#!/usr/bin/env python3
"""HiFi Player — rip an audio CD to tagged FLAC (or WAV) files.

Called by sources_server.py via systemd-run:
    hifi-rip-cd.py /run/hifi-rip-plan.json

The plan (written by the service, root-only) carries the device, the
destination music root, album metadata, one title per track and the CD
ripping settings (`options`, see hifi_cdrip.py). Tracks are read with
cdparanoia — again until two reads agree when "inaccurate retries" asks for
it — de-emphasised or tagged when the TOC flags pre-emphasis, encoded into a
hidden work directory, then the finished album is moved atomically into
<root>/[<prefix>/]<Artist>/<Album>/NN - Title.flac, with ReplayGain tags, a
cover and a ripping log. Progress goes to /run/hifi-rip-status.json, same
shape as the disk-format job. `systemctl stop` (the Cancel button) ends in a
"cancelled" status with nothing left behind.
"""
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys

# hifi_logging.py and hifi_cdrip.py ship in /usr/local/bin alongside the
# Python daemons; this script lives in /usr/local/sbin.
sys.path.insert(0, '/usr/local/bin')
try:
    from hifi_logging import tee_stdio_to_file
    tee_stdio_to_file('rip-cd')
except Exception:
    pass
import hifi_cdrip  # noqa: E402

STATUS = "/run/hifi-rip-status.json"
IMAGE_VERSION_FILE = "/usr/lib/osmium/IMAGE_VERSION"

_proc = None          # the cdparanoia/flac/sox running right now
_cancelled = False


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


def _on_term(signum, frame):
    """Cancel: stop whatever is reading or encoding; main() cleans up."""
    global _cancelled
    _cancelled = True
    p = _proc
    if p is not None:
        try:
            p.terminate()
        except OSError:
            pass


def run(cmd, timeout):
    """subprocess.run that the cancel handler can reach."""
    global _proc
    _proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = _proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _proc.kill()
        out, err = _proc.communicate()
    rc = _proc.returncode
    _proc = None
    return subprocess.CompletedProcess(cmd, rc, out, err)


def extra_tags(pairs):
    """`--tag=` options for (NAME, value) pairs from the plan: Vorbis comment
    names are printable ASCII without '=', and a value never spans lines.
    Repeated names are how FLAC carries multiple values (several artists)."""
    out = []
    for pair in pairs or []:
        try:
            name, value = pair
        except (TypeError, ValueError):
            continue
        name = str(name or "").strip().upper()
        value = " ".join(str(value or "").split())
        if value and re.fullmatch(r"[A-Z0-9_]{1,64}", name):
            out.append(f"--tag={name}={value}")
    return out


def read_toc(device):
    """The TOC as cdparanoia sees it (lengths, pre-emphasis flags); {} when it
    cannot be read — the rip goes on without the flags."""
    try:
        r = run(["cdparanoia", "-Q", "-d", device], timeout=60)
    except Exception:
        return {}
    return hifi_cdrip.parse_cdparanoia_toc((r.stdout or "") + "\n" + (r.stderr or ""))


def read_track(device, num, wav, opt):
    """One cdparanoia read of track `num` into `wav`. Returns (ok, stderr)."""
    cmd = ["cdparanoia", "-q", "-d", device]
    if not opt["paranoia"]:
        cmd.append("-Z")
    if opt["speed"]:
        cmd += ["-S", str(opt["speed"])]
    if opt["offset"]:
        cmd += ["-O", str(opt["offset"])]
    cmd += [str(num), wav]
    try:
        os.remove(wav)
    except OSError:
        pass
    r = run(cmd, timeout=1800)
    ok = r.returncode == 0 and os.path.isfile(wav) and os.path.getsize(wav) > 44
    return ok, (r.stderr or "").strip()


def rip_track(device, num, wav, opt):
    """Read the track, and with retries read it again until two consecutive
    reads carry the same audio. Returns a dict for the log: crc, reads,
    accurate (True when two reads agreed, None when no retry was asked)."""
    ok, err = read_track(device, num, wav, opt)
    if not ok:
        return {"ok": False, "error": err}
    crc = hifi_cdrip.wav_crc32(wav)
    result = {"ok": True, "crc": crc, "reads": 1, "accurate": None, "crcs": [crc]}
    retries = int(opt["retries"] or 0)
    if retries <= 0:
        return result
    alt = wav + ".verify"
    prev = crc
    for _ in range(retries):
        if _cancelled:
            break
        ok2, _err2 = read_track(device, num, alt, opt)
        if not ok2:
            break
        c2 = hifi_cdrip.wav_crc32(alt)
        result["reads"] += 1
        result["crcs"].append(c2)
        if c2 == prev:
            result["accurate"] = True
            try:
                os.remove(alt)
            except OSError:
                pass
            break
        # the two disagree: keep the newest read and compare the next with it
        os.replace(alt, wav)
        result["crc"] = prev = c2
    else:
        result["accurate"] = False
    try:
        os.remove(alt)
    except OSError:
        pass
    if result["accurate"] is None:
        result["accurate"] = False
    return result


