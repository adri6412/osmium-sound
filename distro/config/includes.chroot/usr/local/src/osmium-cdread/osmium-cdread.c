/*
 * osmium-cdread — ESP-style audio-CD reader for live CD playback.
 *
 * The Lyrion "CD Player" plugin streams audio CDs in real time by piping a
 * capture tool into flac. The stock capture (cdda2wav/icedax at a fixed speed,
 * no error handling) drops samples when a USB optical drive stalls mid-track,
 * which the player hears as a crackle; cdparanoia instead *stops to re-read*,
 * which the player hears as buffering. A real CD player does neither: it reads
 * ahead into a RAM cushion ("Electronic Shock Protection") and, on a sector it
 * cannot recover, conceals the gap and keeps going without ever pausing.
 *
 * This reader does the same. A reader thread pulls raw CDDA sectors from the
 * drive as fast as the drive allows into a bounded ring buffer; a writer thread
 * drains the ring to stdout at whatever rate the consumer takes. The ring is a
 * ~25 s cushion, so a drive stall is absorbed silently as long as it is shorter
 * than the cushion. A sector that will not read after a few retries is
 * concealed (the last good sector is repeated; silence until the first good
 * one) and the read advances — the stream never blocks on the drive.
 *
 * Output is a canonical 44-byte WAV header (44.1 kHz / 16-bit / stereo, little
 * endian — the native CDDA layout on x86) followed by the track's PCM, sized
 * exactly from the TOC. It is a drop-in for the plugin's `cdda2wav ... -` stage.
 * With --raw it emits the headerless PCM instead, for the plugin's raw rule.
 *
 * Usage: osmium-cdread --device <dev> --track <n> [--raw]   (WAV on stdout)
 */
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE            /* usleep() for the flock retry loop */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/file.h>
#include <signal.h>
#include <getopt.h>
#include <pthread.h>

#include <cdio/cdio.h>
#include <cdio/paranoia/cdda.h>

#define SECTOR_BYTES   CDIO_CD_FRAMESIZE_RAW   /* 2352 */
#define SECTORS_PER_S  75                      /* CDDA frames per second */
#define RING_SECTORS   (25 * SECTORS_PER_S)    /* ~25 s cushion (~4.2 MiB) */
#define MAX_RETRY      4                        /* re-reads before concealing */
#define LOCK_PATH      "/tmp/osmium-cdread.lock" /* single-reader-per-drive coord */

/* Bounded ring buffer of raw CDDA sectors, shared reader -> writer. */
static uint8_t  ring[RING_SECTORS][SECTOR_BYTES];
static int      head, tail, count;   /* head: next write, tail: next read */
static int      producer_done;       /* reader has pushed the last sector */
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t  not_full  = PTHREAD_COND_INITIALIZER;
static pthread_cond_t  not_empty = PTHREAD_COND_INITIALIZER;

static void ring_push(const uint8_t *sector) {
    pthread_mutex_lock(&lock);
    while (count == RING_SECTORS)
        pthread_cond_wait(&not_full, &lock);
    memcpy(ring[head], sector, SECTOR_BYTES);
    head = (head + 1) % RING_SECTORS;
    count++;
    pthread_cond_signal(&not_empty);
    pthread_mutex_unlock(&lock);
}

/* Pop one sector into out; returns 1 on a sector, 0 when drained and done. */
static int ring_pop(uint8_t *out) {
    pthread_mutex_lock(&lock);
    while (count == 0 && !producer_done)
        pthread_cond_wait(&not_empty, &lock);
    if (count == 0 && producer_done) {
        pthread_mutex_unlock(&lock);
        return 0;
    }
    memcpy(out, ring[tail], SECTOR_BYTES);
    tail = (tail + 1) % RING_SECTORS;
    count--;
    pthread_cond_signal(&not_full);
    pthread_mutex_unlock(&lock);
    return 1;
}

static void mark_done(void) {
    pthread_mutex_lock(&lock);
    producer_done = 1;
    pthread_cond_broadcast(&not_empty);
    pthread_mutex_unlock(&lock);
}

/* Reader-thread context. */
struct reader_ctx {
    cdrom_drive_t *drive;
    lsn_t first, last;        /* inclusive track sector range */
    unsigned long concealed;  /* sectors concealed (stats) */
};

static void *reader_thread(void *arg) {
    struct reader_ctx *c = arg;
    uint8_t last_good[SECTOR_BYTES];
    memset(last_good, 0, sizeof last_good);   /* silence until first good read */

    for (lsn_t lsn = c->first; lsn <= c->last; lsn++) {
        uint8_t buf[SECTOR_BYTES];
        int ok = 0;
        for (int attempt = 0; attempt <= MAX_RETRY; attempt++) {
            /* cdio_cddap_read returns the sector count read (1), else <= 0. */
            if (cdio_cddap_read(c->drive, buf, lsn, 1) == 1) {
                ok = 1;
                break;
            }
        }
        if (ok) {
            memcpy(last_good, buf, SECTOR_BYTES);
            ring_push(buf);
        } else {
            /* Conceal: repeat the last good sector (silence if none yet) and
             * keep going — never stop the stream on the drive. */
            c->concealed++;
            ring_push(last_good);
        }
    }
    mark_done();
    if (c->concealed)
        fprintf(stderr, "osmium-cdread: concealed %lu sector(s)\n", c->concealed);
    return NULL;
}

