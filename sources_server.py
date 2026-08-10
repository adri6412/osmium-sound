#!/usr/bin/env python3
"""
HiFi Player — Music Sources manager.

A small self-contained web service (port 8080) that lets the user add music
sources to Lyrion Music Server from a browser on their phone/PC:

  * Local folders  → added directly to Lyrion's mediadirs
  * SMB shares     → mounted on /mnt/hifi-sources/<name> (cifs) then added
                     to mediadirs (Lyrion sees them as local folders)

State is persisted in /etc/hifi-sources.json; SMB shares are re-mounted when
this service starts (so they survive reboots without touching /etc/fstab).

Runs as root (needs mount.cifs and to restart Lyrion).
"""
from flask import Flask, jsonify, request, Response
import json
import os
import re
import glob
import time
import subprocess
import threading
import io
import tarfile
import hashlib
import secrets
import shutil
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timezone

import hifi_backup as hb
from hifi_logging import tee_stdio_to_file
from hifi_i18n import t as _ht
# Every print() below keeps reaching the console/journald unchanged AND now also
# lands in a size-rotated file at /var/log/hifi/sources.log (journald alone is
# volatile on this image) — picked up by the support-bundle endpoint.
tee_stdio_to_file('sources')

app = Flask(__name__)
# Hard ceiling on any request body (restore archive, FIR filter upload) BEFORE
# Werkzeug buffers it into request.files/request.form. Without this, a client
# can stream an unbounded body and it gets fully received/spooled to disk
# before any of this file's own per-route size checks ever run — those checks
# are still kept below as the real business-logic limits, this is just the
# outer backstop. 80MB comfortably covers a couple of FIR filters + tiny
# config files in one restore archive.
app.config['MAX_CONTENT_LENGTH'] = 80 * 1024 * 1024


@app.errorhandler(413)
def _request_too_large(_e):
    return _err("msg.fileTooLarge", 413)


# The Electron UI now talks to this service natively (cross-origin from the
# file:// renderer), so allow CORS like api_server does. Falls back gracefully
# if flask_cors isn't present.
try:
    from flask_cors import CORS
    CORS(app)
except Exception:
    @app.after_request
    def _cors(resp):
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return resp

STATE_FILE = "/etc/hifi-sources.json"
MOUNT_ROOT = "/mnt/hifi-sources"
INTERNAL_MOUNT_ROOT = "/mnt/hifi-internal"
# Adopted USB disks (type "usb") mount here, read-write, keyed by stable
# PARTUUID/UUID — distinct from USB_MOUNT_ROOT below, which is the ephemeral
# read-only browse mount for USB sticks that haven't been adopted.
USB_ADOPTED_ROOT = "/mnt/hifi-usb"
# Local music folders may only be added from these base directories. This
# keeps the (root-privileged) service from being pointed at arbitrary paths
# such as /etc or /root via the add-local-source API.
ALLOWED_LOCAL_ROOTS = ("/mnt", "/media", "/srv", "/home", MOUNT_ROOT, INTERNAL_MOUNT_ROOT, USB_ADOPTED_ROOT)
LYRION_SERVICE = "lyrionmusicserver.service"
SAMBA_SHARES_FILE = "/etc/samba/hifi-shares.conf"
SAMBA_CRED_FILE = "/etc/hifi-player/samba-cred.json"
SAMBA_USER = "hifimusic"
FORMAT_STATUS = "/run/hifi-format-status.json"
FORMAT_UNIT = "hifi-format-disk"
FORMAT_SCRIPT = "/usr/local/sbin/hifi-format-disk.sh"
CD_DEVICE = "/dev/cdrom"
RIP_STATUS = "/run/hifi-rip-status.json"
RIP_PLAN = "/run/hifi-rip-plan.json"
RIP_COVER = "/run/hifi-rip-cover.jpg"
RIP_UNIT = "hifi-rip-cd"
RIP_SCRIPT = "/usr/local/sbin/hifi-rip-cd.py"
LYRION_RPC = "http://127.0.0.1:9000/jsonrpc.js"
PREFS_GLOBS = [
    "/var/lib/squeezeboxserver/prefs/server.prefs",
    "/var/lib/lyrion*/prefs/server.prefs",
    "/var/lib/lyrionmusicserver/prefs/server.prefs",
]
# The appliance skips Lyrion's web setup wizard, so `playlistdir` is never set
# and "save queue as playlist" silently fails. We provision a writable folder.
DEFAULT_PLAYLISTDIR = "/var/lib/squeezeboxserver/playlists"

_lock = threading.Lock()


# ─────────────────────────── state ──────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {"sources": []}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)
    try:
        os.chmod(STATE_FILE, 0o600)
    except Exception:
        pass


def _slug(*parts):
    s = "-".join(p for p in parts if p)
    # strip leading/trailing dots too, so a value like ".." can never survive
    # and turn os.path.join(MOUNT_ROOT, slug) into a path-traversal.
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_.") or "share"


def _field_ok(value):
    """True if `value` is safe to pass as a mount option / command argument.

    The SMB fields below are interpolated into mount(8) `-o` options and into
    the command argv; a comma, newline or a leading '-' would let a malicious
    value add arbitrary mount options or be parsed as a flag, so only allow a
    conservative character set and reject leading dashes.
    """
    v = "" if value is None else str(value)
    return bool(re.fullmatch(r"[^\x00-\x1f,]*", v)) and not v.startswith("-")


def _label_ok(value):
    """Safe volume label: alphanumerics, space, underscore, dot, hyphen."""
    v = "" if value is None else str(value)
    return bool(re.fullmatch(r"[A-Za-z0-9 _.-]{1,16}", v))


def _path_ok(value):
    """Safe block-device path: must start with /dev/ and contain no shell metas."""
    v = "" if value is None else str(value)
    return bool(re.fullmatch(r"/dev/[A-Za-z0-9/_-]+", v))


def _run(cmd, timeout=30):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _run_json(cmd, timeout=30):
    r = _run(cmd, timeout=timeout)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout or "{}")
    except Exception:
        return None


# ─────────────────────────── SMB mounting ───────────────────────────
def mount_smb(src):
    """Mount one SMB source. Returns (ok, message)."""
    server = src["server"].strip().strip("/")
    share = src["share"].strip().strip("/")
    username = src.get("username", "")
    password = src.get("password", "")
    for value in (server, share, username, password):
        if not _field_ok(value):
            return False, "Valore non valido in server/condivisione/credenziali"

    # The mountpoint is derived from user-supplied server/share; resolve it and
    # make sure it can never escape MOUNT_ROOT before we create or mount onto it.
    root = os.path.realpath(MOUNT_ROOT)
    mountpoint = os.path.realpath(src["mountpoint"])
    if mountpoint != root and not mountpoint.startswith(root + os.sep):
        return False, "mountpoint non valido"
    os.makedirs(mountpoint, exist_ok=True)

    if os.path.ismount(mountpoint):
        return True, "già montato"

    unc = f"//{server}/{share}"
    base_opts = "uid=0,gid=0,iocharset=utf8,ro,file_mode=0644,dir_mode=0755"

    cred_path = None
    try:
        if username:
            # Credentials go in a private temp file rather than the -o string,
            # so the password never shows up in argv / `ps aux` output.
            fd, cred_path = tempfile.mkstemp(prefix="hifi-smb-cred-")
            with os.fdopen(fd, "w") as f:
                f.write(f"username={username}\npassword={password}\n")
            os.chmod(cred_path, 0o600)
            cred_opt = f",credentials={cred_path}"
        else:
            cred_opt = ",guest"

        last = ""
        for vers in ("3.1.1", "3.0", "2.1", "1.0"):
            opts = f"{base_opts}{cred_opt},vers={vers}"
            r = _run(["mount", "-t", "cifs", unc, mountpoint, "-o", opts])
            if r.returncode == 0:
                return True, f"montato (SMB {vers})"
            last = (r.stderr or r.stdout).strip()
        return False, last or "mount fallito"
    finally:
        if cred_path:
            try:
                os.remove(cred_path)
            except OSError:
                pass


def umount(mountpoint):
    if os.path.ismount(mountpoint):
        _run(["umount", "-l", mountpoint])


def _system_disk_paths():
    """Return a set of disk paths that are part of the running system and must
    never be offered for adoption or formatting."""
    system = set()
    for target in ("/", "/boot/efi"):
        try:
            r = _run(["findmnt", "-no", "SOURCE", target], timeout=5)
            if r.returncode != 0 or not r.stdout.strip():
                continue
            src = r.stdout.strip()
            # findmnt returns the partition; resolve to the parent disk via lsblk.
            if src.startswith("/dev/"):
                pr = _run(["lsblk", "-no", "PKNAME", src], timeout=5)
                if pr.returncode == 0 and pr.stdout.strip():
                    system.add("/dev/" + pr.stdout.strip().split()[0])
            elif src.startswith("UUID=") or src.startswith("PARTUUID="):
                # resolve to a device node
                pr = _run(["findfs", src], timeout=5)
                if pr.returncode == 0 and pr.stdout.strip().startswith("/dev/"):
                    dev = pr.stdout.strip()
                    pr2 = _run(["lsblk", "-no", "PKNAME", dev], timeout=5)
                    if pr2.returncode == 0 and pr2.stdout.strip():
                        system.add("/dev/" + pr2.stdout.strip().split()[0])
        except Exception:
            pass
    return system


def _lsblk_full():
    return _run_json(["lsblk", "-J", "-b", "-o",
                        "PATH,NAME,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,RM,FSTYPE,LABEL,UUID,PARTUUID,PKNAME,MOUNTPOINT"],
                       timeout=10)


def _internal_disks():
    """Enumerate internal (non-USB, non-optical, non-system) block devices.
    Returns a list of dicts with partitions and adoption state."""
    data = _lsblk_full() or {}
    system_disks = _system_disk_paths()

    # Build a map of mounted partitions outside allowed roots.
    mounted_outside = set()
    for dev in data.get("blockdevices", []):
        for part in dev.get("children") or []:
            mp = part.get("mountpoint")
            if mp:
                try:
                    rp = os.path.realpath(mp)
                    allowed = False
                    for root in ("/mnt", "/media", INTERNAL_MOUNT_ROOT, USB_MOUNT_ROOT):
                        if rp == root or rp.startswith(root + os.sep):
                            allowed = True
                            break
                    if not allowed:
                        mounted_outside.add(dev.get("path"))
                except Exception:
                    mounted_outside.add(dev.get("path"))
            if part.get("fstype") == "swap":
                system_disks.add(dev.get("path"))

    state = load_state()
    by_partuuid = {}
    by_uuid = {}
    for s in state.get("sources", []):
        if s.get("type") == "internal":
            if s.get("partuuid"):
                by_partuuid[s["partuuid"].lower()] = s
            if s.get("fsuuid"):
                by_uuid[s["fsuuid"].lower()] = s

    out = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk":
            continue
        if dev.get("tran") == "usb" or dev.get("rm") or dev.get("type") == "rom":
            continue
        path = dev.get("path")
        if not path or path in system_disks or path in mounted_outside:
            continue
        if dev.get("size", 0) <= 0:
            continue

        partitions = []
        has_data = False
        adopted = False
        source_id = None
        for part in dev.get("children") or []:
            if part.get("type") != "part":
                continue
            p = {
                "path": part.get("path"),
                "name": part.get("name"),
                "fstype": part.get("fstype"),
                "label": part.get("label"),
                "uuid": part.get("uuid"),
                "partuuid": part.get("partuuid"),
                "size": part.get("size"),
                "mountpoint": part.get("mountpoint"),
            }
            partitions.append(p)
            if part.get("fstype"):
                has_data = True
            pu = (part.get("partuuid") or "").lower()
            uu = (part.get("uuid") or "").lower()
            if pu in by_partuuid or uu in by_uuid:
                adopted = True
                source_id = (by_partuuid.get(pu) or by_uuid.get(uu) or {}).get("id")

        serial = dev.get("serial") or ""
        size = dev.get("size") or 0
        confirm = hashlib.sha256(f"{path}:{serial}:{size}".encode()).hexdigest()[:12]
        out.append({
            "path": path,
            "model": (dev.get("model") or "").strip(),
            "serial": serial,
            "size": size,
            "fstype": dev.get("fstype"),
            "label": dev.get("label"),
            "has_data": has_data,
            "adopted": adopted,
            "source_id": source_id,
            "confirm": confirm,
            "partitions": partitions,
        })
    return out


def _adopted_disk_sources():
    """Adopted internal disks AND adopted (read-write) USB disks — the two
    source types that get a stable mountpoint, a Samba share, and can be a CD
    rip destination. Ephemeral read-only USB browse mounts are not included."""
    return [s for s in load_state().get("sources", []) if s.get("type") in ("internal", "usb")]


def _share_name(label):
    base = _slug(label or "Musica")
    if not base:
        base = "Musica"
    names = set()
    for s in _adopted_disk_sources():
        names.add(s.get("share") or "Musica")
    if base not in names:
        return base
    n = 2
    while f"{base}-{n}" in names:
        n += 1
    return f"{base}-{n}"


def _ensure_samba_uid_gid():
    """Ensure the dedicated music/Samba user exists; return its (uid, gid).
    exFAT/vfat mount options require numeric ids, not a username."""
    import pwd
    try:
        ent = pwd.getpwnam(SAMBA_USER)
        return ent.pw_uid, ent.pw_gid
    except KeyError:
        _run(["useradd", "-r", "-M", "-s", "/usr/sbin/nologin", "-N", SAMBA_USER], timeout=10)
    try:
        ent = pwd.getpwnam(SAMBA_USER)
        return ent.pw_uid, ent.pw_gid
    except KeyError:
        return 0, 0


def _samba_account_exists():
    try:
        r = subprocess.run(["pdbedit", "-L", "-u", SAMBA_USER], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def _create_samba_user(force_new_password=False):
    """Ensure a dedicated local + Samba user exists; return its password."""
    _ensure_samba_uid_gid()
    cred = {}
    if os.path.exists(SAMBA_CRED_FILE):
        try:
            with open(SAMBA_CRED_FILE) as f:
                cred = json.load(f)
        except Exception:
            pass
    password = None if force_new_password else cred.get("password")
    if not password:
        password = secrets.token_urlsafe(9)
        cred = {"username": SAMBA_USER, "password": password, "synced": False}

    # Only re-run smbpasswd when we haven't confirmed it actually took — a
    # transient failure here must not leave the credential file showing a
    # password Samba never accepted (which is exactly what happened before:
    # the smbpasswd call's result was discarded, so a failure was silent).
    if not cred.get("synced"):
        try:
            # `-a` (add) fails on some Samba versions if the account already
            # exists — use it only for the very first creation, otherwise
            # just reset the existing account's password.
            args = ["smbpasswd", "-s"] + ([] if _samba_account_exists() else ["-a"]) + [SAMBA_USER]
            r = subprocess.run(
                args, input=f"{password}\n{password}\n", text=True,
                capture_output=True, timeout=10,
            )
            # Don't trust the exit code alone — confirm the account is
            # actually present in the passdb afterwards.
            cred["synced"] = r.returncode == 0 and _samba_account_exists()
            if not cred["synced"]:
                print(f"[sources] smbpasswd did not take effect for {SAMBA_USER} "
                      f"(rc={r.returncode}): {(r.stderr or r.stdout).strip()}")
        except Exception as e:
            cred["synced"] = False
            print(f"[sources] smbpasswd error for {SAMBA_USER}: {e}")

    os.makedirs(os.path.dirname(SAMBA_CRED_FILE), exist_ok=True)
    tmp = SAMBA_CRED_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cred, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, SAMBA_CRED_FILE)
    return password


def regen_samba_shares():
    """Rewrite the included shares file and start/stop smbd accordingly."""
    disks = _adopted_disk_sources()
    lines = []
    for src in disks:
        share = src.get("share") or "Musica"
        mp = src.get("mountpoint")
        if not mp:
            continue
        lines.append(f"\n[{share}]")
        lines.append(f"   path = {mp}")
        lines.append("   read only = no")
        lines.append("   browseable = yes")
        lines.append(f"   valid users = {SAMBA_USER}")
        lines.append(f"   force user = {SAMBA_USER}")
        lines.append("   create mask = 0664")
        lines.append("   directory mask = 0775")

    os.makedirs(os.path.dirname(SAMBA_SHARES_FILE), exist_ok=True)
    tmp = SAMBA_SHARES_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, SAMBA_SHARES_FILE)

    smbd = _run(["which", "smbd"], timeout=5).returncode == 0
    if not disks:
        if smbd:
            _run(["systemctl", "disable", "--now", "smbd"], timeout=30)
        return
    if smbd:
        _create_samba_user()
        _run(["systemctl", "enable", "--now", "smbd"], timeout=30)
        _run(["systemctl", "reload", "smbd"], timeout=10)


def _ip_addresses():
    addrs = []
    try:
        r = _run(["hostname", "-I"], timeout=5)
        if r.returncode == 0:
            addrs = r.stdout.strip().split()
    except Exception:
        pass
    return addrs


def _mount_adopted_disk(src, root):
    """Mount one adopted (internal or USB) source by stable PARTUUID — or, for
    a "superfloppy" USB stick with no partition table (common on cheap USB
    flash drives), by filesystem UUID instead. Always read-write. Returns
    (ok, message)."""
    partuuid = src.get("partuuid")
    fsuuid = src.get("fsuuid")
    fstype = (src.get("fstype") or "").lower()
    mountpoint = src.get("mountpoint")
    if (not partuuid and not fsuuid) or not mountpoint:
        return False, "partuuid/uuid o mountpoint mancante"
    root = os.path.realpath(root)
    p = os.path.realpath(mountpoint)
    if p != root and not p.startswith(root + os.sep):
        return False, "mountpoint non valido"
    os.makedirs(mountpoint, exist_ok=True)
    if os.path.ismount(mountpoint):
        return True, "già montato"

    if fstype == "ext4":
        opts = "rw,noatime,nosuid,nodev"
    elif fstype in _FAT_LIKE:
        # These filesystems (exFAT/vFAT/NTFS via the in-kernel ntfs3 driver)
        # require numeric ids, not a username, and carry no POSIX perms.
        uid, gid = _ensure_samba_uid_gid()
        opts = f"rw,noatime,nosuid,nodev,uid={uid},gid={gid},fmask=0113,dmask=0002,iocharset=utf8"
    else:
        opts = "rw,noatime,nosuid,nodev"

    spec = f"PARTUUID={partuuid}" if partuuid else f"UUID={fsuuid}"
    r = _run(["mount", "-t", _fs_mount_type(fstype), "-o", opts, spec, mountpoint], timeout=30)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "mount fallito").strip()

    if fstype == "ext4":
        # mkfs.ext4 leaves the root dir owned by root:root, which the Samba
        # forced user (hifimusic) cannot write into. exFAT/vfat/ntfs get this
        # via the uid/gid mount options above instead.
        try:
            uid, gid = _ensure_samba_uid_gid()
            os.chown(mountpoint, uid, gid)
            os.chmod(mountpoint, 0o2775)
        except Exception:
            pass
    return True, "montato"


def mount_internal(src):
    return _mount_adopted_disk(src, INTERNAL_MOUNT_ROOT)


def mount_usb_adopted(src):
    return _mount_adopted_disk(src, USB_ADOPTED_ROOT)


def remount_all():
    state = load_state()
    for src in state.get("sources", []):
        t = src.get("type")
        try:
            if t == "smb":
                mount_smb(src)
            elif t == "internal":
                mount_internal(src)
            elif t == "usb":
                mount_usb_adopted(src)
        except Exception as e:
            print(f"[sources] remount failed for {src.get('name')}: {e}")
    regen_samba_shares()


def _all_smb_mounted():
    """True if every configured SMB source is currently mounted (or none exist)."""
    for src in load_state().get("sources", []):
        if src.get("type") == "smb":
            try:
                if not os.path.ismount(os.path.realpath(src["mountpoint"])):
                    return False
            except Exception:
                return False
    return True