def deemphasize(wav):
    """SoX's `deemph` (the CD de-emphasis curve) in place. Returns True on success."""
    out = wav + ".deemph"
    r = run(["sox", wav, out, "deemph"], timeout=600)
    if r.returncode != 0 or not os.path.isfile(out):
        try:
            os.remove(out)
        except OSError:
            pass
        return False
    os.replace(out, wav)
    return True


def image_version():
    try:
        with open(IMAGE_VERSION_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def build_log(plan, opt, drive, toc, results, dest_name):
    """The ripping log, in the spirit of EAC's: what was read, with what, and
    whether each track came out the same twice."""
    L = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L.append(f"Osmium Sound CD ripping log — {now}")
    ver = image_version()
    if ver:
        L.append(f"Osmium Sound {ver}")
    L.append("")
    L.append(f"Used drive  : {drive.get('label') or plan.get('device') or ''}")
    L.append(f"Read offset : {opt['offset']:+d} samples")
    L.append(f"Read mode   : {'cdparanoia (error correction on)' if opt['paranoia'] else 'cdparanoia -Z (error correction off)'}")
    L.append(f"Drive speed : {str(opt['speed']) + 'x' if opt['speed'] else 'drive maximum'}")
    L.append(f"Re-reads    : {opt['retries']} (a track is read again until two reads agree)")
    pre = {"ignore": "ignored", "tag": "tagged (PRE_EMPHASIS)", "filter": "removed with SoX deemph"}[opt["pre_emphasis"]]
    L.append(f"Pre-emphasis: {pre}")
    fmt = "WAV" if opt["format"] == "wav" else f"FLAC, compression level {opt['flac_compression']}"
    L.append(f"Output      : {fmt}")
    L.append(f"ReplayGain  : {'calculated and tagged' if opt['replaygain'] and opt['format'] == 'flac' else 'no'}")
    L.append("")
    L.append(f"Artist      : {plan.get('artist') or ''}")
    L.append(f"Album       : {plan.get('album') or ''}")
    if plan.get("year"):
        L.append(f"Year        : {plan['year']}")
    if plan.get("discid"):
        L.append(f"Disc id     : {plan['discid']}")
    for name, value in plan.get("album_tags") or []:
        if str(name).upper() in ("MUSICBRAINZ_ALBUMID", "MUSICBRAINZ_DISCID"):
            L.append(f"{str(name).upper():<12}: {value}")
    L.append(f"Folder      : {dest_name}")
    L.append("")
    L.append("TOC of the extracted CD")
    L.append("  track |     start |    length | pre-emphasis")
    for num in sorted(toc):
        t = toc[num]
        L.append(f"  {num:5d} | {hifi_cdrip.frames_to_msf(t['begin']):>9} | {hifi_cdrip.frames_to_msf(t['length']):>9} | {'yes' if t['pre'] else 'no'}")
    L.append("")
    for res in results:
        L.append(f"Track {res['num']:2d}: {res['file']}")
        if res.get("crc") is not None:
            L.append(f"    Copy CRC {res['crc']:08X}")
        if res.get("reads", 0) > 1:
            crcs = " ".join(f"{c:08X}" if c is not None else "?" for c in res.get("crcs") or [])
            L.append(f"    Reads {res['reads']}: {crcs}")
        if res.get("accurate") is True:
            L.append("    Accurately ripped (two reads agree)")
        elif res.get("accurate") is False:
            L.append("    Inaccurate: no two reads agreed")
        else:
            L.append("    Copy OK (read once)")
        if res.get("pre"):
            L.append(f"    Pre-emphasis: {res['pre']}")
    L.append("")
    bad = [r["num"] for r in results if r.get("accurate") is False]
    if bad:
        L.append(f"{len(bad)} track(s) could not be read the same way twice: {', '.join(map(str, bad))}")
    else:
        L.append("No errors occurred")
    L.append("")
    L.append("End of status report")
    return "\n".join(L) + "\n"


def main():
    if len(sys.argv) != 2:
        fail("usage: hifi-rip-cd.py <plan.json>")
    try:
        with open(sys.argv[1]) as f:
            plan = json.load(f)
    except Exception as e:
        fail(f"piano di rip illeggibile: {e}")

    signal.signal(signal.SIGTERM, _on_term)
    signal.signal(signal.SIGINT, _on_term)

    device = plan.get("device") or "/dev/cdrom"
    root = plan.get("root") or ""
    tracks = plan.get("tracks") or []
    total = len(tracks)
    opt = hifi_cdrip.normalize(plan.get("options"))
    if not os.path.isdir(root):
        fail("destinazione non montata")
    if not tracks:
        fail("nessuna traccia da rippare")

    artist = plan.get("artist") or "Unknown Artist"
    album = plan.get("album") or "Unknown Album"
    clean = opt["clean_names"]
    album_tags = extra_tags(plan.get("album_tags"))
    year = plan.get("year") or ""
    cover = plan.get("cover") or ""
    if cover and not os.path.isfile(cover):
        cover = ""

    base = os.path.join(root, hifi_cdrip.safe_name(opt["dir_prefix"], "", clean)) if opt["dir_prefix"] else root
    dest = os.path.join(base, hifi_cdrip.safe_name(artist, "Unknown Artist", clean),
                        hifi_cdrip.safe_name(album, "Unknown Album", clean))
    work = os.path.join(root, ".partial-rip")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    def cancelled():
        if _cancelled:
            shutil.rmtree(work, ignore_errors=True)
            write_status("cancelled", 0, total, 0, "Copia annullata")
            sys.exit(0)

    write_status("ripping", 0, total, 0, "Lettura dell'indice del disco…")
    toc = read_toc(device)
    drive = hifi_cdrip.drive_info(device)
    cancelled()

    results, outputs = [], []
    for i, tr in enumerate(tracks):
        num = int(tr.get("num") or (i + 1))
        title = tr.get("title") or f"Track {num:02d}"
        write_status("ripping", num, total, int(i * 100 / total),
                     f"Traccia {num}/{total}: {title}")
        wav = os.path.join(work, f"track{num:02d}.wav")
        fname = f"{num:02d} - {hifi_cdrip.safe_name(title, f'Track {num:02d}', clean)}"
        res = rip_track(device, num, wav, opt)
        cancelled()
        if not res.get("ok"):
            shutil.rmtree(work, ignore_errors=True)
            fail(f"lettura traccia {num} fallita (disco rovinato?)", num, total)
        res["num"] = num
        pre_flag = bool((toc.get(num) or {}).get("pre"))
        pre_tags = []
        if pre_flag and opt["pre_emphasis"] == "filter":
            res["pre"] = "removed with SoX deemph" if deemphasize(wav) else "flagged, filter FAILED, left as read"
            cancelled()
        elif pre_flag and opt["pre_emphasis"] == "tag":
            pre_tags = ["--tag=PRE_EMPHASIS=true"]
            res["pre"] = "flagged, tagged PRE_EMPHASIS"
        elif pre_flag:
            res["pre"] = "flagged, ignored"
        track_artist = tr.get("artist") or artist
        if opt["format"] == "wav":
            out = os.path.join(work, fname + ".wav")
            os.replace(wav, out)
        else:
            out = os.path.join(work, fname + ".flac")
            cmd = ["flac", "--silent", f"-{opt['flac_compression']}", "--force",
                   f"--tag=ARTIST={track_artist}", f"--tag=ALBUM={album}",
                   f"--tag=TITLE={title}", f"--tag=TRACKNUMBER={num}",
                   f"--tag=TRACKTOTAL={total}"]
            if year:
                cmd.append(f"--tag=DATE={year}")
            if plan.get("discid"):
                cmd.append(f"--tag=DISCID={plan['discid']}")
            cmd += album_tags + extra_tags(tr.get("tags")) + pre_tags
            if cover:
                cmd.append(f"--picture={cover}")
            cmd += ["-o", out, wav]
            r = run(cmd, timeout=900)
            try:
                os.remove(wav)
            except OSError:
                pass
            cancelled()
            if r.returncode != 0 or not os.path.isfile(out):
                shutil.rmtree(work, ignore_errors=True)
                fail(f"codifica traccia {num} fallita", num, total)
        res["file"] = os.path.basename(out)
        results.append(res)
        outputs.append(out)

    if opt["replaygain"] and opt["format"] == "flac" and outputs:
        write_status("ripping", total, total, 99, "ReplayGain…")
        run(["metaflac", "--add-replay-gain"] + outputs, timeout=1800)
        cancelled()

    if cover:
        shutil.copyfile(cover, os.path.join(work, "cover.jpg"))
    if opt["log_file"]:
        log_name = hifi_cdrip.safe_name(f"{artist} - {album}", "rip", clean) + ".log"
        with open(os.path.join(work, log_name), "w", encoding="utf-8") as f:
            f.write(build_log(plan, opt, drive, toc, results, os.path.relpath(dest, root)))

    # Album complete: move into place in one pass so the library never sees a
    # half-ripped folder.
    os.makedirs(dest, exist_ok=True)
    for name in sorted(os.listdir(work)):
        os.replace(os.path.join(work, name), os.path.join(dest, name))
    shutil.rmtree(work, ignore_errors=True)

    inaccurate = sum(1 for r in results if r.get("accurate") is False)
    msg = f"{album} — {total} tracce"
    if inaccurate:
        msg += f" ({inaccurate} non verificate)"
    ejected = False
    if opt["eject"]:
        ejected = run(["eject", device], timeout=30).returncode == 0
    write_status("done", total, total, 100, msg, dest=dest, inaccurate=inaccurate, ejected=ejected)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # any unexpected crash still lands in the status file
        fail(f"errore inatteso: {e}")
