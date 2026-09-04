#!/bin/sh
# Osmium Sound — aggiornamento IMMAGINE (schema A/B con RAUC).
#
#   hifi-image-update.sh stage <url|file> <versione>
#       installa il bundle nello slot inattivo con `rauc install` (in streaming
#       se è un URL: RAUC scarica solo i blocchi che scrive, niente file locale),
#       sulla root legacy appena convertita semina prima /data e dopo scrive il
#       selettore sulla ESP. Il sistema in uso non cambia: è il riavvio a far
#       partire il nuovo slot (la fase "apply" del sequencer è vuota).
#   hifi-image-update.sh apply <staged_dir> <versione>
#       no-op (compatibilità col sequencer a due fasi).
set -eu

CMD="${1:-}"
STATUS=/run/hifi-image-status.json
STAGE_ROOT=/var/lib/hifi-player/update/staged/image
VERSION=unknown
if [ -r /usr/local/sbin/hifi-log.sh ]; then
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
    # shellcheck disable=SC1091
    . /usr/local/sbin/hifi-log.sh
    hifi_log_init hifi-image-update
fi

# write_status <state> <progress> <message-en> [key] [params-json]
# Il testo è inglese e serve da ripiego/log; `key` + `params` sono la chiave
# di hifi_i18n.py che l'API traduce nella lingua di chi interroga
# /update/status (kiosk, web admin), così i messaggi escono in en+it.
write_status() {
    state="$1"; progress="$2"; msg="$3"; key="${4:-}"; params="${5:-}"
    [ -n "$params" ] || params='{}'
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s","key":"%s","params":%s}\n' \
        "$state" "$progress" "$VERSION" "$esc" "$key" "$params" > "$STATUS"
}
fail() {  # <message-en> [key] [params-json]
    write_status error 0 "$1" "${2:-}" "${3:-}"
    echo "E: [hifi-image] $1" >&2
    exit 1
}