def remount_all_retry(attempts=60, delay=5):
    """Mount SMB shares, retrying in the background until they all mount.

    Boot no longer waits for the network (NetworkManager-wait-online is masked
    for speed), so at startup the LAN / NAS may not be reachable yet and a
    one-shot mount fails with -101 (ENETUNREACH). Keep retrying so the shares
    come up on their own once the network is available — without ever delaying
    boot or the UI (this runs in a daemon thread).
    """
    for i in range(attempts):
        try:
            remount_all()
        except Exception as e:
            print(f"[sources] remount attempt {i + 1} error: {e}")
        if _all_smb_mounted():
            if i:
                print(f"[sources] SMB shares mounted after {i + 1} attempt(s)")
            return
        time.sleep(delay)
    print("[sources] gave up mounting SMB shares (network/server unreachable)")


# ─────────────────────────── USB drives ─────────────────────────────
# USB sticks / external drives are auto-mounted read-only under USB_MOUNT_ROOT
# (inside the allowed /media root) so they show up in the Sources UI and the
# user can add folders from them as local sources. We poll lsblk rather than
# wiring udev, so the whole feature stays in this one service.
USB_MOUNT_ROOT = "/media/hifi-usb"
_FAT_LIKE = ("vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "msdos")
# Latest snapshot from usb_sync(), refreshed by the background usb_monitor thread
# every few seconds. /api/usb serves this instead of running the full lsblk +
# mount scan on every poll (the web UI polls /api/usb every 4s and the monitor
# already scans that often). None = no scan has completed yet.
_usb_state = None


def _fs_mount_type(fstype):
    """Explicit `mount -t` type for a given fstype — shared by the ephemeral
    read-only USB browse mount and the adopted (internal/USB) read-write
    mount, so both get the same kernel-driver mapping rather than relying on
    autodetection."""
    if fstype == "ntfs":
        return "ntfs3"                       # in-kernel NTFS (no ntfs-3g needed)
    if fstype in ("vfat", "exfat", "ntfs3", "msdos"):
        return fstype
    return "auto"


def _usb_mount_opts(fstype):
    base = "ro,noatime,nosuid,nodev,noexec"
    if fstype in _FAT_LIKE:
        # These carry no UNIX perms — map everything readable for Lyrion.
        return base + ",uid=0,gid=0,iocharset=utf8,umask=022"
    return base


def _adopted_usb_ids():
    """(partuuid, fsuuid) lowercased sets of already-adopted "usb" sources —
    used to keep the ephemeral browse mount from fighting over a disk that's
    now mounted read-write under USB_ADOPTED_ROOT."""
    partuuids, fsuuids = set(), set()
    for s in load_state().get("sources", []):
        if s.get("type") == "usb":
            if s.get("partuuid"):
                partuuids.add(s["partuuid"].lower())
            if s.get("fsuuid"):
                fsuuids.add(s["fsuuid"].lower())
    return partuuids, fsuuids


def _usb_partitions():
    """USB block devices carrying a filesystem, excluding already-adopted ones
    → [{path,name,fstype,label,size,uuid,partuuid}]. Handles partitioned
    (sdX1) and whole-disk filesystems; skips optical drives (type 'rom') and
    any non-USB transport (internal SATA/eMMC)."""
    try:
        r = _run(["lsblk", "-J", "-o", "PATH,NAME,TYPE,FSTYPE,LABEL,SIZE,TRAN,UUID,PARTUUID"], timeout=10)
        data = json.loads(r.stdout or "{}")
    except Exception:
        return []
    adopted_partuuids, adopted_fsuuids = _adopted_usb_ids()
    out = []
    for dev in data.get("blockdevices", []):
        if dev.get("tran") != "usb" or dev.get("type") != "disk":
            continue
        kids = dev.get("children") or []
        if kids:
            out.extend(p for p in kids if p.get("type") == "part" and p.get("fstype"))
        elif dev.get("fstype"):
            out.append(dev)
    return [
        p for p in out
        if (p.get("partuuid") or "").lower() not in adopted_partuuids
        and (p.get("uuid") or "").lower() not in adopted_fsuuids
    ]


def _usb_mountpoint(part):
    return os.path.join(USB_MOUNT_ROOT, _slug(part.get("label") or part.get("name")))


def usb_sync():
    """Mount newly-appeared USB filesystems (read-only) and unmount ones whose
    device has gone. Returns {mountpoint: part} for the currently live disks.
    Also publishes the result to _usb_state for /api/usb to read cheaply."""
    global _usb_state
    with _lock:
        os.makedirs(USB_MOUNT_ROOT, exist_ok=True)
        wanted = {}
        for p in _usb_partitions():
            mp = _usb_mountpoint(p)
            wanted[mp] = p
            if not os.path.ismount(mp):
                try:
                    os.makedirs(mp, exist_ok=True)
                    fs = (p.get("fstype") or "").lower()
                    _run(["mount", "-t", _fs_mount_type(fs), "-o", _usb_mount_opts(fs),
                          p["path"], mp], timeout=20)
                except Exception as e:
                    print(f"[sources] usb mount failed for {p.get('path')}: {e}")
        # Reap mountpoints we created that are no longer present (drive removed).
        try:
            for name in os.listdir(USB_MOUNT_ROOT):
                mp = os.path.join(USB_MOUNT_ROOT, name)
                if mp in wanted:
                    continue
                if os.path.ismount(mp):
                    _run(["umount", "-l", mp], timeout=10)
                try:
                    os.rmdir(mp)
                except OSError:
                    pass
        except FileNotFoundError:
            pass
        _usb_state = dict(wanted)
        return wanted


def usb_monitor(interval=4):
    while True:
        try:
            usb_sync()
        except Exception as e:
            print(f"[sources] usb monitor error: {e}")
        time.sleep(interval)


# ─────────────────────────── Lyrion mediadirs ───────────────────────
def _prefs_dir_from_service():
    """Read the real PREFSDIR from the lyrionmusicserver systemd unit."""
    try:
        r = _run(["systemctl", "show", LYRION_SERVICE, "-p", "Environment"])
        m = re.search(r"PREFSDIR=(\S+)", r.stdout)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None

def _find_prefs():
    candidates = []
    pd = _prefs_dir_from_service()
    if pd:
        candidates.append(os.path.join(pd, "server.prefs"))
    candidates += [
        "/var/lib/squeezeboxserver/prefs/server.prefs",
        "/var/lib/lyrionmusicserver/prefs/server.prefs",
    ]
    for pat in PREFS_GLOBS:
        candidates += glob.glob(pat)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None

def _ensure_prefs():
    """Find server.prefs; if missing (fresh install), start Lyrion and wait
    for it to create the file on first run."""
    prefs = _find_prefs()
    if prefs:
        return prefs
    _run(["systemctl", "start", LYRION_SERVICE], timeout=30)
    for _ in range(20):  # up to ~40s
        time.sleep(2)
        prefs = _find_prefs()
        if prefs:
            return prefs
    return None


def _squeezebox_ids():
    """(uid, gid) of the squeezeboxserver user, or (None, None)."""
    try:
        import pwd
        ent = pwd.getpwnam("squeezeboxserver")
        return ent.pw_uid, ent.pw_gid
    except Exception:
        return None, None


def _provision_playlistdir(data):
    """Given the loaded prefs dict, make sure `playlistdir` points at an
    existing, writable folder (creating/chowning it). Returns the (possibly
    updated) dict and a bool telling whether anything changed."""
    cur = (data.get("playlistdir") or "").strip()
    if cur and os.path.isdir(cur) and os.access(cur, os.W_OK):
        return data, False
    target = cur or DEFAULT_PLAYLISTDIR
    uid, gid = _squeezebox_ids()
    try:
        os.makedirs(target, exist_ok=True)
        if uid is not None:
            os.chown(target, uid, gid)
    except Exception as e:
        print(f"[sources] playlistdir mkdir failed: {e}")
        return data, False
    data["playlistdir"] = target
    return data, True


def ensure_playlistdir():
    """Standalone provisioning used at service start (covers devices that were
    set up before this feature and never re-apply their sources). Idempotent:
    only stops/edits/starts Lyrion when the folder is missing/unset."""
    try:
        import yaml
    except Exception:
        return
    prefs = _find_prefs()
    if not prefs:
        return
    try:
        with open(prefs) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return
    data, changed = _provision_playlistdir(data)
    if not changed:
        return
    _run(["systemctl", "stop", LYRION_SERVICE], timeout=60)
    try:
        tmp = prefs + ".tmp"
        with open(tmp, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, prefs)
        uid, gid = _squeezebox_ids()
        if uid is not None:
            try:
                os.chown(prefs, uid, gid)
            except Exception:
                pass
    except Exception as e:
        print(f"[sources] playlistdir prefs write failed: {e}")
    finally:
        _run(["systemctl", "start", LYRION_SERVICE], timeout=60)
    print(f"[sources] playlistdir set to {data.get('playlistdir')}")


def current_paths(state):
    """Media directories to hand to Lyrion. Re-validates every path against the
    same confinement each source type is supposed to already satisfy (MOUNT_ROOT
    for SMB mountpoints, INTERNAL_MOUNT_ROOT for internal disks,
    USB_ADOPTED_ROOT for adopted USB disks, ALLOWED_LOCAL_ROOTS for local
    paths) rather than trusting the stored state verbatim — state can come
    from a restored /etc/hifi-sources.json (see /api/restore), which is
    untrusted archive content that never goes through api_add_smb()/
    api_add_local()'s own validation. Without this, a crafted backup with
    e.g. {"type":"local", "path":"/"} would get handed straight to Lyrion as
    a media directory."""
    smb_root = os.path.realpath(MOUNT_ROOT)
    internal_root = os.path.realpath(INTERNAL_MOUNT_ROOT)
    usb_root = os.path.realpath(USB_ADOPTED_ROOT)
    paths = []
    for src in state.get("sources", []):
        t = src.get("type")
        if t == "smb":
            mp = src.get("mountpoint")
            if not mp:
                continue
            p = os.path.realpath(mp)
            if p != smb_root and not p.startswith(smb_root + os.sep):
                continue
        elif t == "internal":
            mp = src.get("mountpoint")
            if not mp:
                continue
            p = os.path.realpath(mp)
            if p != internal_root and not p.startswith(internal_root + os.sep):
                continue
        elif t == "usb":
            mp = src.get("mountpoint")
            if not mp:
                continue
            p = os.path.realpath(mp)
            if p != usb_root and not p.startswith(usb_root + os.sep):
                continue
        else:
            raw = src.get("path")
            p = _local_path_allowed(raw) if raw else None
        if p and p not in paths:
            paths.append(p)
    return paths


def _hlang():
    """Caller's UI language for hifi_i18n-backed messages (X-UI-Lang header,
    same convention as api_server.py/webui_server.py) — distinct from
    _req_lang()/_m() below, which serve the self-contained Sources web page via
    ?lang=/Accept-Language. Wrapped in try/except because apply_to_lyrion() (the
    only caller today) also runs from the format-watcher background thread,
    outside any request context."""
    try:
        v = request.headers.get('X-UI-Lang')
    except RuntimeError:
        return 'en'
    return v if v in ('en', 'it') else 'en'


def apply_to_lyrion(state):
    """Write mediadirs into Lyrion prefs and restart + rescan."""
    try:
        import yaml
    except Exception:
        return False, _ht('lyrion.yamlMissing', _hlang())

    prefs = _ensure_prefs()
    if not prefs:
        return False, _ht('lyrion.prefsNotFound', _hlang())

    paths = current_paths(state)

    # Warn if an adopted internal/USB source is not mounted: applying would
    # hand an empty mountpoint to Lyrion and clear the library. The user must
    # re-attach the disk or remove the source.
    unmounted_disks = []
    for src in state.get("sources", []):
        if src.get("type") in ("internal", "usb"):
            mp = src.get("mountpoint")
            if not mp or not os.path.ismount(mp):
                unmounted_disks.append(src.get("name") or "disco")
    if unmounted_disks:
        return False, _ht('lyrion.diskNotMounted', _hlang(), disks=", ".join(unmounted_disks))

    # Stop Lyrion so it does not overwrite the prefs file under us.
    _run(["systemctl", "stop", LYRION_SERVICE], timeout=60)
    try:
        with open(prefs) as f:
            data = yaml.safe_load(f) or {}
        data["mediadirs"] = paths
        # keep ignoreInAudioScan in sync (empty list is fine)
        data.setdefault("ignoreInAudioScan", [])
        # ensure a writable playlist folder so "save as playlist" works
        data, _ = _provision_playlistdir(data)
        tmp = prefs + ".tmp"
        with open(tmp, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, prefs)
        # prefs belong to the squeezeboxserver user
        try:
            import pwd
            uid = pwd.getpwnam("squeezeboxserver").pw_uid
            gid = pwd.getpwnam("squeezeboxserver").pw_gid
            os.chown(prefs, uid, gid)
        except Exception:
            pass
    finally:
        _run(["systemctl", "start", LYRION_SERVICE], timeout=60)

    return True, _ht('lyrion.applied', _hlang(), count=len(paths))


# ─────────────────────────── Backup / restore ────────────────────────
# HTTP layer only. What may be archived and what may be written back both come
# from hifi_backup.py — one table, so the two directions can never drift apart.
# See that module for the reasoning behind the category split, the deny-list,
# and why this is a profile backup rather than a rootfs image.
#
# Building an archive is delegated to /usr/local/sbin/hifi-backup-run.py via
# systemd-run (same detached-worker + /run status-file shape as the disk format
# and CD rip jobs), because it walks the whole Lyrion prefs tree and can take
# long enough to hold an HTTP worker hostage. Restoring used to stay
# synchronous on the theory that it only ever touches "a handful of small
# files plus, at worst, a Lyrion stop/start" — wrong in practice: a full
# profile restore writes back the same thousands-of-tiny-files Lyrion prefs/
# playlists tree a backup reads, takes its OWN pre-restore safety snapshot
# inline first (another full archive build), and can restart squeezelite,
# CamillaDSP, NetworkManager, Samba and hifi-webui along the way. Held in an
# HTTP request, that ran long enough to look hung, with zero feedback on which
# of those steps it was actually doing — and if the restored file was
# webui.db, the last of those restarts kills hifi-webui itself, i.e. the very
# process proxying the request for the web-admin UI, abruptly dropping the
# connection the browser was waiting on. So restore now runs in a background
# thread (in-process — unlike backup it never needs to survive sources_server
# itself restarting, so systemd-run isn't needed) reporting progress to
# RESTORE_STATUS_FILE exactly like the backup job does, polled the same way.
#
# The archive itself is still an allow-list on BOTH sides — a restore never
# uses the tar member's own path verbatim, only regular files are ever opened,
# and every member is checked against the manifest's sha256 before it is
# written. A malicious or corrupt archive therefore has nowhere to aim.
# Distinct from the "hifi-backup" name used by the scheduled hifi-backup.service
# (see 0033-backup-scheduler.sh): systemd-run refuses to create a transient unit
# that shares a name with one that already has a fragment file on disk — that
# collision made every manual backup fail with "already loaded or has a
# fragment file", unconditionally, the moment the scheduler shipped.
BACKUP_UNIT = "hifi-backup-manual"
BACKUP_JOB = "/run/hifi-backup-job.json"
BACKUP_SCRIPT = "/usr/local/sbin/hifi-backup-run.py"
# 32MB per file is generous for config, a FIR filter or the web-admin database.
MAX_RESTORE_MEMBER_SIZE = 32 * 1024 * 1024
# Lyrion keeps one .prefs file per plugin and per player, and /var/lib/bluetooth
# one directory per pairing, so a full profile is thousands of tiny files — not
# the handful the config-only backup this replaces used to hold.
MAX_RESTORE_MEMBERS = 20000
# Compressed-upload ceiling, checked BEFORE tarfile ever walks the archive.
# Deliberately far tighter than MAX_RESTORE_MEMBERS * MAX_RESTORE_MEMBER_SIZE:
# a real backup is small (the Lyrion library cache, the only genuinely large
# thing on the box, is excluded by the manifest). Bounds how much a maliciously
# well-compressed small upload can force us to decompress while enumerating
# members, since that has to happen before any per-member size check can run.
MAX_RESTORE_ARCHIVE_SIZE = 64 * 1024 * 1024

# Same shape as hb.STATUS_FILE, own file: a restore and a backup can never run
# at once (the restore path calls _snapshot_before_restore inline, and the
# scheduled/manual backup guard would otherwise fight it), but keeping them
# separate means each polling loop only ever sees its own job's progress.
RESTORE_STATUS_FILE = "/run/hifi-restore-status.json"
_RESTORE_LOCK = threading.Lock()


def _restore_status():
    try:
        with open(RESTORE_STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"state": "idle"}


def _write_restore_status(state, progress, message, **extra):
    payload = {"state": state, "progress": progress, "message": message}
    payload.update(extra)
    tmp = RESTORE_STATUS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, RESTORE_STATUS_FILE)
    except OSError as e:
        print(f"[sources] impossibile scrivere lo stato restore: {e}")


def _backup_status():
    try:
        with open(hb.STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"state": "idle"}


def _passphrase_ok(value):
    """A passphrase is handed to openssl through stdin, never a shell, so the
    only real constraints are that it is printable and bounded."""
    if not value:
        return True
    return len(value) <= 256 and "\n" not in value and "\r" not in value


# ── restore ──────────────────────────────────────────────────────────
def _restore_members(tar, manifest, categories, progress_cb=None):
    """Write back every member that the selected categories allow.

    Returns (restored_paths, errors). Integrity is checked per member against
    the manifest before anything touches the filesystem — the failure mode a
    checksum-free backup tool has (a silently corrupted file restored over a
    good one) is the whole reason this is here.

    progress_cb, if given, is called as progress_cb(done, total) every 50
    members — a Lyrion profile is thousands of tiny files, so without this a
    restore's status just sits on "Ripristino file..." for however long that
    takes, indistinguishable from actually being stuck.
    """
    restored, errors = [], []
    digests = (manifest or {}).get("members") or {}
    members = tar.getmembers()
    if len(members) > MAX_RESTORE_MEMBERS:
        return [], ["Archivio non valido (troppi file)"]
    total = len(members)

    current_sources = None
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "rb") as f:
                current_sources = f.read()
        except OSError:
            pass

    for i, member in enumerate(members):
        if progress_cb and i % 50 == 0:
            progress_cb(i, total)
        if not member.isfile():
            continue  # dirs, symlinks, devices: never followed, never created
        if member.size > MAX_RESTORE_MEMBER_SIZE:
            errors.append(f"{member.name}: troppo grande, saltato")
            continue
        dest = hb.restore_dest_for_member(member.name, categories)
        if not dest:
            continue  # outside the allow-list, or a category not selected
        try:
            src = tar.extractfile(member)
            if src is None:
                continue
            data = src.read()

            expected = digests.get(member.name)
            if expected and hashlib.sha256(data).hexdigest() != expected:
                errors.append(f"{os.path.basename(dest)}: checksum non valido")
                continue

            if dest == STATE_FILE and current_sources:
                # An unencrypted backup has its SMB passwords blanked; keep the
                # ones this device already knows so the shares still mount.
                data = hb.merge_sources_state(data, current_sources)

            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tmp = dest + ".restore.tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o600)
            os.replace(tmp, dest)
            restored.append(dest)
        except Exception as e:
            print(f"[sources] restore failed for {dest}: {e}")
            errors.append(f"{os.path.basename(dest)}: ripristino fallito")
    if progress_cb:
        progress_cb(total, total)
    return restored, errors


def _lyrion_paths_touched(restored):
    return [p for p in restored if "/prefs/" in p or "/playlists/" in p]


def _stop_lyrion():
    """Lyrion caches its prefs in memory and rewrites them on exit, so writing
    prefs underneath a running server would simply be overwritten. Unlike the
    backup path — which never stops anything — a restore is an explicit, rare
    action where a short pause is the right trade."""
    _run(["systemctl", "stop", "lyrionmusicserver"], timeout=60)


def _start_lyrion():
    _run(["systemctl", "start", "lyrionmusicserver"], timeout=60)


def _chown_lyrion(paths):
    uid, gid = _squeezebox_ids()
    if uid is None:
        return
    for path in paths:
        try:
            os.chown(path, uid, gid)
            os.chmod(path, 0o640)
        except OSError:
            pass


