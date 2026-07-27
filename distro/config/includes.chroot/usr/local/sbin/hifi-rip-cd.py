#!/usr/bin/env python3
"""HiFi Player — rip an audio CD to tagged FLAC files.

Called by sources_server.py via systemd-run:
    hifi-rip-cd.py /run/hifi-rip-plan.json

The plan (written by the service, root-only) carries the device, the
destination music root, album metadata and one title per track. Tracks are
ripped with cdparanoia and encoded with flac into a hidden work directory,
then the finished album is moved atomically into
<root>/<Artist>/<Album>/NN - Title.flac. Progress goes to
/run/hifi-rip-status.json, same shape as the disk-format job.
"""
import json
import os
import re
import shutil
import subprocess
import sys

try:
    # hifi_logging.py ships in /usr/local/bin alongside the Python daemons;
    # this script lives in /usr/local/sbin, so it isn't found without this.
    # Best-effort: a missing module must never stop a CD rip.
    sys.path.insert(0, '/usr/local/bin')
    from hifi_logging import tee_stdio_to_file
    tee_stdio_to_file('rip-cd')
except Exception:
    pass

STATUS = "/run/hifi-rip-status.json"


def write_status(state, track, total, progress, message, **extra):
    payload = {"state": state, "track": track, "total": total,
               "progress": progress, "message": message}
    payload.update(extra)
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, STATUS)


def fail(message, track=0, total=0):
    write_status("error", track, total, 0, message)
    print(f"E: [hifi-rip] {message}", file=sys.stderr)
    sys.exit(1)


def safe_name(value, fallback):
    """Filesystem-safe file/dir component (also fine on exFAT)."""
    v = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")
    return v[:120] or fallback


def main():
    if len(sys.argv) != 2:
        fail("usage: hifi-rip-cd.py <plan.json>")
    try:
        with open(sys.argv[1]) as f:
            plan = json.load(f)
    except Exception as e:
        fail(f"piano di rip illeggibile: {e}")

    device = plan.get("device") or "/dev/cdrom"
    root = plan.get("root") or ""
    tracks = plan.get("tracks") or []
    total = len(tracks)
    if not os.path.isdir(root):
        fail("destinazione non montata")
    if not tracks:
        fail("nessuna traccia da rippare")

    artist = plan.get("artist") or "Unknown Artist"
    album = plan.get("album") or "Unknown Album"
    year = plan.get("year") or ""
    cover = plan.get("cover") or ""
    if cover and not os.path.isfile(cover):
        cover = ""

    dest = os.path.join(root, safe_name(artist, "Unknown Artist"),
                        safe_name(album, "Unknown Album"))
    work = os.path.join(root, ".partial-rip")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    for i, tr in enumerate(tracks):
        num = int(tr.get("num") or (i + 1))
        title = tr.get("title") or f"Track {num:02d}"
        write_status("ripping", num, total, int(i * 100 / total),
                     f"Traccia {num}/{total}: {title}")
        wav = os.path.join(work, f"track{num:02d}.wav")
        flac = os.path.join(work, f"{num:02d} - {safe_name(title, f'Track {num:02d}')}.flac")
        r = subprocess.run(["cdparanoia", "-q", "-d", device, str(num), wav],
                           capture_output=True, text=True, timeout=1200)
        if r.returncode != 0 or not os.path.isfile(wav):
            shutil.rmtree(work, ignore_errors=True)
            fail(f"lettura traccia {num} fallita (disco rovinato?)", num, total)
        cmd = ["flac", "--silent", "--best", "--force",
               f"--tag=ARTIST={artist}", f"--tag=ALBUM={album}",
               f"--tag=TITLE={title}", f"--tag=TRACKNUMBER={num}",
               f"--tag=TRACKTOTAL={total}"]
        if year:
            cmd.append(f"--tag=DATE={year}")
        if plan.get("discid"):
            cmd.append(f"--tag=DISCID={plan['discid']}")
        if cover:
            cmd.append(f"--picture={cover}")
        cmd += ["-o", flac, wav]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        os.remove(wav)
        if r.returncode != 0 or not os.path.isfile(flac):
            shutil.rmtree(work, ignore_errors=True)
            fail(f"codifica traccia {num} fallita", num, total)

    if cover:
        shutil.copyfile(cover, os.path.join(work, "cover.jpg"))

    # Album complete: move into place in one pass so the library never sees a
    # half-ripped folder.
    os.makedirs(dest, exist_ok=True)
    for name in sorted(os.listdir(work)):
        os.replace(os.path.join(work, name), os.path.join(dest, name))
    shutil.rmtree(work, ignore_errors=True)

    write_status("done", total, total, 100, f"{album} — {total} tracce",
                 dest=dest)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # any unexpected crash still lands in the status file
        fail(f"errore inatteso: {e}")