case "$CMD" in
stage)
    SRC="${2:-}"
    VERSION="${3:-unknown}"
    [ -n "$SRC" ] || fail "Bundle URL or file missing" update.image.badSource
    case "$VERSION" in ''|*[!0-9A-Za-z._-]*) fail "Invalid version" ;; esac
    case "$SRC" in
        https://*) modprobe nbd 2>/dev/null || true ;;
        http://*)  modprobe nbd 2>/dev/null || true ;;
        /*) [ -f "$SRC" ] || fail "Bundle not found: $SRC" update.image.badSource ;;
        *) fail "Invalid source: $SRC" update.image.badSource ;;
    esac
    [ -f /etc/rauc/system.conf ] || fail "RAUC is not configured: device not yet converted to the A/B layout" update.image.notConverted
    legacy=0
    [ -f /usr/lib/osmium/IMAGE_VERSION ] || legacy=1

    WORKDIR="$STAGE_ROOT/$VERSION"
    rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"

    if [ "$legacy" = 1 ]; then
        # Before the settings, the music. A source can be a folder of the root
        # filesystem (/srv, /mnt, /media, /home): on the image that folder is
        # not there any more, so it moves onto /data now — and the seed just
        # below copies the pointers to it (sources, Samba, Lyrion's prefs),
        # which is why this has to run first. Failing here stops the update on
        # purpose: the device stays legacy, with its music untouched, rather
        # than switching to a system where the library is gone.
        if [ -x /usr/local/sbin/hifi-ab-media.py ]; then
            write_status applying 3 "Moving your music onto the data partition…" update.image.media
            /usr/local/sbin/hifi-ab-media.py move \
                || fail "Moving the music folders to the data partition failed" update.image.mediaFailed
        fi
        write_status applying 5 "Copying your settings to the data partition…" update.image.seed
        /usr/local/sbin/hifi-ab-seed.sh || fail "Copying the settings to the data partition failed" update.image.seedFailed
    fi

    VJ="{\"version\":\"$VERSION\"}"
    write_status downloading 10 "Installing system image $VERSION into the standby slot…" update.image.install "$VJ"

    # Avanzamento reale. RAUC stampa "46% Copying image to rootfs.1" una volta
    # sola e poi tace per tutta la copia (20-30 minuti in streaming): la barra
    # resterebbe ferma. Si misura invece quanto è stato scritto sullo slot di
    # destinazione (settori scritti in /sys/class/block/<part>/stat, nessun
    # altro scrive lì) rispetto alla dimensione dell'immagine dichiarata nel
    # manifest del bundle. Se una delle due misure manca si ripiega sulle
    # percentuali grossolane di RAUC.
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
    # shellcheck disable=SC1091
    . /usr/local/sbin/hifi-ab-lib.sh
    # Slot di destinazione = la partizione hifi-root-* che NON è la root in
    # uso. Non si usa `rauc.slot=` dalla cmdline: sul primo avvio dopo la
    # conversione non c'è ancora (lo aggiunge finish in quello stesso boot) e
    # la misura restava muta.
    slot_dev=""
    _root=$(ab_root_dev 2>/dev/null || true)
    _pa=$(ab_part_by_name hifi-root-a 2>/dev/null || true)
    _pb=$(ab_part_by_name hifi-root-b 2>/dev/null || true)
    if [ -n "$_pa" ] && [ -n "$_root" ] && [ "$_root" = "$_pb" ]; then
        slot_dev=$_pa
    elif [ -n "$_pb" ] && [ "$_root" != "$_pb" ]; then
        slot_dev=$_pb
    fi
    img_bytes=$(rauc info --output-format=json "$SRC" 2>/dev/null | python3 -c '
import json, sys
def sizes(o):
    if isinstance(o, dict):
        if isinstance(o.get("size"), int) and "filename" in o:
            yield o["size"]
        for v in o.values():
            yield from sizes(v)
    elif isinstance(o, list):
        for v in o:
            yield from sizes(v)
print(sum(sizes(json.load(sys.stdin).get("images", []))))' 2>/dev/null || echo 0)
    case "$img_bytes" in ''|*[!0-9]*) img_bytes=0 ;; esac
    written_sectors() { awk '{print $7}' "/sys/class/block/${slot_dev#/dev/}/stat" 2>/dev/null || echo 0; }
    base_sectors=0
    [ -n "$slot_dev" ] && base_sectors=$(written_sectors)
    echo "I: [hifi-image] slot di destinazione ${slot_dev:-?}, immagine ${img_bytes} byte"

    # RAUC streams the bundle through an NBD device and issues ONE HTTP range
    # request per read (src/nbd.c, start_read): with the kernel defaults those
    # are 128 KiB, which makes the download bound by the round trip and not by
    # the line — measured, 128 KiB requests give ~1 MiB/s against our release
    # assets while 1 MiB ones give ~5.5 MiB/s on the same file. The helper
    # raises the read-ahead on the devices as soon as RAUC creates them and,
    # when the transfer is over, writes down how large the requests really
    # were, so every update in the field carries its own measurement.
    tune_pid=""
    case "$SRC" in
        http://*|https://*)
            if [ -x /usr/local/sbin/hifi-stream-tune.sh ]; then
                /usr/local/sbin/hifi-stream-tune.sh watch 1800 &
                tune_pid=$!
            fi
            ;;
    esac

    rcfile="$WORKDIR/rauc.rc"
    { rauc install "$SRC" 2>&1; echo "$?" > "$rcfile"; } | while IFS= read -r line; do
        printf '%s\n' "$line"
        [ "$img_bytes" -gt 0 ] && [ -n "$slot_dev" ] && continue
        case "$line" in
            *%*)
                pct=$(printf '%s' "$line" | sed -n 's/^[[:space:]]*\([0-9]\{1,3\}\)%.*/\1/p')
                [ -n "$pct" ] && write_status downloading $(( 10 + pct * 80 / 100 )) "Writing system image $VERSION… ${pct}%" \
                    update.image.write "{\"version\":\"$VERSION\",\"pct\":$pct}"
                ;;
        esac
    done &
    pipe_pid=$!
    last_pct=-1
    while kill -0 "$pipe_pid" 2>/dev/null; do
        sleep 3
        [ "$img_bytes" -gt 0 ] || continue
        [ -n "$slot_dev" ] || continue
        now=$(written_sectors)
        case "$now" in ''|*[!0-9]*) continue ;; esac
        pct=$(( (now - base_sectors) * 512 * 100 / img_bytes ))
        [ "$pct" -gt 99 ] && pct=99
        [ "$pct" -lt 0 ] && pct=0
        if [ "$pct" != "$last_pct" ]; then
            last_pct=$pct
            write_status downloading $(( 10 + pct * 80 / 100 )) "Writing system image $VERSION… ${pct}%" \
                update.image.write "{\"version\":\"$VERSION\",\"pct\":$pct}"
        fi
    done
    wait "$pipe_pid" 2>/dev/null || true
    rc=$(cat "$rcfile" 2>/dev/null || echo 1)
    case "$rc" in ''|*[!0-9]*) rc=1 ;; esac
    if [ -n "$tune_pid" ]; then
        # The watcher stops on its own once RAUC disconnects the NBD device;
        # give it a couple of polls to notice before taking it down, so its
        # summary line makes it into the log.
        i=0
        while kill -0 "$tune_pid" 2>/dev/null && [ "$i" -lt 10 ]; do sleep 1; i=$(( i + 1 )); done
        kill "$tune_pid" 2>/dev/null || true
        wait "$tune_pid" 2>/dev/null || true
        if [ -r /run/hifi-stream-tune.summary ]; then
            echo "I: [hifi-image] $(cat /run/hifi-stream-tune.summary)"
        fi
    fi
    [ "$rc" = 0 ] || fail "rauc install failed (rc=$rc): see /var/log/hifi/hifi-image-update.log" update.image.installFailed "{\"rc\":$rc}"

    if [ "$legacy" = 1 ]; then
        write_status applying 92 "Enabling the A/B boot selector…" update.image.selector
        /usr/local/sbin/hifi-ab-convert.sh select || fail "Writing the A/B boot selector to the ESP failed" update.image.selectorFailed
        /usr/local/sbin/hifi-ab-seed.sh >/dev/null 2>&1 || true
        ab_mount_esp 2>/dev/null || true
        ab_state_set installed
    fi
    printf '%s\n' "$VERSION" > "$WORKDIR/STAGED"
    write_status staged 100 "System image $VERSION installed: the new system starts at the next restart" update.image.staged "$VJ"
    ;;
apply)
    # Niente da fare: RAUC ha già scritto lo slot e impostato il primario; il
    # sequencer riavvia e il selettore GRUB fa il resto.
    VERSION="${3:-unknown}"
    write_status 'done' 100 "System image $VERSION ready" update.image.ready "{\"version\":\"$VERSION\"}"
    ;;
*)
    echo "Uso: $0 stage <url|file> <versione> | apply <staged_dir> <versione>" >&2
    exit 64
    ;;
esac