def _restore_apply_side_effects(restored):
    """Re-apply the config that was just restored (best-effort, non-fatal)."""
    notes = []
    if STATE_FILE in restored:
        try:
            remount_all()
            ok, msg = apply_to_lyrion(load_state())
            notes.append(msg if ok else f"Sorgenti: {msg}")
        except Exception as e:
            print(f"[sources] restore side-effect (sources) failed: {e}")
            notes.append("Sorgenti non riapplicate")
    if any(p in restored for p in ("/etc/default/squeezelite", "/var/lib/hifi-player/dsp-target")):
        _run(["systemctl", "restart", "squeezelite"], timeout=30)
        notes.append("squeezelite riavviato")
    if any(p in restored for p in ("/etc/camilladsp/config.yml", "/etc/hifi-player/dsp.json")) \
            or any(p.startswith("/etc/camilladsp/filters/") for p in restored):
        # Only restart CamillaDSP if it was already running — restoring a
        # backup must never turn DSP on by itself.
        try:
            active = _run(["systemctl", "is-active", "camilladsp.service"], timeout=10)
            if (active.stdout or "").strip() == "active":
                _run(["systemctl", "restart", "camilladsp.service"], timeout=30)
                notes.append("CamillaDSP riavviato")
        except Exception:
            pass
    if any(p.startswith("/etc/NetworkManager/system-connections/") for p in restored):
        # The profiles are on disk but NetworkManager only reads them on
        # demand; reload so the restored Wi-Fi networks are actually known.
        for path in restored:
            if path.startswith("/etc/NetworkManager/system-connections/"):
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
        _run(["nmcli", "connection", "reload"], timeout=30)
        notes.append("Reti Wi-Fi ricaricate")
    if "/etc/hifi-player/webui.db" in restored:
        # The admin account changed underneath the running daemon; restart so
        # it reopens the database, and expect the operator to log in again.
        _run(["systemctl", "restart", "hifi-webui"], timeout=30)
        notes.append("Web admin riavviato (nuovo login necessario)")
    if SAMBA_CRED_FILE in restored:
        # The restored file's `synced` flag describes whichever machine's
        # Samba passdb it was written on, not this one's — _create_samba_user
        # would trust a stale "true" and skip pushing the password into
        # smbpasswd, leaving smbd still authenticating with its OWN old
        # password while the UI shows the one that was just restored. Force
        # the resync so the restored password is what smbd actually accepts.
        try:
            with open(SAMBA_CRED_FILE) as f:
                cred = json.load(f)
            cred["synced"] = False
            tmp = SAMBA_CRED_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(cred, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, SAMBA_CRED_FILE)
        except Exception as e:
            print(f"[sources] samba-cred resync flag reset failed: {e}")
        _create_samba_user()
        _run(["systemctl", "try-restart", "smbd"], timeout=30)
        notes.append("Credenziali SMB risincronizzate")
    return notes


def _restore_from_path(path, passphrase, requested_categories, report=None):
    """Open a backup file (either shape), apply it, return (payload, status).

    report, if given, is called as report(state, progress, message) at each
    stage — see RESTORE_STATUS_FILE / _write_restore_status. Defaults to a
    no-op so this stays callable on its own (e.g. from a test) without a
    status file in play.
    """
    if report is None:
        report = lambda *a, **kw: None  # noqa: E731
    workdir = tempfile.mkdtemp(prefix="hifi-restore-", dir="/run")
    os.chmod(workdir, 0o700)
    tar = None
    try:
        report("opening", 20, "Apertura archivio…")
        try:
            tar, manifest = hb.open_backup(path, workdir, passphrase)
        except hb.BackupError as e:
            return {"success": False, "message": str(e)}, 400

        # A backup written by a newer build may use members or semantics this
        # code does not understand; refuse rather than half-apply it.
        if manifest and int(manifest.get("schema") or 1) > hb.SCHEMA:
            return {"success": False,
                    "message": "Backup creato da una versione più recente: "
                               "aggiorna il dispositivo prima di ripristinarlo"}, 409

        available = hb.categories_in_manifest(manifest)
        wanted = set(requested_categories or available)
        categories = [c for c in available if c in wanted]
        if not categories:
            return {"success": False,
                    "message": "Nessuna categoria da ripristinare"}, 400

        lyrion_stopped = False
        if "lyrion" in categories:
            report("stopping_lyrion", 25, "Arresto di Lyrion…")
            _stop_lyrion()
            lyrion_stopped = True
        try:
            def _member_progress(done, total):
                pct = 30 + int(done / total * 45) if total else 30
                report("restoring", pct, f"Ripristino file… ({done}/{total})")
            restored, errors = _restore_members(tar, manifest, categories, _member_progress)
        finally:
            if lyrion_stopped:
                report("starting_lyrion", 80, "Riavvio di Lyrion…")
                _chown_lyrion(_lyrion_paths_touched(restored if restored else []))
                _start_lyrion()

        if not restored and errors:
            return {"success": False, "message": "; ".join(errors)}, 400

        report("applying", 90, "Applicazione modifiche (rete, DSP, servizi)…")
        notes = _restore_apply_side_effects(restored)
        if lyrion_stopped:
            # Restoring prefs/playlists makes Lyrion treat them as changed on
            # its own next start, so it runs its own library rescan — nothing
            # this code drives or can see the end of, and the LMS web UI's
            # "please wait" banner during that looks a lot like something
            # stuck. Say so up front instead of leaving the user to wonder.
            notes.append("Lyrion sta terminando la scansione della libreria in background.")
        msg = f"{len(restored)} file ripristinati."
        if notes:
            msg += " " + " ".join(notes)
        if errors:
            msg += " Avvisi: " + "; ".join(errors)
        hb.record_history(hb.STORE_DIR,
                          f"restore\tcompleted\t{len(restored)} file\t"
                          f"{','.join(categories)}")
        return {"success": True, "message": msg, "restored": len(restored),
                "categories": categories}, 200
    finally:
        if tar is not None:
            try:
                tar.close()
            except Exception:
                pass
        shutil.rmtree(workdir, ignore_errors=True)


def _snapshot_before_restore():
    """Take a restore point first.

    Restoring is the one operation here that overwrites live configuration, and
    it is exactly when the user is least able to reconstruct what they had. The
    snapshot is built inline (not via the worker) so it is guaranteed to be on
    disk before the first file is overwritten — an async job could still be
    running when the restore starts.
    """
    try:
        os.makedirs(hb.STORE_DIR, exist_ok=True)
        os.chmod(hb.STORE_DIR, 0o700)
        hb.prune_incomplete(hb.STORE_DIR)
        gen_id = hb.new_gen_id()
        gen_dir = os.path.join(hb.STORE_DIR, gen_id)
        os.makedirs(gen_dir, exist_ok=True)
        os.chmod(gen_dir, 0o700)
        cats = list(hb.UNATTENDED_CATEGORIES)
        manifest = hb.build_archive(os.path.join(gen_dir, hb.ARCHIVE_NAME),
                                    cats, "/", encrypted=False,
                                    extra={"created": gen_id,
                                           "trigger": "pre-restore",
                                           "versions": hb.device_versions()})
        tmp = os.path.join(gen_dir, hb.MANIFEST_NAME + ".tmp")
        with open(tmp, "w") as f:
            json.dump(manifest, f, indent=2)
        os.replace(tmp, os.path.join(gen_dir, hb.MANIFEST_NAME))
        hb.rotate(hb.STORE_DIR, hb.read_settings()["keep"])
        hb.record_history(hb.STORE_DIR, f"backup\tcompleted\t{gen_id}\tpre-restore")
        return gen_id
    except Exception as e:
        print(f"[sources] pre-restore snapshot failed: {e}")
        return None


def _run_restore_async(path, passphrase, categories, workdir_to_clean=None):
    """Background-thread body for a restore job. Runs in-process (unlike the
    backup job, restore never needs to survive sources_server itself dying —
    nothing it does restarts this process — so a plain daemon thread is enough,
    no systemd-run/status-file-on-tmpfs-for-a-separate-process needed beyond the
    status file itself, which exists purely so polling requests don't have to
    share state with this thread directly)."""
    try:
        _write_restore_status("preparing", 5, "Preparazione…")
        _write_restore_status("snapshotting", 10, "Backup di sicurezza pre-ripristino…")
        _snapshot_before_restore()

        def report(state, progress, message):
            _write_restore_status(state, progress, message)

        payload, status = _restore_from_path(path, passphrase, categories, report)
        if status == 200 and payload.get("success"):
            _write_restore_status("done", 100, payload.get("message", "Ripristino completato."),
                                  restored=payload.get("restored"), categories=payload.get("categories"))
        else:
            _write_restore_status("error", 0, payload.get("message", "Ripristino fallito"))
    except Exception as e:
        print(f"[sources] restore job failed: {e}")
        _write_restore_status("error", 0, f"Ripristino fallito: {e}")
    finally:
        if workdir_to_clean:
            shutil.rmtree(workdir_to_clean, ignore_errors=True)
        _RESTORE_LOCK.release()


def _start_restore(path, passphrase, categories, workdir_to_clean=None):
    """Start a restore job in the background. Returns None on success, or a
    (payload, status) error pair if one is already running."""
    if not _RESTORE_LOCK.acquire(blocking=False):
        return {"success": False, "code": "restore.alreadyInProgress",
                "message": _ht('restore.alreadyInProgress', _hlang())}, 409
    _write_restore_status("preparing", 0, "Avvio…")
    threading.Thread(target=_run_restore_async,
                     args=(path, passphrase, categories, workdir_to_clean),
                     daemon=True, name="restore-worker").start()
    return None


# ── routes ───────────────────────────────────────────────────────────
@app.route("/api/backup", methods=["GET"])
def api_backup():
    """Build and stream a backup immediately.

    Kept as-is (same URL, same behaviour) because it is what the plain download
    link in the UI points at, and an <a href> cannot send a passphrase — so this
    one is always the non-secret half of the profile. Encrypted backups go
    through /api/backup/create.
    """
    denied = _require_pair_token()
    if denied:
        return denied
    workdir = tempfile.mkdtemp(prefix="hifi-backup-dl-", dir="/run")
    try:
        path = os.path.join(workdir, hb.ARCHIVE_NAME)
        stamp = hb.new_gen_id()
        hb.build_archive(path, list(hb.UNATTENDED_CATEGORIES), "/",
                         encrypted=False,
                         extra={"created": stamp, "trigger": "download",
                                "versions": hb.device_versions()})
        with open(path, "rb") as f:
            data = f.read()
    except Exception as e:
        print(f"[sources] backup build failed: {e}")
        return jsonify({"success": False, "message": "Creazione backup fallita"}), 500
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    resp = Response(data, mimetype="application/gzip")
    resp.headers["Content-Disposition"] = f'attachment; filename="osmium-backup-{stamp}.tar.gz"'
    return resp