/* Little-endian field writers for the WAV header. */
static void put_u32le(uint8_t *p, uint32_t v) {
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}
static void put_u16le(uint8_t *p, uint16_t v) {
    p[0] = v; p[1] = v >> 8;
}

static int write_all(int fd, const void *buf, size_t n) {
    const uint8_t *p = buf;
    while (n) {
        ssize_t w = write(fd, p, n);
        if (w < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        p += w; n -= (size_t)w;
    }
    return 0;
}

static int write_wav_header(int fd, uint32_t data_bytes) {
    const uint32_t rate = 44100, channels = 2, bits = 16;
    const uint32_t block_align = channels * bits / 8;      /* 4 */
    const uint32_t byte_rate   = rate * block_align;       /* 176400 */
    uint8_t h[44];
    memcpy(h, "RIFF", 4);
    put_u32le(h + 4, 36 + data_bytes);
    memcpy(h + 8, "WAVE", 4);
    memcpy(h + 12, "fmt ", 4);
    put_u32le(h + 16, 16);              /* PCM fmt chunk size */
    put_u16le(h + 20, 1);               /* PCM */
    put_u16le(h + 22, channels);
    put_u32le(h + 24, rate);
    put_u32le(h + 28, byte_rate);
    put_u16le(h + 32, block_align);
    put_u16le(h + 34, bits);
    memcpy(h + 36, "data", 4);
    put_u32le(h + 40, data_bytes);
    return write_all(fd, h, sizeof h);
}

int main(int argc, char **argv) {
    const char *device = NULL;
    long track = 0;
    long offset_sectors = 0;   /* seek: sectors from the start of the track */
    int raw = 0;

    static struct option opts[] = {
        { "device", required_argument, 0, 'd' },
        { "track",  required_argument, 0, 't' },
        { "offset", required_argument, 0, 'O' },
        { "raw",    no_argument,       0, 'r' },
        { 0, 0, 0, 0 },
    };
    /* getopt_long_only so the plugin's single-dash "-offset N" (CDPLAY.pm
     * expands $CDOFFSET$ to "-offset <sectors>") matches the long option. */
    int opt;
    while ((opt = getopt_long_only(argc, argv, "d:t:O:r", opts, NULL)) != -1) {
        switch (opt) {
        case 'd': device = optarg; break;
        case 't': track = strtol(optarg, NULL, 10); break;
        case 'O': offset_sectors = strtol(optarg, NULL, 10); break;
        case 'r': raw = 1; break;
        default:
            fprintf(stderr, "usage: %s --device <dev> --track <n> [-offset <sectors>] [--raw]\n", argv[0]);
            return 2;
        }
    }
    if (!device || track < 1) {
        fprintf(stderr, "usage: %s --device <dev> --track <n> [-offset <sectors>] [--raw]\n", argv[0]);
        return 2;
    }
    if (offset_sectors < 0) offset_sectors = 0;

    /* Single reader per drive. Two libcdio opens on one cheap USB-ATAPI drive
     * disrupt each other and stall the live read, so only one instance may hold
     * the drive at a time. Lyrion starts a fresh capture before tearing the old
     * one down, in two cases that MUST be told apart by the only thing visible
     * at exec time — whether the new capture reads the same (--track, -offset):
     *   - seek / track change: the new capture has a DIFFERENT --track or
     *     -offset and must take over; Lyrion never kills the predecessor, so we
     *     do it ourselves (SIGTERM, then wait for its lock to drop). The old
     *     reader may even be wedged on a stalled drive read; SIGTERM frees it.
     *   - gapless pre-open: when a track reaches PLAYING, Lyrion opens the NEXT
     *     stream ahead of time; for a single CD track that is the SAME track and
     *     offset as the live reader, and it must NOT disturb it, so an identical
     *     request yields and produces nothing, like cdda2wav's harmless second
     *     instance. (Pause does NOT reopen: the plugin's "pausestop" pref is
     *     forced off by hifi-cdplayer-tolerate.sh, so squeezelite buffer-pauses
     *     the live stream in place — this reader simply blocks on the full ring
     *     and resumes — and never spawns an identical reopen that would wrongly
     *     yield here.)
     * Coordinate through a small lock file holding "pid track offset" of the
     * current holder. We lock a dedicated file (not the device node: an
     * O_RDONLY open of a busy drive can fail, silently skipping the lock). */
    int lockfd = open(LOCK_PATH, O_RDWR | O_CREAT | O_CLOEXEC, 0666);
    if (lockfd >= 0) {
        if (flock(lockfd, LOCK_EX | LOCK_NB) != 0) {
            /* Someone holds the drive — find out who, and what they are reading. */
            char buf[64];
            long h_pid = 0, h_track = -1, h_off = -1;
            lseek(lockfd, 0, SEEK_SET);
            ssize_t n = read(lockfd, buf, sizeof buf - 1);
            if (n > 0) { buf[n] = '\0'; sscanf(buf, "%ld %ld %ld", &h_pid, &h_track, &h_off); }
            if (h_track == track && h_off == offset_sectors)
                return 0;                       /* gapless pre-open / duplicate — yield */
            if (h_pid > 0) kill((pid_t)h_pid, SIGTERM);   /* seek / track change — take over */
            int got = 0;
            for (int i = 0; i < 50; i++) {      /* up to ~5 s for the holder to drop */
                if (flock(lockfd, LOCK_EX | LOCK_NB) == 0) { got = 1; break; }
                usleep(100000);
            }
            if (!got) return 0;
        }
        /* Record who we are and what we are reading, for the next taker. */
        char rec[64];
        int rl = snprintf(rec, sizeof rec, "%ld %ld %ld\n",
                          (long)getpid(), track, offset_sectors);
        if (ftruncate(lockfd, 0) == 0 && lseek(lockfd, 0, SEEK_SET) == 0)
            (void)!write(lockfd, rec, (size_t)rl);
    }
    /* lockfd intentionally stays open for the process lifetime to hold the lock. */

    cdrom_drive_t *drive = cdio_cddap_identify(device, 0, NULL);
    if (!drive) {
        fprintf(stderr, "osmium-cdread: cannot identify drive %s\n", device);
        return 1;
    }
    cdio_cddap_verbose_set(drive, CDDA_MESSAGE_FORGETIT, CDDA_MESSAGE_FORGETIT);
    if (cdio_cddap_open(drive) != 0) {
        fprintf(stderr, "osmium-cdread: cannot open drive %s\n", device);
        cdio_cddap_close(drive);
        return 1;
    }
    /* Cooperative read speed (parity with cdda2wav --speed 4). Requesting the
     * drive's maximum (-1) makes cheap USB-ATAPI bridges reset under sustained
     * full-rate reads; 4x is well within the drive's margin and the RAM ring
     * still stays far ahead of 1x playback. */
    cdio_cddap_speed_set(drive, 4);

    track_t tracks = cdio_cddap_tracks(drive);
    if (track > tracks) {
        fprintf(stderr, "osmium-cdread: track %ld > %d on disc\n", track, tracks);
        cdio_cddap_close(drive);
        return 1;
    }
    lsn_t first = cdio_cddap_track_firstsector(drive, (track_t)track);
    lsn_t last  = cdio_cddap_track_lastsector(drive, (track_t)track);
    if (first < 0 || last < first) {
        fprintf(stderr, "osmium-cdread: bad sector range for track %ld\n", track);
        cdio_cddap_close(drive);
        return 1;
    }

    /* Seek: start offset_sectors into the track (clamped within the track). */
    if (offset_sectors > 0) {
        lsn_t want = first + (lsn_t)offset_sectors;
        first = (want > last) ? last : want;
    }

    uint64_t sectors   = (uint64_t)(last - first + 1);
    uint64_t data_bytes = sectors * SECTOR_BYTES;
    if (!raw && write_wav_header(STDOUT_FILENO, (uint32_t)data_bytes) != 0) {
        fprintf(stderr, "osmium-cdread: write error (header)\n");
        cdio_cddap_close(drive);
        return 1;
    }

    struct reader_ctx ctx = { .drive = drive, .first = first, .last = last };
    pthread_t rt;
    if (pthread_create(&rt, NULL, reader_thread, &ctx) != 0) {
        fprintf(stderr, "osmium-cdread: cannot start reader thread\n");
        cdio_cddap_close(drive);
        return 1;
    }

    int rc = 0;
    uint8_t out[SECTOR_BYTES];
    while (ring_pop(out)) {
        if (write_all(STDOUT_FILENO, out, SECTOR_BYTES) != 0) {
            /* Consumer went away (flac/squeezelite closed the pipe). Stop. */
            rc = 1;
            break;
        }
    }

    /* If we broke out early, drain the reader so it does not block on a full
     * ring, then join. */
    if (rc != 0) {
        pthread_mutex_lock(&lock);
        count = 0;
        producer_done = 1;
        pthread_cond_broadcast(&not_full);
        pthread_mutex_unlock(&lock);
    }
    pthread_join(rt, NULL);

    cdio_cddap_close(drive);
    return rc;
}