@app.route("/api/backup/create", methods=["POST"])
def api_backup_create():
    """Start a stored-generation build (async, so a big Lyrion prefs tree
    doesn't hold an HTTP worker)."""
    denied = _require_pair_token()
    if denied:
        return denied
    if not os.path.exists(BACKUP_SCRIPT):
        return jsonify({"success": False, "code": "backup.systemUpdateRequired",
                        "message": _ht('backup.systemUpdateRequired', _hlang())}), 424
    if _backup_status().get("state") in ("preparing", "checking", "archiving",
                                         "encrypting", "finishing"):
        return jsonify({"success": False, "code": "backup.alreadyInProgress",
                        "message": _ht('backup.alreadyInProgress', _hlang())}), 409
    if _restore_status().get("state") not in ("idle", "done", "error", None):
        # A restore takes its own pre-restore snapshot via the same STORE_DIR
        # (hb.build_archive/rotate) a manual backup would touch — let it finish
        # rather than racing two writers over the same generations directory.
        return jsonify({"success": False, "code": "backup.alreadyInProgress",
                        "message": _ht('backup.alreadyInProgress', _hlang())}), 409

    data = request.get_json(silent=True) or {}
    passphrase = data.get("passphrase") or ""
    if not _passphrase_ok(passphrase):
        return jsonify({"success": False, "message": "Passphrase non valida"}), 400
    categories = hb.selected_categories(data.get("categories"), bool(passphrase))
    if not categories:
        return jsonify({"success": False,
                        "message": "Nessuna categoria selezionata"}), 400

    job = {"categories": categories, "passphrase": passphrase,
           "trigger": "manual", "keep": hb.read_settings()["keep"]}
    # /run is tmpfs and this may carry the passphrase: write it 0600, and the
    # worker deletes it the moment it has been read.
    fd = os.open(BACKUP_JOB, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(job, f)
    with open(hb.STATUS_FILE, "w") as f:
        json.dump({"state": "preparing", "progress": 0, "message": "Avvio…"}, f)
    try:
        r = _run(["systemd-run", "--no-block", "--collect", "--unit=" + BACKUP_UNIT,
                  BACKUP_SCRIPT, BACKUP_JOB], timeout=15)
        launch_err = None if r.returncode == 0 else (r.stderr or r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        launch_err = "systemd-run non ha risposto"
    if launch_err:
        # Without this, a systemd-run failure (unit già attivo, dbus, ecc.)
        # leaves the "Avvio…"/0% placeholder above in place forever, since
        # nothing ever starts to overwrite it — the UI just polls a frozen
        # status and looks hung.
        with open(hb.STATUS_FILE, "w") as f:
            json.dump({"state": "error", "progress": 0,
                       "message": f"Avvio del backup fallito: {launch_err}"[:300]}, f)
        try:
            os.unlink(BACKUP_JOB)
        except OSError:
            pass
        return jsonify({"success": False, "message": "Avvio del backup fallito"}), 500
    return jsonify({"success": True, "categories": categories,
                    "encrypted": bool(passphrase)}), 202


@app.route("/api/backup/status", methods=["GET"])
def api_backup_status():
    denied = _require_pair_token()
    if denied:
        return denied
    return jsonify(_backup_status())


@app.route("/api/backup/list", methods=["GET"])
def api_backup_list():
    denied = _require_pair_token()
    if denied:
        return denied
    hb.prune_incomplete(hb.STORE_DIR)
    return jsonify({"generations": hb.list_generations(hb.STORE_DIR),
                    "categories": list(hb.ALL_CATEGORIES),
                    "secret": list(hb.SECRET_CATEGORIES),
                    "settings": hb.read_settings(),
                    "scheduled_categories": list(hb.UNATTENDED_CATEGORIES)})


@app.route("/api/backup/<gen_id>", methods=["GET"])
def api_backup_download(gen_id):
    """Download a stored generation as one self-contained file."""
    denied = _require_pair_token()
    if denied:
        return denied
    if not hb.valid_gen_id(gen_id):
        return jsonify({"success": False, "message": "Backup non trovato"}), 404
    manifest = hb.read_manifest(hb.STORE_DIR, gen_id)
    if not manifest:
        return jsonify({"success": False, "message": "Backup non trovato"}), 404

    src = hb.archive_path(hb.STORE_DIR, gen_id, manifest)
    workdir = None
    try:
        if manifest.get("enc"):
            # Wrap manifest + ciphertext so the download can be restored
            # anywhere, not just from the directory it was produced in.
            workdir = tempfile.mkdtemp(prefix="hifi-backup-dl-", dir="/run")
            wrapper = os.path.join(workdir, "wrapper.tar.gz")
            hb.wrap_encrypted(wrapper, manifest, src)
            src = wrapper
        with open(src, "rb") as f:
            data = f.read()
    except OSError:
        return jsonify({"success": False, "message": "Backup non leggibile"}), 500
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    resp = Response(data, mimetype="application/gzip")
    resp.headers["Content-Disposition"] = f'attachment; filename="osmium-backup-{gen_id}.tar.gz"'
    return resp


@app.route("/api/backup/<gen_id>", methods=["DELETE"])
def api_backup_delete(gen_id):
    denied = _require_pair_token()
    if denied:
        return denied
    if not hb.valid_gen_id(gen_id):
        return jsonify({"success": False, "message": "Backup non trovato"}), 404
    path = os.path.join(hb.STORE_DIR, gen_id)
    if not os.path.isdir(path):
        return jsonify({"success": False, "message": "Backup non trovato"}), 404
    shutil.rmtree(path, ignore_errors=True)
    hb.record_history(hb.STORE_DIR, f"delete\t{gen_id}")
    return jsonify({"success": True, "message": "Backup eliminato"})


@app.route("/api/backup/<gen_id>/restore", methods=["POST"])
def api_backup_restore(gen_id):
    denied = _require_pair_token()
    if denied:
        return denied
    if not hb.valid_gen_id(gen_id):
        return jsonify({"success": False, "message": "Backup non trovato"}), 404
    manifest = hb.read_manifest(hb.STORE_DIR, gen_id)
    if not manifest:
        return jsonify({"success": False, "message": "Backup non trovato"}), 404
    data = request.get_json(silent=True) or {}
    passphrase = data.get("passphrase") or ""
    if not _passphrase_ok(passphrase):
        return jsonify({"success": False, "message": "Passphrase non valida"}), 400

    stored_path = hb.archive_path(hb.STORE_DIR, gen_id, manifest)
    path, workdir = stored_path, None
    if manifest.get("enc"):
        # The stored ciphertext has no wrapper; hand open_backup the manifest
        # by building one on the fly, so both entry points take the same road.
        # The wrapper lives in its own workdir, which the restore job cleans
        # up itself once it's actually done reading from it.
        workdir = tempfile.mkdtemp(prefix="hifi-restore-src-", dir="/run")
        path = os.path.join(workdir, "wrapper.tar.gz")
        try:
            hb.wrap_encrypted(path, manifest, stored_path)
        except Exception as e:
            shutil.rmtree(workdir, ignore_errors=True)
            return jsonify({"success": False, "message": f"Preparazione ripristino fallita: {e}"}), 500

    err = _start_restore(path, passphrase, data.get("categories"), workdir)
    if err:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        return jsonify(err[0]), err[1]
    return jsonify({"success": True, "started": True}), 202


@app.route("/api/backup/settings", methods=["GET", "POST"])
def api_backup_settings():
    denied = _require_pair_token()
    if denied:
        return denied
    if request.method == "GET":
        return jsonify(hb.read_settings())
    data = request.get_json(silent=True) or {}
    settings = {"scheduled": bool(data.get("scheduled")),
                "keep": max(1, min(20, int(data.get("keep") or hb.DEFAULT_KEEP)))}
    try:
        os.makedirs(os.path.dirname(hb.SETTINGS_FILE), exist_ok=True)
        tmp = hb.SETTINGS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(settings, f, indent=2)
        os.replace(tmp, hb.SETTINGS_FILE)
    except OSError as e:
        return jsonify({"success": False, "message": f"Salvataggio fallito: {e}"}), 500
    # The timer unit itself ships from the OS channel; this only flips it,
    # and 0033-backup-scheduler.sh re-applies the same choice on every OS
    # update so it survives one.
    action = "enable" if settings["scheduled"] else "disable"
    _run(["systemctl", action, "--now", "hifi-backup.timer"], timeout=30)
    return jsonify({"success": True, **settings})


@app.route("/api/restore/status", methods=["GET"])
def api_restore_status():
    denied = _require_pair_token()
    if denied:
        return denied
    return jsonify(_restore_status())


@app.route("/api/restore", methods=["POST"])
def api_restore():
    denied = _require_pair_token()
    if denied:
        return denied
    f = request.files.get("file")
    if not f:
        return _err("msg.noFile", 400)
    archive_bytes = f.read(MAX_RESTORE_ARCHIVE_SIZE + 1)
    if len(archive_bytes) > MAX_RESTORE_ARCHIVE_SIZE:
        return _err("msg.fileTooLarge", 400)
    passphrase = request.form.get("passphrase") or ""
    if not _passphrase_ok(passphrase):
        return jsonify({"success": False, "message": "Passphrase non valida"}), 400
    requested = request.form.get("categories") or ""
    categories = [c for c in requested.split(",") if c] or None

    workdir = tempfile.mkdtemp(prefix="hifi-upload-", dir="/run")
    os.chmod(workdir, 0o700)
    upload = os.path.join(workdir, "upload.tar.gz")
    with open(upload, "wb") as out:
        out.write(archive_bytes)
    err = _start_restore(upload, passphrase, categories, workdir)
    if err:
        shutil.rmtree(workdir, ignore_errors=True)
        return jsonify(err[0]), err[1]
    return jsonify({"success": True, "started": True}), 202


# ─────────────────────────── Room correction (FIR filter) ────────────
# Lets the user upload a convolution filter (impulse response) generated on a
# PC with REW/rePhase, for the optional DSP engine's room-correction toggle
# (Settings → DSP, api_server.py). Only ONE filter is kept at a time, always
# under the fixed name "room.<ext>" — never a user-supplied filename — so
# there is no path-traversal surface. The file is applied identically to both
# channels; api_server.py's _camilla_config_dict() picks it up if present and
# room_correction is enabled.
FIR_DIR = "/etc/camilladsp/filters"
# Extension -> CamillaDSP Conv "type" (both are officially documented formats,
# not guessed): a WAV impulse response, or a plain text file with one
# coefficient per line (CamillaDSP's Raw/TEXT format).
FIR_KINDS = {".wav": "Wav", ".txt": "Raw"}
# Fixed ext -> filename lookup (not string-built from the ext at request time)
# so the stored/opened path is always one of these two literal names, never a
# concatenation of request-derived data.
FIR_FILENAMES = {".wav": "room.wav", ".txt": "room.txt"}
FIR_MAX_SIZE = 20 * 1024 * 1024


def _fir_current():
    """Return (path, ext) of the currently stored filter, or (None, None)."""
    if os.path.isdir(FIR_DIR):
        for ext, filename in FIR_FILENAMES.items():
            p = os.path.join(FIR_DIR, filename)
            if os.path.isfile(p):
                return p, ext
    return None, None


@app.route("/api/dsp/fir", methods=["GET"])
def api_dsp_fir_status():
    denied = _require_pair_token()
    if denied:
        return denied
    path, ext = _fir_current()
    if not path:
        return jsonify({"present": False})
    return jsonify({"present": True, "filename": os.path.basename(path),
                     "kind": FIR_KINDS[ext], "size": os.path.getsize(path)})


@app.route("/api/dsp/fir", methods=["POST"])
def api_dsp_fir_upload():
    denied = _require_pair_token()
    if denied:
        return denied
    f = request.files.get("file")
    if not f or not f.filename:
        return _err("msg.noFile", 400)
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in FIR_KINDS:
        return _err("msg.badFilterFormat", 400)
    data = f.read(FIR_MAX_SIZE + 1)
    if len(data) > FIR_MAX_SIZE:
        return _err("msg.fileTooLarge20", 400)
    if not data:
        return _err("msg.fileEmpty", 400)
    try:
        os.makedirs(FIR_DIR, exist_ok=True)
        # Only one filter at a time: clear any previous room.* before writing.
        for other_filename in FIR_FILENAMES.values():
            other = os.path.join(FIR_DIR, other_filename)
            if os.path.isfile(other):
                os.remove(other)
        dest = os.path.join(FIR_DIR, FIR_FILENAMES[ext])
        tmp = dest + ".tmp"
        with open(tmp, "wb") as out:
            out.write(data)
        os.replace(tmp, dest)
    except Exception as e:
        print(f"[sources] FIR filter save failed: {e}")
        return _err("msg.saveFailed", 500)
    return jsonify({"success": True, "code": "msg.filterUploaded", "message": _m("msg.filterUploaded")})


@app.route("/api/dsp/fir", methods=["DELETE"])
def api_dsp_fir_delete():
    denied = _require_pair_token()
    if denied:
        return denied
    removed = False
    for filename in FIR_FILENAMES.values():
        p = os.path.join(FIR_DIR, filename)
        if os.path.isfile(p):
            os.remove(p)
            removed = True
    return jsonify({"success": True, "removed": removed})


# ─────────────────────────── App pairing token ────────────────────────
# The companion app's DSP controls are a live "control" surface (unlike the
# FIR/backup/restore endpoints above, which are also reachable from a plain
# phone browser via the separate sourcesUrl QR and must stay usable from a
# bare <a href>). To scope DSP control to phones the user has actually
# paired, the appliance UI (Settings → Phone control) mints a fresh token
# each time the pairing QR is (re)generated and embeds it in the QR
# alongside the LMS/API host:port; the app stores it and sends it back as
# `Authorization: Bearer <token>` on every DSP call. Tokens are persisted
# (survive a service restart) and never expire/rotate out on their own —
# re-scanning the QR just adds another valid token, so multiple paired
# phones can coexist.
PAIR_TOKENS_FILE = "/etc/hifi-pairing-tokens.json"


def _load_pair_tokens():
    try:
        with open(PAIR_TOKENS_FILE) as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_pair_tokens(tokens):
    os.makedirs(os.path.dirname(PAIR_TOKENS_FILE), exist_ok=True)
    tmp = PAIR_TOKENS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(tokens, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, PAIR_TOKENS_FILE)


@app.route("/api/pair/token", methods=["POST"])
def api_pair_token():
    """Mint a new pairing token, shown to the user only via the appliance's
    own QR code (Settings → Phone control). Restricted to localhost: the
    Electron kiosk UI is the only caller (it runs on the appliance itself),
    so a token can only ever be minted by someone with physical access to
    the appliance's screen. Without this check, any device on the LAN could
    just POST here directly and self-mint a valid token, defeating the whole
    point of gating DSP control behind pairing."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return _err("msg.notAllowedRemotely", 403)
    token = secrets.token_urlsafe(24)
    tokens = _load_pair_tokens()
    tokens.append({"token": token, "created": datetime.now(timezone.utc).isoformat()})
    _save_pair_tokens(tokens)
    return jsonify({"token": token})


@app.route("/api/pair/tokens/revoke_all", methods=["POST"])
def api_pair_tokens_revoke_all():
    """Invalidate every paired phone at once. Restricted to localhost for the
    same reason as minting above: only someone standing at the appliance can
    nuke every token, so a leaked/stolen token can always be neutralised by
    walking up to the device and re-pairing, without needing per-token
    expiry (which would otherwise log out every legitimately paired phone
    just to bound a theft that may never have happened)."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return _err("msg.notAllowedRemotely", 403)
    _save_pair_tokens([])
    return jsonify({"success": True})


# Per-IP failed-auth throttle for _require_pair_token(). In-memory only (the
# service runs single-process/multi-threaded via `threaded=True`, so a
# lock-guarded dict is enough — no cross-process state needed, and losing it
# on restart is fine since it exists purely to slow down online guessing).
_auth_fail_lock = threading.Lock()
_auth_fail_log = {}  # ip -> list of failure timestamps (monotonic)
_AUTH_FAIL_WINDOW = 60.0
_AUTH_FAIL_MAX = 20


def _auth_rate_limited(ip):
    now = time.monotonic()
    with _auth_fail_lock:
        fails = [t for t in _auth_fail_log.get(ip, []) if now - t < _AUTH_FAIL_WINDOW]
        _auth_fail_log[ip] = fails
        return len(fails) >= _AUTH_FAIL_MAX


def _auth_record_failure(ip):
    with _auth_fail_lock:
        _auth_fail_log.setdefault(ip, []).append(time.monotonic())


def _require_pair_token():
    """Returns None if the request is exempt (local kiosk UI) or carries a
    valid pairing token, otherwise a (jsonify(...), status) tuple to return
    immediately. The Electron kiosk UI on the appliance itself already calls
    these endpoints from 127.0.0.1 (same machine, no network hop) — only
    requests arriving over the LAN (the phone app) need a token."""
    if request.remote_addr in ("127.0.0.1", "::1"):
        return None
    ip = request.remote_addr
    if _auth_rate_limited(ip):
        return _err("msg.tooManyAttempts", 429)
    auth = request.headers.get("Authorization", "")
    token = auth[len("Bearer "):] if auth.startswith("Bearer ") else None
    if not token:
        # Fallback for the embedded SPA's plain browser-navigation flows (the
        # backup download link, restore file input) which can't attach a
        # custom Authorization header. The SPA embeds the token minted for it
        # in the QR-carried URL (?token=...) and forwards it here — same
        # secret, just a different transport, since a plain <a href> click
        # can't set headers.
        token = request.args.get("token") or None
    valid = bool(token) and any(
        secrets.compare_digest(t.get("token", ""), token) for t in _load_pair_tokens()
    )
    if not valid:
        _auth_record_failure(ip)
        return _err("msg.badPairToken", 401)
    return None


# ─────────────────────────── DSP status/control proxy ────────────────
# api_server.py:8000 (root, unauthenticated, exposes reboot/shutdown/network
# reconfig) is deliberately loopback-only — see the bind comment at the
# bottom of that file. dsp_status/dsp_set are the one piece of that API the
# phone companion app needs, so we relay just those two calls through this
# already-LAN-exposed, already-root service instead of widening api_server's
# bind address. Unlike the FIR/backup endpoints above, these two require a
# valid pairing token (see above) since they're control, not just data.
_API_SERVER_BASE = "http://127.0.0.1:8000"


def _proxy_to_api_server(path, method="GET", body=None, timeout=10):
    # Callers that trigger a full DSP apply pass a longer timeout: applying
    # now pauses playback, restarts squeezelite/CamillaDSP, waits for the
    # player to re-register with Lyrion (up to ~10s) and seeks back — easily
    # past the default 10s, and timing out here made the phone report
    # "Servizio DSP non raggiungibile" while the apply was in fact succeeding.
    req = urllib.request.Request(f"{_API_SERVER_BASE}{path}", method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8")), e.code
        except Exception:
            # api_server.py didn't return JSON for this error — don't forward
            # the raw exception text (may contain internal paths/details) to
            # the caller; log it server-side instead.
            print(f"[sources] proxy to {path} failed: {e}")
            return {"success": False, "code": "msg.dspUnavailable", "message": _m("msg.dspUnavailable")}, e.code
    except Exception as e:
        print(f"[sources] proxy to {path} unreachable: {e}")
        return {"success": False, "code": "msg.dspUnreachable", "message": _m("msg.dspUnreachable")}, 502


@app.route("/api/dsp/status", methods=["GET"])
def api_dsp_status_proxy():
    denied = _require_pair_token()
    if denied:
        return denied
    body, status = _proxy_to_api_server("/dsp_status")
    return jsonify(body), status


@app.route("/api/dsp/set", methods=["POST"])
def api_dsp_set_proxy():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    body, status = _proxy_to_api_server("/dsp_set", method="POST", body=data, timeout=60)
    return jsonify(body), status


@app.route("/api/dsp/presets", methods=["GET"])
def api_dsp_presets_proxy():
    denied = _require_pair_token()
    if denied:
        return denied
    body, status = _proxy_to_api_server("/dsp_presets")
    return jsonify(body), status


@app.route("/api/dsp/preset/save", methods=["POST"])
def api_dsp_preset_save_proxy():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    body, status = _proxy_to_api_server("/dsp_preset_save", method="POST", body=data)
    return jsonify(body), status


@app.route("/api/dsp/preset/load", methods=["POST"])
def api_dsp_preset_load_proxy():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    # Preset load runs a full set_dsp() apply on the appliance — long timeout,
    # same reasoning as /api/dsp/set above.
    body, status = _proxy_to_api_server("/dsp_preset_load", method="POST", body=data, timeout=60)
    return jsonify(body), status


@app.route("/api/dsp/preset/rename", methods=["POST"])
def api_dsp_preset_rename_proxy():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    body, status = _proxy_to_api_server("/dsp_preset_rename", method="POST", body=data)
    return jsonify(body), status


@app.route("/api/dsp/preset/delete", methods=["POST"])
def api_dsp_preset_delete_proxy():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    body, status = _proxy_to_api_server("/dsp_preset_delete", method="POST", body=data)
    return jsonify(body), status


# ─────────────────────────── System / admin proxy ─────────────────────
# Same rationale as the DSP proxy above: these all live on api_server.py's
# loopback-only port (system info, SSH toggle, OTA channel + update
# check/apply/status for each of the 4 update kinds, reboot/shutdown, audio
# device selection). All require a pairing token except from localhost (the
# kiosk UI) — see _require_pair_token(). Table-driven to avoid 20 near-
# identical view functions; each entry is (our path, method, api_server.py
# path).
_SYSTEM_PROXY_ROUTES = [
    ("/api/system/info", "GET", "/system_info"),
    ("/api/system/ssh", "GET", "/ssh_status"),
    ("/api/system/ssh", "POST", "/ssh_set"),
    ("/api/system/ota_channel", "GET", "/ota_channel"),
    ("/api/system/ota_channel", "POST", "/ota_channel"),
    ("/api/system/audio_devices", "GET", "/audio_devices"),
    ("/api/system/audio_device", "POST", "/set_audio_device"),
    # Display mode (GUI kiosk <-> headless). Lets a paired companion bring a
    # headless unit back to the on-screen GUI remotely — the only way back when
    # there is no screen. Non-destructive, so the pairing token alone is enough
    # (factory reset, which IS destructive, is deliberately NOT proxied here).
    ("/api/system/display_mode", "GET", "/display_mode"),
    ("/api/system/display_mode", "POST", "/display_mode"),
    # UI render resolution (framebuffer downscale + GPU upscale). Same
    # rationale as above: non-destructive, and worth reaching remotely because
    # the unit it helps most is the one driving a big TV.
    ("/api/system/ui_resolution", "GET", "/ui_resolution"),
    ("/api/system/ui_resolution", "POST", "/ui_resolution"),
    # Animated VU meter toggle. Same rationale as ui_resolution: no OS action,
    # but worth reaching remotely because a headless unit can never open the
    # on-screen Settings to flip it locally.
    ("/api/system/vu_meter", "GET", "/vu_meter"),
    ("/api/system/vu_meter", "POST", "/vu_meter"),
    ("/api/system/player_name", "GET", "/player_name"),
    ("/api/system/player_name", "POST", "/player_name"),
    ("/api/system/lms_role", "GET", "/lms_role"),
    ("/api/system/lms_role", "POST", "/lms_role"),
    ("/api/system/discover_lms", "GET", "/discover_lms"),
    ("/api/system/updates/app/check", "GET", "/app_update/check"),
    ("/api/system/updates/app/apply", "POST", "/app_update/apply"),
    ("/api/system/updates/app/status", "GET", "/app_update/status"),
    ("/api/system/updates/system/check", "GET", "/system_update/check"),
    ("/api/system/updates/system/apply", "POST", "/system_update/apply"),
    ("/api/system/updates/system/status", "GET", "/system_update/status"),
    ("/api/system/updates/os/check", "GET", "/os_update/check"),
    ("/api/system/updates/os/apply", "POST", "/os_update/apply"),
    ("/api/system/updates/os/status", "GET", "/os_update/status"),
    # Sequenced multi-component update (server-side plan). The companion used to
    # chain the three components itself over the network, which made it the most
    # fragile of the three clients — every restart the update performs dropped
    # its connection mid-sequence.
    ("/api/system/updates/apply_all", "POST", "/update/apply_all"),
    ("/api/system/updates/status", "GET", "/update/status"),
    ("/api/system/updates/dismiss", "POST", "/update/dismiss"),
    ("/api/system/updates/lyrion/check", "GET", "/lyrion_update/check"),
    ("/api/system/updates/lyrion/apply", "POST", "/lyrion_update/apply"),
    ("/api/system/updates/lyrion/status", "GET", "/lyrion_update/status"),
    ("/api/system/lyrion_channel", "GET", "/lyrion_channel"),
    ("/api/system/lyrion_channel", "POST", "/lyrion_channel"),
    # Deliberately NOT exposed here: /shell_account. It mints a Linux user with
    # full sudo, and the only thing authenticating a companion request is the
    # pairing token — a stolen one must not be able to create a root-capable
    # login. The companion reads the SSH login name from /ssh_status (which
    # carries `account`) and sends the user to the touchscreen or web admin to
    # create or change it.
    ("/api/system/reboot", "POST", "/reboot"),
    ("/api/system/shutdown", "POST", "/shutdown"),
]


def _make_system_proxy_view(remote_path, method):
    # Starting an update is slower than the default budget: api_server resolves
    # the release and downloads a checksum sidecar per component before it can
    # write the plan. Timing out here would tell the phone the update failed
    # while the appliance was in fact about to start it — and the phone would
    # then fall back to driving the sequence itself, on top of a running plan.
    timeout = 90 if "apply" in remote_path else 10
    def view():
        denied = _require_pair_token()
        if denied:
            return denied
        data = request.get_json(silent=True) if method == "POST" else None
        body, status = _proxy_to_api_server(remote_path, method=method, body=data,
                                            timeout=timeout)
        return jsonify(body), status
    return view


for _local_path, _method, _remote_path in _SYSTEM_PROXY_ROUTES:
    app.add_url_rule(
        _local_path,
        endpoint=f"system_proxy_{_method}_{_local_path}",
        view_func=_make_system_proxy_view(_remote_path, _method),
        methods=[_method],
    )


# ─────────────────────────── HTTP API ───────────────────────────────
@app.route("/api/sources", methods=["GET"])
def api_list():
    # Previously exempt ("read-only, no secrets") — but source names/paths/SMB
    # server+username are still information disclosure to any device that can
    # merely reach port 8080 on the LAN, so this now requires the same pairing
    # token as everything else. Loopback (Electron kiosk, and the webui:443
    # proxy's own forwarded requests — see webui_server.py's SECURITY comment
    # on _forward_to()) and a valid ?token=/companion app remain exempt/allowed
    # via _require_pair_token() itself.
    denied = _require_pair_token()
    if denied:
        return denied
    state = load_state()
    out = []
    for s in state.get("sources", []):
        item = dict(s)
        item.pop("password", None)
        item.pop("smbpassword", None)
        t = s.get("type")
        if t == "smb":
            item["mounted"] = os.path.ismount(s["mountpoint"])
        elif t in ("internal", "usb"):
            item["mounted"] = os.path.ismount(s.get("mountpoint", ""))
            item["share"] = s.get("share")
        else:
            item["exists"] = os.path.isdir(s.get("path", ""))
        out.append(item)
    return jsonify({"sources": out, "paths": current_paths(state)})


def _format_watcher():
    """Background thread: when the format job finishes, adopt the new partition."""
    deadline = time.monotonic() + 15 * 60
    while time.monotonic() < deadline:
        try:
            if not os.path.exists(FORMAT_STATUS):
                time.sleep(2)
                continue
            with open(FORMAT_STATUS) as f:
                st = json.load(f)
            state = st.get("state")
            if state in ("done", "error", "idle"):
                if state == "done":
                    _auto_adopt_formatted(st)
                break
        except Exception as e:
            print(f"[sources] format watcher error: {e}")
        time.sleep(2)


def _auto_adopt_formatted(st):
    device = st.get("partition")
    partuuid = st.get("partuuid")
    fstype = (st.get("fstype") or "").lower()
    label = st.get("label") or "Musica"
    if not device or not partuuid or fstype not in ("ext4", "exfat"):
        return
    # Re-read lsblk to get the fresh partition details.
    data = _lsblk_full() or {}
    part = None
    for dev in data.get("blockdevices", []):
        for p in dev.get("children") or []:
            if p.get("partuuid") == partuuid or p.get("path") == device:
                part = p
                break
        if part:
            break
    if not part:
        return

    share = _share_name(label)
    mountpoint = os.path.join(INTERNAL_MOUNT_ROOT,
                              _slug(label) + "-" + partuuid[:8])
    src = {
        "id": _slug("internal", share),
        "type": "internal",
        "name": f"{label} (interno)",
        "partuuid": partuuid,
        "fsuuid": part.get("uuid"),
        "fstype": fstype,
        "label": label,
        "model": (part.get("model") or "").strip(),
        "mountpoint": mountpoint,
        "share": share,
    }
    ok, msg = mount_internal(src)
    if not ok:
        print(f"[sources] auto-adopt mount failed: {msg}")
        return
    with _lock:
        state = load_state()
        state["sources"] = [s for s in state["sources"] if s.get("id") != src["id"]]
        state["sources"].append(src)
        save_state(state)
        regen_samba_shares()
    # Mark status as adopted so the UI can show success.
    try:
        with open(FORMAT_STATUS) as f:
            st = json.load(f)
        st["adopted"] = True
        st["source_id"] = src["id"]
        st["share"] = share
        with open(FORMAT_STATUS, "w") as f:
            json.dump(st, f)
    except Exception:
        pass
    try:
        apply_to_lyrion(load_state())
    except Exception as e:
        print(f"[sources] auto-adopt apply_to_lyrion failed: {e}")


def _local_path_allowed(path):
    """Resolve `path` and confine it to an allow-listed media root. Returns the
    resolved realpath if allowed, otherwise None. Shared by api_add_local
    (fresh user input) and the restore-time re-validation of a restored
    hifi-sources.json (untrusted archive content) — both must apply the exact
    same confinement before the path is ever touched on disk or handed to
    Lyrion as a media directory."""
    path = os.path.realpath(path)
    for root in ALLOWED_LOCAL_ROOTS:
        root = os.path.realpath(root)
        if path == root or path.startswith(root + os.sep):
            return path
    return None


@app.route("/api/sources/local", methods=["POST"])
def api_add_local():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    if not path:
        return _err("msg.pathMissing", 400)
    path = _local_path_allowed(path)
    if not path:
        return _err("msg.pathNotAllowed", 400)
    if not os.path.isdir(path):
        return _err("msg.folderMissing", 400, path=path)
    with _lock:
        state = load_state()
        sid = _slug("local", os.path.basename(path.rstrip("/")))
        state["sources"] = [s for s in state["sources"] if s.get("id") != sid]
        state["sources"].append({"id": sid, "type": "local", "name": path, "path": path})
        save_state(state)
    return jsonify({"success": True})


@app.route("/api/sources/smb", methods=["POST"])
def api_add_smb():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    server = (data.get("server") or "").strip().strip("/")
    share = (data.get("share") or "").strip().strip("/")
    if not server or not share:
        return _err("msg.smbFieldsRequired", 400)
    name = data.get("name") or f"{server}/{share}"
    sid = _slug("smb", server, share)
    src = {
        "id": sid,
        "type": "smb",
        "name": name,
        "server": server,
        "share": share,
        "username": (data.get("username") or "").strip(),
        "password": data.get("password") or "",
        "mountpoint": os.path.join(MOUNT_ROOT, _slug(server, share)),
    }
    ok, msg = mount_smb(src)
    if not ok:
        return _err("msg.mountFailed", 400, detail=msg)
    with _lock:
        state = load_state()
        state["sources"] = [s for s in state["sources"] if s.get("id") != sid]
        state["sources"].append(src)
        save_state(state)
    return jsonify({"success": True, "message": msg})


@app.route("/api/sources/<sid>", methods=["DELETE"])
def api_remove(sid):
    denied = _require_pair_token()
    if denied:
        return denied
    with _lock:
        state = load_state()
        keep = []
        for s in state["sources"]:
            if s.get("id") == sid:
                t = s.get("type")
                if t == "smb":
                    umount(s["mountpoint"])
                elif t in ("internal", "usb"):
                    umount(s.get("mountpoint"))
            else:
                keep.append(s)
        state["sources"] = keep
        save_state(state)
        regen_samba_shares()
    return jsonify({"success": True})


@app.route("/api/apply", methods=["POST"])
def api_apply():
    denied = _require_pair_token()
    if denied:
        return denied
    state = load_state()
    ok, msg = apply_to_lyrion(state)
    return jsonify({"success": ok, "message": msg}), (200 if ok else 500)


@app.route("/api/internal/disks", methods=["GET"])
def api_internal_disks():
    denied = _require_pair_token()
    if denied:
        return denied
    return jsonify({"disks": _internal_disks()})


@app.route("/api/internal/adopt", methods=["POST"])
def api_internal_adopt():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    device = (data.get("device") or "").strip()
    if not _path_ok(device):
        return _err("msg.badDevice", 400)

    disks = _internal_disks()
    disk = None
    part = None
    for d in disks:
        if d["path"] == device:
            disk = d
            break
        for p in d.get("partitions") or []:
            if p["path"] == device:
                disk = d
                part = p
                break
    if not disk:
        return _err("msg.diskNotFound", 400)
    if not part:
        # Whole disk with no partitions: reject.
        return _err("msg.pickPartition", 400)
    if not part.get("fstype"):
        return _err("msg.partitionNoFs", 400)

    partuuid = part.get("partuuid")
    fsuuid = part.get("uuid")
    fstype = (part.get("fstype") or "").lower()
    label = part.get("label") or disk.get("label") or "Musica"
    model = disk.get("model") or ""
    share = _share_name(label)
    mountpoint = os.path.join(INTERNAL_MOUNT_ROOT,
                              _slug(label) + "-" + (partuuid or fsuuid or "adopt")[:8])

    src = {
        "id": _slug("internal", share),
        "type": "internal",
        "name": f"{label or 'Musica'} (interno)",
        "partuuid": partuuid,
        "fsuuid": fsuuid,
        "fstype": fstype,
        "label": label,
        "model": model,
        "mountpoint": mountpoint,
        "share": share,
    }
    ok, msg = mount_internal(src)
    if not ok:
        return _err("msg.mountFailed", 400, detail=msg)

    with _lock:
        state = load_state()
        state["sources"] = [s for s in state["sources"] if s.get("id") != src["id"]]
        state["sources"].append(src)
        save_state(state)
        regen_samba_shares()
    apply_to_lyrion(state)
    return jsonify({"success": True, "source_id": src["id"], "share": share})


@app.route("/api/usb/adopt", methods=["POST"])
def api_usb_adopt():
    """Adopt a currently-connected USB partition as a persistent, read-write,
    Samba-shared source — the USB equivalent of /api/internal/adopt. No
    reformat: mounts whatever filesystem is already on it (ext4/exfat/vfat, or
    NTFS via the in-kernel ntfs3 driver)."""
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    device = (data.get("device") or "").strip()
    if not _path_ok(device):
        return _err("msg.badDevice", 400)

    part = next((p for p in _usb_partitions() if p.get("path") == device), None)
    if not part:
        return _err("msg.diskNotFound", 400)
    if not part.get("fstype"):
        return _err("msg.partitionNoFs", 400)

    partuuid = part.get("partuuid")
    fsuuid = part.get("uuid")
    fstype = (part.get("fstype") or "").lower()
    label = part.get("label") or part.get("name") or "USB"
    share = _share_name(label)
    mountpoint = os.path.join(USB_ADOPTED_ROOT,
                              _slug(label) + "-" + (partuuid or fsuuid or "adopt")[:8])

    # Drop the ephemeral read-only browse mount for this device (if any),
    # guarded by the same lock usb_sync() uses, so the background monitor
    # can't recreate it out from under us mid-adopt. Any "local" source that
    # was pointed into it would otherwise dangle once it's gone.
    ephemeral_mp = _usb_mountpoint(part)
    with _lock:
        if os.path.ismount(ephemeral_mp):
            umount(ephemeral_mp)
        try:
            os.rmdir(ephemeral_mp)
        except OSError:
            pass

    src = {
        "id": _slug("usb", share),
        "type": "usb",
        "name": f"{label or 'USB'} (USB)",
        "partuuid": partuuid,
        "fsuuid": fsuuid,
        "fstype": fstype,
        "label": label,
        "model": "",
        "mountpoint": mountpoint,
        "share": share,
    }
    ok, msg = mount_usb_adopted(src)
    if not ok:
        return _err("msg.mountFailed", 400, detail=msg)

    def _stale_local(s):
        if s.get("type") != "local":
            return False
        p = s.get("path") or ""
        return p == ephemeral_mp or p.startswith(ephemeral_mp + os.sep)

    with _lock:
        state = load_state()
        state["sources"] = [
            s for s in state["sources"]
            if s.get("id") != src["id"] and not _stale_local(s)
        ]
        state["sources"].append(src)
        save_state(state)
        regen_samba_shares()
    # Deliberately does NOT call apply_to_lyrion() — that does a full
    # systemctl stop/start of lyrionmusicserver, which drops the squeezelite
    # connection and kills any music currently playing. The Samba share is
    # already live at this point (regen_samba_shares() above) without it, so
    # there's no need to force that disruption automatically on every USB
    # plug-in-and-adopt; the user applies it to the library explicitly via
    # "Apply & rescan library" when ready — matching how adding a local
    # folder or SMB source already behaves (api_add_local/api_add_smb below
    # don't auto-apply either; only the rarer, one-time internal-disk-adopt
    # flow does).
    return jsonify({"success": True, "source_id": src["id"], "share": share})


@app.route("/api/internal/format", methods=["POST"])
def api_internal_format():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    device = (data.get("device") or "").strip()
    fs = (data.get("fs") or "").strip().lower()
    label = (data.get("label") or "").strip()
    confirm = (data.get("confirm") or "").strip()

    if not _path_ok(device):
        return _err("msg.badDevice", 400)
    if fs not in ("ext4", "exfat"):
        return _err("msg.unsupportedFs", 400)
    if not _label_ok(label):
        return _err("msg.badLabel", 400)
    if fs == "exfat" and len(label) > 11:
        return _err("msg.labelTooLongExfat", 400)

    disks = _internal_disks()
    disk = next((d for d in disks if d["path"] == device), None)
    if not disk:
        return _err("msg.diskNotFound", 400)
    if disk.get("confirm") != confirm:
        return _err("msg.confirmMismatch", 400)
    if disk.get("adopted"):
        return _err("msg.alreadyAdopted", 400)

    # Check no partitions are mounted.
    for p in disk.get("partitions") or []:
        if p.get("mountpoint"):
            return _err("msg.unmountFirst", 400)

    # Check mkfs.exfat is available when requested.
    if fs == "exfat":
        if _run(["which", "mkfs.exfat"], timeout=5).returncode != 0:
            return _err("msg.osUpdateForExfat", 424)

    # Interlock: no concurrent format job.
    if os.path.exists(FORMAT_STATUS):
        try:
            with open(FORMAT_STATUS) as f:
                st = json.load(f)
            if st.get("state") not in ("done", "error", "idle"):
                return _err("msg.formatInProgress", 409)
        except Exception:
            pass

    # Reset status file.
    with open(FORMAT_STATUS, "w") as f:
        json.dump({"state": "idle", "progress": 0, "message": "Avvio…"}, f)

    _run(["systemd-run", "--no-block", "--collect", "--unit=" + FORMAT_UNIT,
          FORMAT_SCRIPT, device, fs, label], timeout=10)
    return jsonify({"success": True}), 202


@app.route("/api/internal/format/status", methods=["GET"])
def api_internal_format_status():
    denied = _require_pair_token()
    if denied:
        return denied
    status = {"state": "idle"}
    if os.path.exists(FORMAT_STATUS):
        try:
            with open(FORMAT_STATUS) as f:
                status = json.load(f)
        except Exception:
            pass
    # Enrich with adoption info if done.
    if status.get("state") == "done":
        partuuid = status.get("partuuid")
        if partuuid:
            for s in _adopted_disk_sources():
                if s.get("partuuid") == partuuid:
                    status["adopted"] = True
                    status["source_id"] = s.get("id")
                    status["share"] = s.get("share")
                    break
    return jsonify(status)


# ─────────────────────────── CD ripping ─────────────────────────────
# Same async-job shape as the disk format above: kick off a detached worker
# via systemd-run, poll a status file on /run, then a watcher thread finishes
# the job (ownership fix + Lyrion rescan). The Lyrion CD Player plugin only
# *plays* discs; this archives them into the library as tagged FLAC.

_cd_info_cache = {}  # discid -> metadata dict from MusicBrainz


def _cd_toc():
    """Read the audio-CD TOC via cd-discid. Returns None when there is no
    readable audio disc. Output format: `discid ntracks off1 ... offN seconds`
    (offsets in CD frames, 75/s, lead-in included)."""
    try:
        r = _run(["cd-discid", CD_DEVICE], timeout=20)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    parts = (r.stdout or "").split()
    if len(parts) < 4:
        return None
    try:
        ntracks = int(parts[1])
        offsets = [int(x) for x in parts[2:2 + ntracks]]
        total_sec = int(parts[2 + ntracks])
    except (ValueError, IndexError):
        return None
    if ntracks < 1 or len(offsets) != ntracks:
        return None
    lengths = []
    for i in range(ntracks):
        if i + 1 < ntracks:
            lengths.append(max(0, (offsets[i + 1] - offsets[i]) // 75))
        else:
            lengths.append(max(0, total_sec - offsets[i] // 75))
    return {"discid": parts[0], "ntracks": ntracks, "offsets": offsets,
            "total_sec": total_sec, "lengths": lengths}


def _mb_lookup(toc):
    """Look the disc up on MusicBrainz by fuzzy TOC. Returns a metadata dict
    or None (offline, unknown disc, malformed response...)."""
    leadout = toc["total_sec"] * 75 + 150
    toc_str = "+".join(str(x) for x in
                       [1, toc["ntracks"], leadout] + toc["offsets"])
    url = ("https://musicbrainz.org/ws/2/discid/-"
           f"?toc={toc_str}&fmt=json&inc=artist-credits+recordings")
    req = urllib.request.Request(url, headers={
        "User-Agent": "OsmiumSound/1.0 (https://osmiumsound.qd.je)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[sources] musicbrainz lookup failed: {e}")
        return None
    releases = data.get("releases") or []
    if not releases:
        return None
    rel = releases[0]
    artist = "".join(
        (c.get("name") or "") + (c.get("joinphrase") or "")
        for c in rel.get("artist-credit") or []
    ) or "Unknown Artist"
    titles = []
    for medium in rel.get("media") or []:
        for tr in medium.get("tracks") or []:
            titles.append(tr.get("title") or "")
        if titles:
            break  # first medium only: one physical disc in the drive
    return {
        "mbid": rel.get("id"),
        "artist": artist,
        "album": rel.get("title") or "Unknown Album",
        "year": (rel.get("date") or "")[:4],
        "titles": titles,
    }


def _cd_metadata(toc):
    """MusicBrainz metadata for `toc` (cached), padded with offline fallbacks
    so callers always get artist/album and one title per track."""
    meta = _cd_info_cache.get(toc["discid"])
    if meta is None:
        meta = _mb_lookup(toc) or {}
        if meta:
            _cd_info_cache[toc["discid"]] = meta
    titles = list(meta.get("titles") or [])
    tracks = []
    for i in range(toc["ntracks"]):
        title = titles[i] if i < len(titles) and titles[i] else f"Track {i + 1:02d}"
        tracks.append({"num": i + 1, "title": title, "length": toc["lengths"][i]})
    return {
        "mbid": meta.get("mbid"),
        "artist": meta.get("artist") or "Unknown Artist",
        "album": meta.get("album") or "Unknown Album",
        "year": meta.get("year") or "",
        "tracks": tracks,
    }


def _rip_state():
    if os.path.exists(RIP_STATUS):
        try:
            with open(RIP_STATUS) as f:
                return json.load(f)
        except Exception:
            pass
    return {"state": "idle"}


def _rip_running():
    return _rip_state().get("state") not in ("idle", "done", "error")


def _lyrion_rescan():
    payload = {"id": 1, "method": "slim.request", "params": ["", ["rescan"]]}
    req = urllib.request.Request(
        LYRION_RPC, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)


def _rip_watcher():
    """Background thread (spawned per rip): when the worker reports done, fix
    ownership for Samba access and ask Lyrion for a rescan — a plain rescan,
    not apply_to_lyrion(), so LMS is not restarted mid-listen."""
    deadline = time.monotonic() + 3 * 60 * 60
    while time.monotonic() < deadline:
        time.sleep(3)
        try:
            st = _rip_state()
            state = st.get("state")
            if state in ("done", "error", "idle"):
                if state == "done":
                    dest = st.get("dest") or ""
                    uid, gid = _ensure_samba_uid_gid()
                    if dest.startswith(INTERNAL_MOUNT_ROOT + "/") and os.path.isdir(dest):
                        for root, dirs, files in os.walk(dest):
                            for name in dirs + files:
                                try:
                                    os.chown(os.path.join(root, name), uid, gid)
                                except OSError:
                                    pass
                        try:
                            os.chown(dest, uid, gid)
                        except OSError:
                            pass
                    try:
                        _lyrion_rescan()
                    except Exception as e:
                        print(f"[sources] rip rescan failed: {e}")
                return
        except Exception as e:
            print(f"[sources] rip watcher error: {e}")


def _rip_writable_sources():
    """Adopted (rw, hifimusic-owned) internal or USB sources the rip can write
    into. Ephemeral read-only USB browse mounts never qualify."""
    out = []
    for s in _adopted_disk_sources():
        mp = s.get("mountpoint") or ""
        if os.path.ismount(mp) and os.access(mp, os.W_OK):
            out.append(s)
    return out


@app.route("/api/cd/info", methods=["GET"])
def api_cd_info():
    denied = _require_pair_token()
    if denied:
        return denied
    toc = _cd_toc()
    if not toc:
        return jsonify({"no_disc": True})
    meta = _cd_metadata(toc)
    return jsonify({
        "no_disc": False,
        "discid": toc["discid"],
        "artist": meta["artist"],
        "album": meta["album"],
        "year": meta["year"],
        "tracks": meta["tracks"],
        "destinations": [
            {"source_id": s.get("id"), "name": s.get("name") or s.get("label")}
            for s in _rip_writable_sources()
        ],
        "ripping": _rip_running(),
    })


@app.route("/api/cd/rip", methods=["POST"])
def api_cd_rip():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    toc = _cd_toc()
    if not toc:
        return _err("msg.noAudioCd", 400)
    if _rip_running():
        return _err("msg.ripInProgress", 409)

    sources = _rip_writable_sources()
    source_id = (data.get("source_id") or "").strip()
    src = next((s for s in sources if s.get("id") == source_id), None)
    if src is None:
        if len(sources) == 1 and not source_id:
            src = sources[0]
        else:
            return jsonify({"success": False,
                            "message": "Nessuna destinazione scrivibile: adotta un disco interno"}), 400

    meta = _cd_metadata(toc)
    artist = str(data.get("artist") or meta["artist"]).strip() or "Unknown Artist"
    album = str(data.get("album") or meta["album"]).strip() or "Unknown Album"
    year = str(data.get("year") or meta["year"]).strip()[:4]
    tracks = meta["tracks"]
    override = data.get("tracks")
    if isinstance(override, list) and len(override) == len(tracks):
        for i, t in enumerate(override):
            title = str(t or "").strip()
            if title:
                tracks[i]["title"] = title

    # Cover art (best effort, embedded by the worker if present).
    try:
        os.remove(RIP_COVER)
    except OSError:
        pass
    if meta.get("mbid"):
        try:
            req = urllib.request.Request(
                f"https://coverartarchive.org/release/{meta['mbid']}/front-500",
                headers={"User-Agent": "OsmiumSound/1.0 (https://osmiumsound.qd.je)"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                cover = resp.read(5 * 1024 * 1024)
            with open(RIP_COVER, "wb") as f:
                f.write(cover)
        except Exception:
            pass

    plan = {
        "device": CD_DEVICE,
        "root": src["mountpoint"],
        "artist": artist,
        "album": album,
        "year": year,
        "discid": toc["discid"],
        "cover": RIP_COVER if os.path.exists(RIP_COVER) else "",
        "tracks": tracks,
    }
    with open(RIP_PLAN, "w") as f:
        json.dump(plan, f)
    os.chmod(RIP_PLAN, 0o600)
    with open(RIP_STATUS, "w") as f:
        json.dump({"state": "starting", "track": 0, "total": len(tracks),
                   "progress": 0, "message": "Avvio…"}, f)

    _run(["systemd-run", "--no-block", "--collect", "--unit=" + RIP_UNIT,
          RIP_SCRIPT, RIP_PLAN], timeout=10)
    threading.Thread(target=_rip_watcher, daemon=True, name="rip-watcher").start()
    return jsonify({"success": True, "total": len(tracks)}), 202


@app.route("/api/cd/rip/status", methods=["GET"])
def api_cd_rip_status():
    denied = _require_pair_token()
    if denied:
        return denied
    return jsonify(_rip_state())


@app.route("/api/cd/eject", methods=["POST"])
def api_cd_eject():
    denied = _require_pair_token()
    if denied:
        return denied
    if _rip_running():
        return _err("msg.ripInProgress", 409)
    r = _run(["eject", CD_DEVICE], timeout=20)
    return jsonify({"success": r.returncode == 0})


@app.route("/api/internal/smb", methods=["GET"])
def api_internal_smb():
    denied = _require_pair_token()
    if denied:
        return denied
    installed = _run(["which", "smbd"], timeout=5).returncode == 0
    enabled = False
    if installed:
        try:
            r = _run(["systemctl", "is-enabled", "smbd"], timeout=5)
            enabled = r.returncode == 0 or (r.stdout or "").strip() == "enabled"
        except Exception:
            pass
    shares = []
    for s in _adopted_disk_sources():
        shares.append({
            "name": s.get("share") or "Musica",
            "mountpoint": s.get("mountpoint"),
            "source_id": s.get("id"),
        })
    password = ""
    if os.path.exists(SAMBA_CRED_FILE):
        try:
            with open(SAMBA_CRED_FILE) as f:
                cred = json.load(f)
            password = cred.get("password", "")
        except Exception:
            pass
    ips = _ip_addresses()
    return jsonify({
        "installed": installed,
        "enabled": enabled,
        "shares": shares,
        "username": SAMBA_USER,
        "password": password,
        "host": "hifiplayer.local",
        "ip": ips[0] if ips else "",
    })


@app.route("/api/internal/smb/regenerate", methods=["POST"])
def api_internal_smb_regenerate():
    denied = _require_pair_token()
    if denied:
        return denied
    if _run(["which", "smbd"], timeout=5).returncode != 0:
        return _err("msg.sambaMissing", 424)
    with _lock:
        password = _create_samba_user(force_new_password=True)
    return jsonify({"success": True, "username": SAMBA_USER, "password": password})


@app.route("/api/usb", methods=["GET"])
def api_usb():
    """List currently-mounted USB disks and their top-level folders, so the UI
    can offer to add them as local sources."""
    denied = _require_pair_token()
    if denied:
        return denied
    # Serve the snapshot kept fresh by the background usb_monitor thread instead
    # of re-scanning on every poll. Only force a scan if none has run yet.
    wanted = _usb_state
    if wanted is None:
        try:
            wanted = usb_sync()
        except Exception:
            app.logger.exception("Failed to enumerate USB disks")
            return jsonify({"disks": [], "error": "Unable to enumerate USB disks."}), 500
    disks = []
    for mp, p in wanted.items():
        if not os.path.ismount(mp):
            continue
        folders = []
        try:
            for entry in sorted(os.listdir(mp)):
                full = os.path.join(mp, entry)
                if not entry.startswith(".") and os.path.isdir(full):
                    folders.append({"name": entry, "path": full})
        except Exception:
            pass
        disks.append({
            "label": p.get("label") or p.get("name"),
            "fstype": p.get("fstype"),
            "size": p.get("size"),
            "mountpoint": mp,
            "folders": folders,
            # Raw device node, used by the "use as source" (adopt) action —
            # already-adopted disks never appear here (see _usb_partitions()).
            "path": p.get("path"),
        })
    return jsonify({"disks": disks})


# ─────────────────────────── Web UI ─────────────────────────────────
# This page is the functional twin of the kiosk's SourcesManager.jsx +
# InternalDisks.jsx, and it is what the web admin embeds and what the setup
# wizard's QR code points a phone at. It used to be hardcoded Italian, so an
# English user got an Italian page in the middle of an otherwise translated
# setup. The catalog below deliberately reuses the *same key names and English
# wording* as src/i18n/locales/{en,it}.json (`sources.*`) — those JSONs are
# bundled into the Electron app by Vite and are not readable from here at
# runtime, so they are mirrored rather than shared. Keep the two in sync when
# either side changes wording.
SOURCES_I18N = {
    "en": {
        "sources.title": "Music sources",
        "sources.intro": "Add the folders that contain your music. When you are done, press Apply to update the library.",
        "sources.back": "Back",
        "sources.done": "Done",
        "sources.loading": "Loading…",
        "sources.active": "Active sources",
        "sources.none": "No sources yet. Add one below.",
        "sources.usbTitle": "USB disks",
        "sources.usbNone": "No USB disk connected. Insert a USB stick or drive.",
        "sources.usbAddWhole": "Add whole disk",
        "sources.usbFullHint": "\"Add whole disk\"/\"Add\" copy a folder once, read-only. \"Use as source\" gives read-write access and a network share (Samba), like an internal disk — no need to reformat the drive. It won't interrupt playback, but the new folder only joins the music library once you press \"Apply & rescan library\" below.",
        "sources.add": "Add",
        "sources.addLocal": "Add local folder",
        "sources.localPath": "Path on the device",
        "sources.localPathPlaceholder": "/media/music",
        "sources.addSmb": "Add network folder (SMB)",
        "sources.server": "Server / IP",
        "sources.share": "Share",
        "sources.sharePlaceholder": "Music",
        "sources.user": "User (empty = guest)",
        "sources.userPlaceholder": "user",
        "sources.pass": "Password",
        "sources.mountAndAdd": "Mount and add",
        "sources.mounting": "Mounting…",
        "sources.mounted": "Mounted ✓",
        "sources.added": "Added ✓",
        "sources.remove": "Remove",
        "sources.local": "LOCAL",
        "sources.smbTag": "SMB",
        "sources.mountedShort": "mounted",
        "sources.notMounted": "not mounted",
        "sources.ok": "ok",
        "sources.missing": "missing",
        "sources.error": "Error",
        "sources.networkError": "Network error",
        "sources.apply": "Apply & rescan library",
        "sources.applyHint": "Saves the sources above and rescans the music library.",
        "sources.applying": "Applying…",
        "sources.applied": "Done ✓",
        "sources.backupTitle": "Backup & restore",
        "sources.backupHint": "Save the device's configuration, Lyrion preferences and playlists. Set a passphrase to also include credentials (Wi-Fi, SMB shares, web-admin account) in an encrypted, restorable file — without one, only non-secret settings are saved.",
        "sources.backupPassphrase": "Passphrase (optional)",
        "sources.backupPassphraseHint": "Leave empty for a plain backup with no credentials. Set one to also save Wi-Fi networks, SMB passwords and the web-admin account, encrypted.",
        "sources.backupCreate": "Create backup",
        "sources.backupDownload": "⬇ Download now",
        "sources.backupRestore": "⬆ Restore from file",
        "sources.backupWorking": "Working…",
        "sources.backupStored": "Backups on this device",
        "sources.backupNone": "No backup yet.",
        "sources.backupEncrypted": "encrypted",
        "sources.backupRestoreThis": "Restore",
        "sources.backupRestoreConfirm": "Restore this backup? A safety copy of the current configuration is taken first.",
        "sources.backupDeleteConfirm": "Delete this backup? This cannot be undone.",
        "sources.backupScheduled": "Automatic weekly backup",
        "sources.backupScheduledHint": "Runs unattended, so it never includes credentials — only device settings, sources and Lyrion preferences/playlists.",
        "sources.restoring": "Restoring…",
        "sources.internal.title": "Internal disks",
        "sources.internal.none": "No additional internal disk detected.",
        "sources.internal.tag": "INTERNAL",
        "sources.internal.adopt": "Use as source",
        "sources.internal.use": "Use",
        "sources.internal.adopted": "Source added ✓",
        "sources.internal.adoptedBadge": "adopted",
        "sources.internal.adopting": "Mounting…",
        "sources.internal.hasData": "contains data",
        "sources.internal.remove": "Remove",
        "sources.internal.removed": "Removed ✓",
        "sources.internal.format": "Format…",
        "sources.internal.wizardTitle": "Format disk",
        "sources.internal.fsLabel": "Filesystem",
        "sources.internal.fsExt4": "ext4 (recommended)",
        "sources.internal.fsExfat": "exFAT",
        "sources.internal.labelField": "Disk label",
        "sources.internal.defaultLabel": "Music",
        "sources.internal.cancel": "Cancel",
        "sources.internal.next": "Next",
        "sources.internal.backStep": "Back",
        "sources.internal.warnTitle": "This will erase all data",
        "sources.internal.warnBody": "All data on {model} ({size}, {path}) will be permanently erased. This cannot be undone.",
        "sources.internal.typeToConfirm": "Type \"{label}\" to confirm",
        "sources.internal.formatNow": "Format now",
        "sources.internal.phasePreparing": "Preparing disk…",
        "sources.internal.inProgress": "In progress…",
        "sources.internal.keepPowered": "Keep the appliance powered on until this finishes.",
        "sources.internal.doneAdopted": "Disk formatted and added as a source ✓",
        "sources.internal.doneHint": "Copy your music to the network share below, then apply & rescan the library.",
        "sources.internal.errorTitle": "Error",
        "sources.internal.close": "Close",
        "sources.internal.needOsUpdate": "A system update is required to enable network sharing (Samba) for internal disks.",
        "sources.internal.smbTitle": "Network share",
        "sources.internal.smbHelp": "Copy music from a PC by connecting to this path with the credentials below.",
        "sources.internal.smbUser": "Username",
        "sources.internal.smbPass": "Password",
        "sources.internal.smbRegenerate": "Regenerate password",
        # ── API messages ────────────────────────────────────────────
        # Rendered verbatim by the kiosk's SourcesManager/InternalDisks, so an
        # Italian string here showed up in the middle of the English UI. Every
        # response also carries a stable `code`, so a client can translate on
        # its own side later without another backend change.
        "msg.noFile": "No file uploaded.",
        "msg.fileTooLarge": "File too large.",
        "msg.fileTooLarge20": "File too large (max 20 MB).",
        "msg.fileEmpty": "The file is empty.",
        "msg.saveFailed": "Could not save the file.",
        "msg.badFilterFormat": "Unsupported format (use .wav or .txt).",
        "msg.filterUploaded": "Filter uploaded. Enable it in Settings → DSP.",
        "msg.notAllowedRemotely": "Not allowed from a remote connection.",
        "msg.tooManyAttempts": "Too many attempts, try again in a few minutes.",
        "msg.badPairToken": "Missing or invalid pairing token.",
        "msg.dspUnavailable": "The DSP service is unavailable.",
        "msg.dspUnreachable": "The DSP service is unreachable.",
        "msg.pathMissing": "Path missing.",
        "msg.pathNotAllowed": "This path is not allowed.",
        "msg.folderMissing": "The folder {path} does not exist.",
        "msg.smbFieldsRequired": "Server and share name are required.",
        "msg.mountFailed": "Mount failed: {detail}",
        "msg.badDevice": "Invalid device.",
        "msg.diskNotFound": "Disk not found, or it is a system disk.",
        "msg.pickPartition": "Select a partition that has a filesystem.",
        "msg.partitionNoFs": "That partition has no filesystem.",
        "msg.unsupportedFs": "Unsupported filesystem.",
        "msg.badLabel": "Invalid disk label.",
        "msg.labelTooLongExfat": "Label too long for exFAT (max 11 characters).",
        "msg.confirmMismatch": "The confirmation does not match.",
        "msg.alreadyAdopted": "This disk is already used as a source.",
        "msg.unmountFirst": "The disk is mounted — unmount it first.",
        "msg.osUpdateForExfat": "An OS update is required to format as exFAT.",
        "msg.formatInProgress": "A format is already running.",
        "msg.noAudioCd": "No audio CD in the drive.",
        "msg.ripInProgress": "A rip is already running.",
        "msg.noWritableTarget": "No writable destination: adopt an internal disk first.",
        "msg.sambaMissing": "Samba is not installed.",
    },
    "it": {
        "sources.title": "Sorgenti musicali",
        "sources.intro": "Aggiungi le cartelle che contengono la tua musica. Al termine premi Applica per aggiornare la libreria.",
        "sources.back": "Indietro",
        "sources.done": "Fatto",
        "sources.loading": "Caricamento…",
        "sources.active": "Sorgenti attive",
        "sources.none": "Nessuna sorgente. Aggiungine una qui sotto.",
        "sources.usbTitle": "Dischi USB",
        "sources.usbNone": "Nessun disco USB collegato. Inserisci una chiavetta o un hard disk USB.",
        "sources.usbAddWhole": "Aggiungi tutto il disco",
        "sources.usbFullHint": "\"Aggiungi tutto il disco\"/\"Aggiungi\" copiano una cartella una sola volta, in sola lettura. \"Usa come sorgente\" dà accesso in lettura/scrittura e una condivisione di rete (Samba), come un disco interno — senza bisogno di formattare il disco. Non interrompe la riproduzione, ma la nuova cartella entra nella libreria musicale solo dopo aver premuto \"Applica e scansiona libreria\" qui sotto.",
        "sources.add": "Aggiungi",
        "sources.addLocal": "Aggiungi cartella locale",
        "sources.localPath": "Percorso sul dispositivo",
        "sources.localPathPlaceholder": "/media/musica",
        "sources.addSmb": "Aggiungi cartella di rete (SMB)",
        "sources.server": "Server / IP",
        "sources.share": "Condivisione",
        "sources.sharePlaceholder": "Musica",
        "sources.user": "Utente (vuoto = ospite)",
        "sources.userPlaceholder": "utente",
        "sources.pass": "Password",
        "sources.mountAndAdd": "Monta e aggiungi",
        "sources.mounting": "Montaggio…",
        "sources.mounted": "Montata ✓",
        "sources.added": "Aggiunta ✓",
        "sources.remove": "Rimuovi",
        "sources.local": "LOCALE",
        "sources.smbTag": "SMB",
        "sources.mountedShort": "montato",
        "sources.notMounted": "non montato",
        "sources.ok": "ok",
        "sources.missing": "mancante",
        "sources.error": "Errore",
        "sources.networkError": "Errore di rete",
        "sources.apply": "Applica e scansiona libreria",
        "sources.applyHint": "Salva le sorgenti qui sopra e riscansiona la libreria musicale.",
        "sources.applying": "Applico…",
        "sources.applied": "Fatto ✓",
        "sources.backupTitle": "Backup e ripristino",
        "sources.backupHint": "Salva la configurazione del dispositivo, le preferenze e le playlist di Lyrion. Imposta una passphrase per includere anche le credenziali (Wi-Fi, condivisioni SMB, account web-admin) in un file cifrato e ripristinabile — senza, viene salvato solo ciò che non è segreto.",
        "sources.backupPassphrase": "Passphrase (opzionale)",
        "sources.backupPassphraseHint": "Lascia vuoto per un backup semplice senza credenziali. Impostane una per salvare anche reti Wi-Fi, password SMB e account web-admin, cifrati.",
        "sources.backupCreate": "Crea backup",
        "sources.backupDownload": "⬇ Scarica ora",
        "sources.backupRestore": "⬆ Ripristina da file",
        "sources.backupWorking": "In corso…",
        "sources.backupStored": "Backup su questo dispositivo",
        "sources.backupNone": "Nessun backup ancora.",
        "sources.backupEncrypted": "cifrato",
        "sources.backupRestoreThis": "Ripristina",
        "sources.backupRestoreConfirm": "Ripristinare questo backup? Verrà creata prima una copia di sicurezza della configurazione attuale.",
        "sources.backupDeleteConfirm": "Eliminare questo backup? L'operazione non è reversibile.",
        "sources.backupScheduled": "Backup automatico settimanale",
        "sources.backupScheduledHint": "Viene eseguito senza supervisione, quindi non include mai credenziali — solo impostazioni del dispositivo, sorgenti e preferenze/playlist di Lyrion.",
        "sources.restoring": "Ripristino…",
        "sources.internal.title": "Dischi interni",
        "sources.internal.none": "Nessun disco interno aggiuntivo rilevato.",
        "sources.internal.tag": "INTERNO",
        "sources.internal.adopt": "Usa come sorgente",
        "sources.internal.use": "Usa",
        "sources.internal.adopted": "Sorgente aggiunta ✓",
        "sources.internal.adoptedBadge": "adottato",
        "sources.internal.adopting": "Montaggio…",
        "sources.internal.hasData": "dati presenti",
        "sources.internal.remove": "Rimuovi",
        "sources.internal.removed": "Rimossa ✓",
        "sources.internal.format": "Formatta…",
        "sources.internal.wizardTitle": "Formatta disco",
        "sources.internal.fsLabel": "Filesystem",
        "sources.internal.fsExt4": "ext4 (consigliato)",
        "sources.internal.fsExfat": "exFAT",
        "sources.internal.labelField": "Etichetta disco",
        "sources.internal.defaultLabel": "Musica",
        "sources.internal.cancel": "Annulla",
        "sources.internal.next": "Avanti",
        "sources.internal.backStep": "Indietro",
        "sources.internal.warnTitle": "Questa operazione cancella tutti i dati",
        "sources.internal.warnBody": "Tutti i dati su {model} ({size}, {path}) verranno cancellati in modo permanente. L'operazione non può essere annullata.",
        "sources.internal.typeToConfirm": "Digita \"{label}\" per confermare",
        "sources.internal.formatNow": "Formatta ora",
        "sources.internal.phasePreparing": "Preparazione disco…",
        "sources.internal.inProgress": "In corso…",
        "sources.internal.keepPowered": "Tieni acceso l'apparecchio finché l'operazione non termina.",
        "sources.internal.doneAdopted": "Disco formattato e aggiunto come sorgente ✓",
        "sources.internal.doneHint": "Copia la musica nella condivisione di rete qui sotto, poi applica e riscansiona la libreria.",
        "sources.internal.errorTitle": "Errore",
        "sources.internal.close": "Chiudi",
        "sources.internal.needOsUpdate": "È necessario un aggiornamento di sistema per abilitare la condivisione di rete (Samba) dei dischi interni.",
        "sources.internal.smbTitle": "Condivisione di rete",
        "sources.internal.smbHelp": "Copia la musica da un PC collegandoti a questo percorso con le credenziali qui sotto.",
        "sources.internal.smbUser": "Utente",
        "sources.internal.smbPass": "Password",
        "sources.internal.smbRegenerate": "Rigenera password",
        # ── Messaggi API (vedi il blocco inglese) ───────────────────
        "msg.noFile": "Nessun file caricato.",
        "msg.fileTooLarge": "File troppo grande.",
        "msg.fileTooLarge20": "File troppo grande (max 20 MB).",
        "msg.fileEmpty": "Il file è vuoto.",
        "msg.saveFailed": "Salvataggio fallito.",
        "msg.badFilterFormat": "Formato non supportato (usa .wav o .txt).",
        "msg.filterUploaded": "Filtro caricato. Attivalo da Impostazioni → DSP.",
        "msg.notAllowedRemotely": "Non consentito da remoto.",
        "msg.tooManyAttempts": "Troppi tentativi, riprova tra qualche minuto.",
        "msg.badPairToken": "Token di pairing mancante o non valido.",
        "msg.dspUnavailable": "Servizio DSP non disponibile.",
        "msg.dspUnreachable": "Servizio DSP non raggiungibile.",
        "msg.pathMissing": "Percorso mancante.",
        "msg.pathNotAllowed": "Percorso non consentito.",
        "msg.folderMissing": "La cartella {path} non esiste.",
        "msg.smbFieldsRequired": "Server e nome condivisione obbligatori.",
        "msg.mountFailed": "Mount fallito: {detail}",
        "msg.badDevice": "Device non valido.",
        "msg.diskNotFound": "Disco non trovato o di sistema.",
        "msg.pickPartition": "Seleziona una partizione con filesystem.",
        "msg.partitionNoFs": "Partizione senza filesystem.",
        "msg.unsupportedFs": "Filesystem non supportato.",
        "msg.badLabel": "Etichetta non valida.",
        "msg.labelTooLongExfat": "Etichetta troppo lunga per exFAT (max 11 caratteri).",
        "msg.confirmMismatch": "Conferma non corrispondente.",
        "msg.alreadyAdopted": "Disco già adottato come sorgente.",
        "msg.unmountFirst": "Disco montato, smontalo prima.",
        "msg.osUpdateForExfat": "Aggiornamento OS richiesto per formattare exFAT.",
        "msg.formatInProgress": "Formattazione già in corso.",
        "msg.noAudioCd": "Nessun CD audio nel lettore.",
        "msg.ripInProgress": "Rip già in corso.",
        "msg.noWritableTarget": "Nessuna destinazione scrivibile: adotta un disco interno.",
        "msg.sambaMissing": "Samba non installato.",
    },
}
DEFAULT_LANG = "en"


def _req_lang():
    """Language for this request: explicit ?lang= wins (the web admin and the
    kiosk QR both pass their own), then the browser's Accept-Language, then the
    appliance default. Mirrors how src/i18n/index.jsx picks a locale."""
    lang = (request.args.get("lang") or "").strip().lower()[:2]
    if lang in SOURCES_I18N:
        return lang
    header = request.headers.get("Accept-Language", "")
    for part in header.split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in SOURCES_I18N:
            return code
    return DEFAULT_LANG


def _t(key, lang=None, **vars):
    """Translate `key`, falling back to the default language and then to the key
    itself, with {placeholder} interpolation."""
    lang = lang or DEFAULT_LANG
    table = SOURCES_I18N.get(lang) or SOURCES_I18N[DEFAULT_LANG]
    text = table.get(key) or SOURCES_I18N[DEFAULT_LANG].get(key) or key
    for k, v in vars.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def _m(key, **vars):
    """Translate an API message in the caller's language. Safe to call from a
    worker thread with no request context, where it falls back to the default."""
    try:
        lang = _req_lang()
    except Exception:
        lang = DEFAULT_LANG
    return _t(key, lang, **vars)


def _err(key, status, **vars):
    """Standard failure body: a stable `code` for clients that translate on
    their own, plus a `message` already in the caller's language for those
    (the kiosk, the companion app) that render it verbatim."""
    return jsonify({"success": False, "code": key, "message": _m(key, **vars)}), status


@app.route("/")
def index():
    # Gate the page itself, not just the API calls it makes: without this, any
    # device on the LAN could load this page directly (bypassing the webui:443
    # session and the companion app's pairing flow entirely) and get the full
    # Sources UI. Loopback (Electron kiosk, webui's own proxied requests) and
    # a valid ?token= (the QR-carried phone flow, and webui's minted token —
    # see sources_app() in webui_server.py) still get through, matching
    # _require_pair_token()'s existing exemptions.
    denied = _require_pair_token()
    if denied:
        return denied
    lang = _req_lang()
    # Only the page's own strings are shipped to the browser; the msg.* half of
    # the catalog is server-side only.
    strings = {k: v for k, v in SOURCES_I18N[lang].items() if k.startswith("sources.")}
    # Reached mid first-boot setup (webui_server.py's captive page links here
    # with ?setup=1): Lyrion's own setup wizard performs the real first scan
    # right after, so "Apply & rescan library" is misleading/redundant here —
    # swap in setup-appropriate copy for just these two strings, in whichever
    # language is active. Overriding this local dict (not SOURCES_I18N itself)
    # leaves the normal Settings -> Sources page's wording untouched.
    if request.args.get("setup") == "1":
        strings["sources.apply"] = {"en": "Save sources", "it": "Salva sorgenti"}.get(lang, "Save sources")
        strings["sources.applyHint"] = {
            "en": "Saves the sources above. Lyrion's own setup wizard scans your library once you finish setup.",
            "it": "Salva le sorgenti qui sopra. La scansione della libreria la esegue il setup wizard di Lyrion una volta terminata la configurazione.",
        }.get(lang, strings["sources.applyHint"])
    html = (INDEX_HTML
            .replace("__LANG__", lang)
            .replace("__PAGE_TITLE__", _t("sources.title", lang))
            .replace("__I18N__", json.dumps(strings, ensure_ascii=False)))
    return Response(html, mimetype="text/html")


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Osmium Sound — __PAGE_TITLE__</title>
<style>
  :root { --gold:#d4af37; --bg:#0a0a0a; --surface:#161616; --border:#252525; --silver:#c0c0c0; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:-apple-system,Segoe UI,Roboto,sans-serif; background:var(--bg); color:#fff; }
  .wrap { max-width:640px; margin:0 auto; padding:24px 16px 64px; }
  h1 { font-size:20px; display:flex; align-items:center; gap:8px; }
  h1 .dot { width:10px; height:10px; border-radius:50%; background:var(--gold); box-shadow:0 0 8px var(--gold); }
  h2 { font-size:14px; color:var(--silver); text-transform:uppercase; letter-spacing:.08em; margin:28px 0 10px; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:14px; padding:16px; margin-bottom:12px; }
  label { display:block; font-size:12px; color:var(--silver); margin:8px 0 4px; }
  input { width:100%; background:var(--bg); border:1px solid var(--border); color:#fff; border-radius:10px; padding:11px 12px; font-size:15px; }
  input:focus { outline:none; border-color:var(--gold); }
  button { border:0; border-radius:10px; padding:11px 16px; font-weight:600; font-size:14px; cursor:pointer; }
  .primary { background:var(--gold); color:#000; }
  .ghost { background:rgba(255,255,255,.06); color:#fff; }
  .danger { background:transparent; color:#e66; border:1px solid rgba(238,102,102,.4); }
  .row { display:flex; gap:10px; align-items:center; justify-content:space-between; }
  .src { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:12px 0; border-bottom:1px solid var(--border); }
  .src:last-child { border-bottom:0; }
  .src .meta { min-width:0; }
  .src .name { font-size:14px; word-break:break-all; }
  .src .sub { font-size:12px; color:var(--silver); }
  .tag { font-size:10px; padding:2px 7px; border-radius:6px; background:rgba(212,175,55,.15); color:var(--gold); margin-left:6px; }
  .ok { color:#5fce8f; } .bad { color:#e66; }
  .msg { margin-top:10px; font-size:13px; min-height:18px; }
  .applybar { position:fixed; left:0; right:0; bottom:0; background:#0d0d0dee; backdrop-filter:blur(8px); border-top:1px solid var(--border); padding:10px 16px 12px; }
  .applybar .inner { max-width:640px; margin:0 auto; }
  .applybar .hint { font-size:12px; color:var(--silver); margin:0 0 8px; }
  .applybar .actions { display:flex; gap:10px; align-items:center; }
  .topbar { position:sticky; top:0; z-index:50; background:#0d0d0dee; backdrop-filter:blur(8px); border-bottom:1px solid var(--border); padding:10px 16px; }
  .topbar .inner { max-width:640px; margin:0 auto; display:flex; gap:12px; align-items:center; }
  .topbar a { color:var(--gold); text-decoration:none; font-size:14px; font-weight:600; }
  .topbar .ttl { font-size:14px; color:var(--silver); }
</style>
</head>
<body>
<!-- Shown only when there is somewhere to go back TO: a ?back= target passed by
     the embedder, or ordinary browser history (a phone that scanned the setup
     wizard's QR lands here with neither, and gets no dead-end button). -->
<div class="topbar" id="topbar" style="display:none"><div class="inner">
  <a href="#" id="backLink" onclick="goBack();return false">← <span data-i18n="sources.back"></span></a>
  <span class="ttl" data-i18n="sources.title"></span>
</div></div>

<div class="wrap">
  <h1><span class="dot"></span> <span data-i18n="sources.title"></span></h1>
  <p style="color:var(--silver);font-size:14px" data-i18n="sources.intro"></p>

  <h2 data-i18n="sources.active"></h2>
  <div class="card" id="list"><div style="color:var(--silver);font-size:14px" data-i18n="sources.loading"></div></div>

  <h2 data-i18n="sources.usbTitle"></h2>
  <div class="card" id="usbList"><div style="color:var(--silver);font-size:14px" data-i18n="sources.usbNone"></div></div>

  <h2 data-i18n="sources.internal.title"></h2>
  <div class="card" id="internalList"><div style="color:var(--silver);font-size:14px" data-i18n="sources.loading"></div></div>
  <div class="msg" id="internalMsg"></div>

  <h2 data-i18n="sources.addLocal"></h2>
  <div class="card">
    <label data-i18n="sources.localPath"></label>
    <input id="localPath" data-i18n-ph="sources.localPathPlaceholder">
    <div style="height:10px"></div>
    <button class="ghost" onclick="addLocal()" data-i18n="sources.addLocal"></button>
    <div class="msg" id="localMsg"></div>
  </div>

  <h2 data-i18n="sources.addSmb"></h2>
  <div class="card">
    <div class="row"><div style="flex:1"><label data-i18n="sources.server"></label><input id="smbServer" placeholder="192.168.0.20"></div>
    <div style="flex:1"><label data-i18n="sources.share"></label><input id="smbShare" data-i18n-ph="sources.sharePlaceholder"></div></div>
    <div class="row"><div style="flex:1"><label data-i18n="sources.user"></label><input id="smbUser" data-i18n-ph="sources.userPlaceholder"></div>
    <div style="flex:1"><label data-i18n="sources.pass"></label><input id="smbPass" type="password" placeholder="••••••"></div></div>
    <div style="height:12px"></div>
    <button class="ghost" onclick="addSmb()" data-i18n="sources.mountAndAdd"></button>
    <div class="msg" id="smbMsg"></div>
  </div>

  <div id="backupSection">
  <h2 data-i18n="sources.backupTitle"></h2>
  <div class="card">
    <p style="color:var(--silver);font-size:13px;margin:0 0 10px" data-i18n="sources.backupHint"></p>

    <label data-i18n="sources.backupPassphrase"></label>
    <input id="backupPass" type="password" placeholder="••••••">
    <p style="color:var(--silver);font-size:12px;margin:6px 0 12px" data-i18n="sources.backupPassphraseHint"></p>

    <div class="row">
      <button class="ghost" style="flex:1" onclick="createBackup()" data-i18n="sources.backupCreate"></button>
      <a id="backupLink" class="ghost" style="text-decoration:none;display:inline-block;text-align:center;flex:1" href="/api/backup" data-i18n="sources.backupDownload"></a>
      <label class="ghost" style="text-align:center;flex:1;cursor:pointer" for="restoreFile" data-i18n="sources.backupRestore"></label>
    </div>
    <input type="file" id="restoreFile" accept=".gz,.tar.gz,application/gzip" style="display:none" onchange="doRestore(this)">
    <div class="msg" id="restoreMsg"></div>

    <div style="height:14px"></div>
    <label data-i18n="sources.backupStored"></label>
    <div id="backupList" style="font-size:13px;color:var(--silver)" data-i18n="sources.loading"></div>

    <div style="height:14px"></div>
    <div class="row">
      <span style="font-size:13px" data-i18n="sources.backupScheduled"></span>
      <input type="checkbox" id="backupSched" style="width:auto" onchange="saveBackupSettings()">
    </div>
    <p style="color:var(--silver);font-size:12px;margin:6px 0 0" data-i18n="sources.backupScheduledHint"></p>
  </div>
  </div>
</div>

<!-- The gold button is an ACTION, not a counter: the caption says what it does,
     and when there is a way back a second button makes the bar read as a pair
     of choices rather than a status readout. -->
<div class="applybar"><div class="inner">
  <p class="hint" data-i18n="sources.applyHint"></p>
  <div class="actions">
    <button class="primary" style="flex:1" onclick="apply()" data-i18n="sources.apply"></button>
    <button class="ghost" id="doneBtn" style="display:none" onclick="goBack()" data-i18n="sources.done"></button>
    <span class="msg" id="applyMsg" style="margin:0"></span>
  </div>
</div></div>

<script>
// A remote (non-localhost) visit — the "scan the QR from Settings → Backup e
// ripristino, no companion app needed" flow — carries a pairing token in the
// URL (?token=...), minted server-side when that QR was generated. Attach it
// to every call this page makes so /api/* routes that now require pairing
// (see _require_pair_token()) keep working from a plain phone/PC browser,
// not just from the Electron kiosk (which is exempt via 127.0.0.1).
const QS = new URLSearchParams(location.search);
const PAIR_TOKEN = QS.get('token') || '';
const LANG = document.documentElement.lang || 'it';
// Reached mid first-boot setup (webui_server.py's captive page links here
// with ?setup=1): backup/restore doesn't belong here — the wizard already
// asked "restore from backup or start fresh" as its very first step, before
// this page even exists — and Apply shouldn't force an immediate Lyrion
// restart/scan, since the wizard applies the final source list itself, once,
// right before handing off to Lyrion's own setup wizard.
const SETUP_MODE = QS.get('setup') === '1';
if (SETUP_MODE) {
  const bs = document.getElementById('backupSection');
  if (bs) bs.style.display = 'none';
}

// ── i18n ────────────────────────────────────────────────────────────
// Strings for the selected language are injected server-side (see _req_lang);
// T() mirrors the {placeholder} interpolation of src/i18n/index.jsx.
const I18N = __I18N__;
function T(key, vars){
  let s = I18N[key] != null ? I18N[key] : key;
  if (vars) for (const k in vars) s = s.split('{'+k+'}').join(vars[k]);
  return s;
}
function applyI18n(root){
  (root||document).querySelectorAll('[data-i18n]').forEach(el=>{
    el.textContent = T(el.getAttribute('data-i18n'));
  });
  (root||document).querySelectorAll('[data-i18n-ph]').forEach(el=>{
    el.setAttribute('placeholder', T(el.getAttribute('data-i18n-ph')));
  });
}
applyI18n();

// ── navigation back to whatever embedded/linked us ──────────────────
const BACK_TO = QS.get('back') || '';
// When embedded (web admin Settings/Setup) the surrounding page already owns
// navigation, and history.length reflects the whole tab's joint session
// history — so it would light up a back bar that both looks wrong inside the
// frame and would navigate somewhere unexpected. Only an embedder that asks
// for it explicitly, via ?back=, gets one.
const FRAMED = window.self !== window.top;
function goBack(){
  if (BACK_TO) { location.href = BACK_TO; return; }
  if (history.length > 1) { history.back(); return; }
  location.href = '/';
}
if (BACK_TO || (!FRAMED && history.length > 1)) {
  document.getElementById('topbar').style.display = '';
  document.getElementById('doneBtn').style.display = '';
  if (BACK_TO) document.getElementById('backLink').href = BACK_TO;
}

async function j(url, opts){
  opts = opts || {};
  if (PAIR_TOKEN) {
    opts.headers = Object.assign({}, opts.headers, {'Authorization': 'Bearer ' + PAIR_TOKEN});
  }
  // Backend messages are translated per request, so every call carries the
  // language this page is rendered in.
  const sep = url.indexOf('?') >= 0 ? '&' : '?';
  const r=await fetch(url + sep + 'lang=' + encodeURIComponent(LANG), opts); return r.json();
}
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
// Plain <a href> navigation cannot set an Authorization header, so download
// links carry the pairing token in the query string instead — same fallback
// _require_pair_token() accepts for exactly this reason.
function withToken(url){
  return PAIR_TOKEN ? (url + (url.indexOf('?')>=0?'&':'?') + 'token=' + encodeURIComponent(PAIR_TOKEN)) : url;
}
if (PAIR_TOKEN) {
  document.getElementById('backupLink').href = withToken('/api/backup');
}
async function load(){
  const d=await j('/api/sources');
  const el=document.getElementById('list');
  if(!d.sources.length){ el.innerHTML=`<div style="color:var(--silver);font-size:14px">${esc(T('sources.none'))}</div>`; return; }
  el.innerHTML=d.sources.map(s=>{
            const isSmb=s.type==='smb';
    const isInternal=s.type==='internal';
    const isUsb=s.type==='usb';
    const mountState=s.mounted?`<span class="ok">${esc(T('sources.mountedShort'))}</span>`
                              :`<span class="bad">${esc(T('sources.notMounted'))}</span>`;
    const status=(isSmb||isInternal||isUsb)?mountState
                      :(s.exists?`<span class="ok">${esc(T('sources.ok'))}</span>`
                                :`<span class="bad">${esc(T('sources.missing'))}</span>`);
    const sub=isSmb?('//'+esc(s.server)+'/'+esc(s.share)+' → '+esc(s.mountpoint))
              :(isInternal||isUsb)?(esc(s.mountpoint||s.path||''))
              :esc(s.path);
    const tag=isSmb?T('sources.smbTag'):isInternal?T('sources.internal.tag'):isUsb?'USB':T('sources.local');
    return `<div class="src"><div class="meta"><div class="name">${esc(s.name)}<span class="tag">${esc(tag)}</span></div>
      <div class="sub">${sub} · ${status}</div></div>
      <button class="danger" onclick="rm('${s.id}')">${esc(T('sources.remove'))}</button></div>`;
  }).join('');
}
async function addLocal(){
  const path=document.getElementById('localPath').value.trim();
  const m=document.getElementById('localMsg'); m.textContent='…';
  const r=await j('/api/sources/local',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  m.textContent=r.success?T('sources.added'):(r.message||T('sources.error')); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){document.getElementById('localPath').value='';load();}
}
async function addSmb(){
  const body={server:smbServer.value,share:smbShare.value,username:smbUser.value,password:smbPass.value};
  const m=document.getElementById('smbMsg'); m.textContent=T('sources.mounting');
  const r=await j('/api/sources/smb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  m.textContent=r.success?(T('sources.mounted')+' '+(r.message||'')):(r.message||T('sources.error')); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){smbPass.value='';load();}
}
async function rm(id){ await j('/api/sources/'+id,{method:'DELETE'}); load(); }

// ── Backup / restore ───────────────────────────────────────────────
// The passphrase field is the single switch that decides whether credentials
// (Wi-Fi PSKs, SMB passwords, the admin account) are in the archive at all —
// filled in means encrypted and complete, empty means plain and non-secret.
// It is never stored anywhere: it is sent with the request that needs it and
// forgotten.
let backupGens=[];
function backupPass(){ return document.getElementById('backupPass').value||''; }

async function doRestore(input){
  const file=input.files && input.files[0]; if(!file) return;
  const m=document.getElementById('restoreMsg'); m.textContent=T('sources.restoring'); m.className='msg';
  const body=new FormData(); body.append('file', file);
  if(backupPass()) body.append('passphrase', backupPass());
  try{
    const d=await j('/api/restore',{method:'POST',body});
    if(d.success===false){ m.textContent=d.message||T('sources.error'); m.className='msg bad'; input.value=''; return; }
    await pollRestore();
    load();
  }catch(e){ m.textContent=T('sources.networkError'); m.className='msg bad'; }
  input.value='';
}

// Same poll-a-status-file shape as pollBackup() — restore runs in a
// background thread on the appliance precisely so this can show what step
// it's actually on (stopping Lyrion, writing files, restarting services)
// instead of a single "restoring..." message that looks identical whether
// it's working or stuck.
async function pollRestore(){
  const m=document.getElementById('restoreMsg');
  for(let i=0;i<600;i++){
    await new Promise(r=>setTimeout(r,1500));
    let s; try{ s=await j('/api/restore/status'); }catch(e){ continue; }
    if(s.state==='done'){ m.textContent=s.message||T('sources.applied'); m.className='msg ok'; loadBackups(); return; }
    if(s.state==='error'){ m.textContent=s.message||T('sources.error'); m.className='msg bad'; loadBackups(); return; }
    m.textContent=(s.message||T('sources.restoring'))+(typeof s.progress==='number'?' '+s.progress+'%':'');
  }
}

async function createBackup(){
  const m=document.getElementById('restoreMsg'); m.textContent=T('sources.backupWorking'); m.className='msg';
  try{
    const d=await j('/api/backup/create',{method:'POST',headers:{'Content-Type':'application/json'},
                                          body:JSON.stringify({passphrase:backupPass()})});
    if(d.success===false){ m.textContent=d.message||T('sources.error'); m.className='msg bad'; return; }
    pollBackup();
  }catch(e){ m.textContent=T('sources.networkError'); m.className='msg bad'; }
}

// Same poll-a-status-file shape as the disk format and CD rip jobs.
async function pollBackup(){
  const m=document.getElementById('restoreMsg');
  for(let i=0;i<600;i++){
    await new Promise(r=>setTimeout(r,1500));
    let s; try{ s=await j('/api/backup/status'); }catch(e){ continue; }
    if(s.state==='done'){ m.textContent=s.message||T('sources.applied'); m.className='msg ok'; loadBackups(); return; }
    if(s.state==='error'){ m.textContent=s.message||T('sources.error'); m.className='msg bad'; loadBackups(); return; }
    m.textContent=(s.message||T('sources.backupWorking'))+' '+(s.progress||0)+'%';
  }
}

function fmtBackupSize(n){
  if(!n) return '';
  return n>=1048576 ? (n/1048576).toFixed(1)+' MB' : Math.max(1,Math.round(n/1024))+' kB';
}
function fmtStamp(id){
  // Generation ids are YYYYMMDD-HHMMSS, which is unreadable as-is.
  if(!id||id.length<15) return id||'';
  return id.slice(6,8)+'/'+id.slice(4,6)+'/'+id.slice(0,4)+' '+id.slice(9,11)+':'+id.slice(11,13);
}

async function loadBackups(){
  const el=document.getElementById('backupList');
  let d; try{ d=await j('/api/backup/list'); }catch(e){ el.textContent=T('sources.networkError'); return; }
  backupGens=d.generations||[];
  document.getElementById('backupSched').checked=!!(d.settings&&d.settings.scheduled);
  if(!backupGens.length){ el.textContent=T('sources.backupNone'); return; }
  el.innerHTML=backupGens.map((g,i)=>{
    const tags=[];
    if(g.encrypted) tags.push(`<span class="tag">${esc(T('sources.backupEncrypted'))}</span>`);
    if(g.trigger&&g.trigger!=='manual') tags.push(`<span class="tag">${esc(g.trigger)}</span>`);
    return `<div class="src"><div class="meta">`+
      `<div class="name">${esc(fmtStamp(g.id))}${tags.join('')}</div>`+
      `<div class="sub">${esc((g.categories||[]).join(', '))} · ${esc(fmtBackupSize(g.size))}</div>`+
      `</div><div style="display:flex;gap:6px">`+
      `<a class="ghost" style="text-decoration:none" href="${esc(withToken('/api/backup/'+g.id))}">⬇</a>`+
      `<button class="ghost" onclick="restoreGen(${i})">${esc(T('sources.backupRestoreThis'))}</button>`+
      `<button class="ghost" onclick="deleteGen(${i})">✕</button>`+
      `</div></div>`;
  }).join('');
}

async function restoreGen(i){
  const g=backupGens[i]; if(!g) return;
  if(!confirm(T('sources.backupRestoreConfirm'))) return;
  const m=document.getElementById('restoreMsg'); m.textContent=T('sources.restoring'); m.className='msg';
  try{
    const d=await j('/api/backup/'+g.id+'/restore',{method:'POST',headers:{'Content-Type':'application/json'},
                                                    body:JSON.stringify({passphrase:backupPass()})});
    if(d.success===false){ m.textContent=d.message||T('sources.error'); m.className='msg bad'; return; }
    await pollRestore();
    load();
  }catch(e){ m.textContent=T('sources.networkError'); m.className='msg bad'; }
}

async function deleteGen(i){
  const g=backupGens[i]; if(!g) return;
  if(!confirm(T('sources.backupDeleteConfirm'))) return;
  await j('/api/backup/'+g.id,{method:'DELETE'});
  loadBackups();
}

async function saveBackupSettings(){
  const on=document.getElementById('backupSched').checked;
  const m=document.getElementById('restoreMsg');
  try{
    const d=await j('/api/backup/settings',{method:'POST',headers:{'Content-Type':'application/json'},
                                            body:JSON.stringify({scheduled:on})});
    m.textContent=d.success===false?(d.message||T('sources.error')):T('sources.applied');
    m.className='msg '+(d.success===false?'bad':'ok');
  }catch(e){ m.textContent=T('sources.networkError'); m.className='msg bad'; }
}
async function apply(){
  const m=document.getElementById('applyMsg');
  if (SETUP_MODE) {
    // Sources are already persisted by each add/remove call above — what
    // /api/apply additionally does is push mediadirs into Lyrion's prefs and
    // restart it, which is also what triggers Lyrion's own scan-on-restart.
    // The wizard does that exactly once, right before handing off to
    // Lyrion's own setup wizard, so it isn't duplicated here.
    m.textContent=T('sources.applied'); m.className='msg ok';
    return;
  }
  m.textContent=T('sources.applying'); m.className='msg';
  const r=await j('/api/apply',{method:'POST'});
  m.textContent=r.message||(r.success?T('sources.applied'):T('sources.error')); m.className='msg '+(r.success?'ok':'bad');
}

// ── USB disks ───────────────────────────────────────────────────────
// Paths are kept in an array and referenced by index in onclick handlers, so a
// folder name with quotes/specials can never break the markup.
let usbPaths=[];
let usbDevices=[];
async function loadUsb(){
  let d; try{ d=await j('/api/usb'); }catch(e){ return; }
  const el=document.getElementById('usbList'); usbPaths=[]; usbDevices=[];
  if(!d.disks || !d.disks.length){
    el.innerHTML=`<div style="color:var(--silver);font-size:14px">${esc(T('sources.usbNone'))}</div>`;
    return;
  }
  const hint=`<p style="color:var(--silver);opacity:.7;font-size:12px;margin:0 0 10px">${esc(T('sources.usbFullHint'))}</p>`;
  el.innerHTML=hint+d.disks.map(dk=>{
    const di=usbPaths.push(dk.mountpoint)-1;
    const devi=usbDevices.push(dk.path||'')-1;
    const tag=`USB${dk.fstype?(' '+esc(dk.fstype)):''}${dk.size?(' · '+esc(dk.size)):''}`;
    const head=`<div class="name">${esc(dk.label)||'USB'}<span class="tag">${tag}</span></div><div class="sub">${esc(dk.mountpoint)}</div>`;
    const all=`<button class="ghost" onclick="addUsb(${di})">${esc(T('sources.usbAddWhole'))}</button>`;
    const adopt=dk.path?`<button class="ghost" onclick="adoptUsb(${devi})">${esc(T('sources.internal.adopt'))}</button>`:'';
    const fold=(dk.folders||[]).map(f=>{
      const i=usbPaths.push(f.path)-1;
      return `<div class="src"><div class="meta"><div class="sub">📁 ${esc(f.name)}</div></div><button class="ghost" onclick="addUsb(${i})">${esc(T('sources.add'))}</button></div>`;
    }).join('');
    return `<div style="margin-bottom:14px">${head}<div style="height:8px"></div><div class="row" style="gap:8px">${all}${adopt}</div>${fold?('<div style="height:8px"></div>'+fold):''}</div>`;
  }).join('');
}
async function addUsb(i){
  const path=usbPaths[i]; if(!path) return;
  const r=await j('/api/sources/local',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  if(r.success){ load(); } else { alert(r.message||T('sources.error')); }
}
async function adoptUsb(i){
  const device=usbDevices[i]; if(!device) return;
  const r=await j('/api/usb/adopt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device})});
  if(r.success){ loadUsb(); load(); } else { alert(r.message||T('sources.error')); }
}

// ── Internal disks (adopt existing filesystem / format) ─────────────
// Mirrors the kiosk's InternalDisks.jsx: enumerate non-USB/non-system block
// devices, adopt an existing filesystem as a source, or run the guided format
// wizard (choose fs + label, type-to-confirm the destructive wipe, poll
// progress). Disk objects are kept in an array and referenced by index in
// onclick handlers so a model/label with quotes can never break the markup.
let internalDisks=[];
const fmtSize=(bytes)=>{ const n=Number(bytes)||0; const gb=n/1024**3; if(gb<=0) return ''; return gb>=1000?((gb/1024).toFixed(1)+' TB'):(Math.round(gb)+' GB'); };
function internalMsg(t,cls){ const el=document.getElementById('internalMsg'); el.textContent=t||''; el.className='msg'+(cls?(' '+cls):''); }
async function loadInternal(){
  let d; try{ d=await j('/api/internal/disks'); }catch(e){ return; }
  internalDisks=d.disks||[];
  const el=document.getElementById('internalList');
  if(!internalDisks.length){ el.innerHTML=`<div style="color:var(--silver);font-size:14px">${esc(T('sources.internal.none'))}</div>`; return; }
  el.innerHTML=internalDisks.map((dk,di)=>{
    const fsParts=(dk.partitions||[]).filter(p=>p.fstype);
    const badges=`${esc(fmtSize(dk.size))}`+(dk.adopted?` · <span style="color:#5fce8f">${esc(T('sources.internal.adoptedBadge'))}</span>`:(dk.has_data?(' · '+esc(T('sources.internal.hasData'))):''));
    const sub=`${esc(dk.path)}${dk.fstype?(' · '+esc(dk.fstype)):''}${dk.label?(' · '+esc(dk.label)):''}`;
    const head=`<div class="name">${esc(dk.model||dk.path)}<span class="tag">${badges}</span></div><div class="sub">${sub}</div>`;
    let actions;
    if(dk.adopted){
      actions=`<button class="danger" onclick="removeInternal('${esc(dk.source_id||'')}')">${esc(T('sources.internal.remove'))}</button>`;
    } else {
      const adoptBtn=fsParts.length===1?`<button class="ghost" onclick="adoptInternal(${di},'${esc(fsParts[0].path)}')">${esc(T('sources.internal.adopt'))}</button>`:'';
      actions=`${adoptBtn}<button class="danger" onclick="openFormatWizard(${di})">${esc(T('sources.internal.format'))}</button>`;
    }
    const multi=(!dk.adopted && fsParts.length>1)?('<div style="height:8px"></div>'+fsParts.map(p=>
      `<div class="src"><div class="meta"><div class="sub">${esc(p.path)} · ${esc(p.fstype)}${p.label?(' · '+esc(p.label)):''}</div></div><button class="ghost" onclick="adoptInternal(-1,'${esc(p.path)}')">${esc(T('sources.internal.use'))}</button></div>`
    ).join(''))+'':'';
    return `<div style="margin-bottom:14px"><div class="row">${head}<div style="display:flex;gap:8px;flex-shrink:0">${actions}</div></div>${multi}</div>`;
  }).join('');
}
async function adoptInternal(_di,device){
  internalMsg(T('sources.internal.adopting'));
  const r=await j('/api/internal/adopt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device})});
  internalMsg(r.success?T('sources.internal.adopted'):(r.message||T('sources.error')), r.success?'ok':'bad');
  if(r.success){ loadInternal(); load(); }
}
async function removeInternal(sourceId){
  if(!sourceId) return;
  await j('/api/sources/'+sourceId,{method:'DELETE'});
  internalMsg(T('sources.internal.removed'),'ok');
  loadInternal(); load();
}

// Format wizard state (single instance — one disk formatted at a time).
let fmtDisk=null, fmtStep='choose', fmtFs='ext4', fmtLabel=T('sources.internal.defaultLabel'), fmtPollTimer=null;
function openFormatWizard(di){
  fmtDisk=internalDisks[di]; if(!fmtDisk) return;
  fmtStep='choose'; fmtFs='ext4'; fmtLabel=T('sources.internal.defaultLabel'); window.fmtTypedVal='';
  renderFormatWizard();
}
function closeFormatWizard(){
  if(fmtPollTimer){ clearInterval(fmtPollTimer); fmtPollTimer=null; }
  fmtDisk=null;
  document.getElementById('fmtOverlay')?.remove();
}
function renderFormatWizard(){
  document.getElementById('fmtOverlay')?.remove();
  if(!fmtDisk) return;
  const ov=document.createElement('div');
  ov.id='fmtOverlay';
  ov.style.cssText='position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.8);display:flex;align-items:center;justify-content:center;padding:20px';
  let inner='';
  if(fmtStep==='choose'){
    inner=`<h3 style="margin:0 0 4px">${esc(T('sources.internal.wizardTitle'))}</h3>
      <p style="color:var(--silver);font-size:13px;margin:0 0 16px">${esc(fmtDisk.model||fmtDisk.path)} · ${esc(fmtSize(fmtDisk.size))}</p>
      <label>${esc(T('sources.internal.fsLabel'))}</label>
      <div class="row" style="gap:10px;margin-bottom:10px">
        <button class="${fmtFs==='ext4'?'primary':'ghost'}" style="flex:1" onclick="fmtFs='ext4';renderFormatWizard()">${esc(T('sources.internal.fsExt4'))}</button>
        <button class="${fmtFs==='exfat'?'primary':'ghost'}" style="flex:1" onclick="fmtFs='exfat';renderFormatWizard()">${esc(T('sources.internal.fsExfat'))}</button>
      </div>
      <label>${esc(T('sources.internal.labelField'))}</label>
      <input id="fmtLabelInput" value="${esc(fmtLabel)}" maxlength="${fmtFs==='exfat'?11:16}" oninput="fmtLabel=this.value">
      <div style="height:16px"></div>
      <div class="row" style="gap:10px">
        <button class="ghost" style="flex:1" onclick="closeFormatWizard()">${esc(T('sources.internal.cancel'))}</button>
        <button class="primary" style="flex:1" onclick="window.fmtTypedVal='';fmtStep='confirm';renderFormatWizard()">${esc(T('sources.internal.next'))}</button>
      </div>`;
  } else if(fmtStep==='confirm'){
    inner=`<h3 style="margin:0 0 4px;color:#e66">⚠ ${esc(T('sources.internal.warnTitle'))}</h3>
      <p style="color:var(--silver);font-size:13px;margin:0 0 16px">${esc(T('sources.internal.warnBody',{model:(fmtDisk.model||fmtDisk.path),size:fmtSize(fmtDisk.size),path:fmtDisk.path}))}</p>
      <label>${esc(T('sources.internal.typeToConfirm',{label:fmtLabel.trim()}))}</label>
      <input id="fmtTypedInput" oninput="window.fmtTypedVal=this.value;document.getElementById('fmtConfirmBtn').disabled=(this.value.trim()!==fmtLabel.trim())">
      <div style="height:16px"></div>
      <div class="row" style="gap:10px">
        <button class="ghost" style="flex:1" onclick="fmtStep='choose';renderFormatWizard()">${esc(T('sources.internal.backStep'))}</button>
        <button id="fmtConfirmBtn" class="danger" style="flex:1;border-color:#e66" ${(!window.fmtTypedVal||window.fmtTypedVal.trim()!==fmtLabel.trim())?'disabled':''} onclick="startFormat()">${esc(T('sources.internal.formatNow'))}</button>
      </div>`;
  } else if(fmtStep==='progress'){
    inner=`<div style="text-align:center;padding:10px 0">
      <p id="fmtProgressMsg" style="color:#fff">${esc(T('sources.internal.phasePreparing'))}</p>
      <div style="width:100%;height:8px;background:var(--bg);border-radius:99px;overflow:hidden;margin:14px 0">
        <div id="fmtProgressBar" style="height:100%;width:0%;background:var(--gold);transition:width .4s"></div>
      </div>
      <p style="color:var(--silver);font-size:12px">${esc(T('sources.internal.keepPowered'))}</p>
    </div>`;
  } else if(fmtStep==='done'){
    inner=`<div style="text-align:center;padding:10px 0">
      <p style="color:#5fce8f;font-size:18px;margin:0 0 8px">${esc(T('sources.internal.doneAdopted'))}</p>
      <p style="color:var(--silver);font-size:13px;margin:0 0 16px">${esc(T('sources.internal.doneHint'))}</p>
      <button class="primary" style="width:100%" onclick="closeFormatWizard();loadInternal();load();loadSmbCard();">${esc(T('sources.internal.close'))}</button>
    </div>`;
  } else if(fmtStep==='error'){
    inner=`<div style="text-align:center;padding:10px 0">
      <p style="color:#e66;font-size:16px;margin:0 0 8px">${esc(T('sources.internal.errorTitle'))}</p>
      <p style="color:var(--silver);font-size:13px;margin:0 0 16px">${esc(window.fmtErrorMsg||'')}</p>
      <button class="ghost" style="width:100%" onclick="closeFormatWizard()">${esc(T('sources.internal.close'))}</button>
    </div>`;
  }
  ov.innerHTML=`<div class="card" style="max-width:420px;width:100%;margin:0">${inner}</div>`;
  document.body.appendChild(ov);
}
async function startFormat(){
  fmtStep='progress'; renderFormatWizard();
  let d;
  try{
    const r=await j('/api/internal/format',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({device:fmtDisk.path, fs:fmtFs, label:fmtLabel, confirm:fmtDisk.confirm})});
    d=r;
  }catch(e){ window.fmtErrorMsg=T('sources.networkError'); fmtStep='error'; renderFormatWizard(); return; }
  if(d && d.success===false){ window.fmtErrorMsg=d.message||T('sources.error'); fmtStep='error'; renderFormatWizard(); return; }
  fmtPollTimer=setInterval(async()=>{
    let s; try{ s=await j('/api/internal/format/status'); }catch(e){ return; }
    const pct=Math.max(0,Math.min(100,Math.round(s.progress||0)));
    const bar=document.getElementById('fmtProgressBar'); if(bar) bar.style.width=pct+'%';
    const msg=document.getElementById('fmtProgressMsg'); if(msg) msg.textContent=s.message||T('sources.internal.inProgress');
    if(s.state==='done'){ clearInterval(fmtPollTimer); fmtPollTimer=null; fmtStep='done'; renderFormatWizard(); }
    else if(s.state==='error'){ clearInterval(fmtPollTimer); fmtPollTimer=null; window.fmtErrorMsg=s.message||T('sources.error'); fmtStep='error'; renderFormatWizard(); }
  },2000);
}

// SMB share credentials card for adopted internal disks (installed check +
// username/password + regenerate), appended below the internal disks list.
async function loadSmbCard(){
  let d; try{ d=await j('/api/internal/smb'); }catch(e){ return; }
  document.getElementById('smbCardWrap')?.remove();
  if(!d.shares || !d.shares.length) return;
  const wrap=document.createElement('div');
  wrap.id='smbCardWrap';
  if(!d.installed){
    wrap.innerHTML=`<div class="card" style="border-color:#a86;color:#dba"><p style="margin:0;font-size:13px">${esc(T('sources.internal.needOsUpdate'))}</p></div>`;
  } else {
    const rows=d.shares.map(s=>`<div style="font-size:13px;color:var(--silver)">\\\\${esc(d.ip||d.host)}\\${esc(s.name)}</div>`).join('');
    wrap.innerHTML=`<div class="card">
      <div style="font-weight:600;margin-bottom:6px">${esc(T('sources.internal.smbTitle'))}</div>
      <p style="color:var(--silver);font-size:13px;margin:0 0 10px">${esc(T('sources.internal.smbHelp'))}</p>
      ${rows}
      <div class="row" style="margin-top:10px">
        <div><div style="font-size:11px;color:var(--silver)">${esc(T('sources.internal.smbUser'))}</div><div>${esc(d.username)}</div></div>
        <div><div style="font-size:11px;color:var(--silver)">${esc(T('sources.internal.smbPass'))}</div><div>${esc(d.password)}</div></div>
      </div>
      <div style="height:10px"></div>
      <button class="ghost" onclick="regenSmb()">${esc(T('sources.internal.smbRegenerate'))}</button>
    </div>`;
  }
  document.getElementById('internalList').insertAdjacentElement('afterend', wrap);
}
async function regenSmb(){ await j('/api/internal/smb/regenerate',{method:'POST'}); loadSmbCard(); }

load();
loadUsb();
loadInternal();
loadSmbCard();
loadBackups();
setInterval(loadUsb, 4000);
setInterval(loadInternal, 5000);
</script>
</body>
</html>"""

if __name__ == "__main__":
    try:
        os.makedirs(MOUNT_ROOT, exist_ok=True)
    except Exception:
        pass
    # Re-mount known SMB shares on startup (survives reboots). Runs in the
    # background with retries: boot no longer waits for the network, so the NAS
    # may not be reachable yet — keep trying instead of failing once.
    threading.Thread(target=remount_all_retry, daemon=True, name="smb-remount").start()
    # Auto-mount USB sticks / external drives (read-only) and keep them in sync,
    # so they appear in the Sources UI ready to be added as local sources.
    threading.Thread(target=usb_monitor, daemon=True, name="usb-monitor").start()
    # Watch for completed disk-format jobs and adopt the resulting partition.
    threading.Thread(target=_format_watcher, daemon=True, name="format-watcher").start()
    # Make sure Lyrion has a writable playlist folder ("save as playlist")
    try:
        ensure_playlistdir()
    except Exception as e:
        print(f"[sources] ensure_playlistdir error: {e}")
    # Ensure the internal-storage mount root exists.
    try:
        os.makedirs(INTERNAL_MOUNT_ROOT, exist_ok=True)
    except Exception:
        pass
    # Re-generate Samba shares on startup so adopted disks are reachable even if
    # the service was restarted.
    try:
        regen_samba_shares()
    except Exception as e:
        print(f"[sources] regen_samba_shares error: {e}")
    # threaded=True so the USB/SMB mount scans and a slow Lyrion restart don't
    # serialise behind each other and block the phone/PC web UI.
    app.run(host="0.0.0.0", port=8080, threaded=True)
