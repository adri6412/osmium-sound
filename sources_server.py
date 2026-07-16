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
import urllib.request
import urllib.error
from datetime import datetime, timezone

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
    return jsonify({"success": False, "message": "File troppo grande"}), 413


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
# Local music folders may only be added from these base directories. This
# keeps the (root-privileged) service from being pointed at arbitrary paths
# such as /etc or /root via the add-local-source API.
ALLOWED_LOCAL_ROOTS = ("/mnt", "/media", "/srv", "/home", MOUNT_ROOT, INTERNAL_MOUNT_ROOT)
LYRION_SERVICE = "lyrionmusicserver.service"
SAMBA_SHARES_FILE = "/etc/samba/hifi-shares.conf"
SAMBA_CRED_FILE = "/etc/hifi-player/samba-cred.json"
SAMBA_USER = "hifimusic"
FORMAT_STATUS = "/run/hifi-format-status.json"
FORMAT_UNIT = "hifi-format-disk"
FORMAT_SCRIPT = "/usr/local/sbin/hifi-format-disk.sh"
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
    base_opts = f"uid=0,gid=0,iocharset=utf8,ro,file_mode=0644,dir_mode=0755"
    cred = ""
    if username:
        cred = f",username={username},password={password}"
    else:
        cred = ",guest"

    last = ""
    for vers in ("3.1.1", "3.0", "2.1", "1.0"):
        opts = f"{base_opts}{cred},vers={vers}"
        r = _run(["mount", "-t", "cifs", unc, mountpoint, "-o", opts])
        if r.returncode == 0:
            return True, f"montato (SMB {vers})"
        last = (r.stderr or r.stdout).strip()
    return False, last or "mount fallito"


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


def _adopted_internal_sources():
    return [s for s in load_state().get("sources", []) if s.get("type") == "internal"]


def _share_name(label):
    base = _slug(label or "Musica")
    if not base:
        base = "Musica"
    names = set()
    for s in _adopted_internal_sources():
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
    internal = _adopted_internal_sources()
    lines = []
    for src in internal:
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
    if not internal:
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


def mount_internal(src):
    """Mount one internal source by PARTUUID. Returns (ok, message)."""
    partuuid = src.get("partuuid")
    fstype = (src.get("fstype") or "").lower()
    mountpoint = src.get("mountpoint")
    if not partuuid or not mountpoint:
        return False, "partuuid o mountpoint mancante"
    root = os.path.realpath(INTERNAL_MOUNT_ROOT)
    p = os.path.realpath(mountpoint)
    if p != root and not p.startswith(root + os.sep):
        return False, "mountpoint non valido"
    os.makedirs(mountpoint, exist_ok=True)
    if os.path.ismount(mountpoint):
        return True, "già montato"

    if fstype == "ext4":
        opts = "rw,noatime,nosuid,nodev"
    elif fstype in ("exfat", "vfat"):
        # The in-kernel exfat/vfat driver requires numeric ids, not a username.
        uid, gid = _ensure_samba_uid_gid()
        opts = f"rw,noatime,nosuid,nodev,uid={uid},gid={gid},fmask=0113,dmask=0002,iocharset=utf8"
    else:
        opts = "rw,noatime,nosuid,nodev"

    r = _run(["mount", "-o", opts, f"PARTUUID={partuuid}", mountpoint], timeout=30)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "mount fallito").strip()

    if fstype == "ext4":
        # mkfs.ext4 leaves the root dir owned by root:root, which the Samba
        # forced user (hifimusic) cannot write into. exFAT/vfat get this via
        # the uid/gid mount options above instead.
        try:
            uid, gid = _ensure_samba_uid_gid()
            os.chown(mountpoint, uid, gid)
            os.chmod(mountpoint, 0o2775)
        except Exception:
            pass
    return True, "montato"


def remount_all():
    state = load_state()
    for src in state.get("sources", []):
        t = src.get("type")
        try:
            if t == "smb":
                mount_smb(src)
            elif t == "internal":
                mount_internal(src)
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


def _usb_mount_type(fstype):
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


def _usb_partitions():
    """USB block devices carrying a filesystem → [{path,name,fstype,label,size}].
    Handles partitioned (sdX1) and whole-disk filesystems; skips optical drives
    (type 'rom') and any non-USB transport (internal SATA/eMMC)."""
    try:
        r = _run(["lsblk", "-J", "-o", "PATH,NAME,TYPE,FSTYPE,LABEL,SIZE,TRAN"], timeout=10)
        data = json.loads(r.stdout or "{}")
    except Exception:
        return []
    out = []
    for dev in data.get("blockdevices", []):
        if dev.get("tran") != "usb" or dev.get("type") != "disk":
            continue
        kids = dev.get("children") or []
        if kids:
            out.extend(p for p in kids if p.get("type") == "part" and p.get("fstype"))
        elif dev.get("fstype"):
            out.append(dev)
    return out


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
                    _run(["mount", "-t", _usb_mount_type(fs), "-o", _usb_mount_opts(fs),
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
    ALLOWED_LOCAL_ROOTS for local paths) rather than trusting the stored state
    verbatim — state can come from a restored /etc/hifi-sources.json (see
    /api/restore), which is untrusted archive content that never goes through
    api_add_smb()/api_add_local()'s own validation. Without this, a crafted
    backup with e.g. {"type":"local", "path":"/"} would get handed straight to
    Lyrion as a media directory."""
    smb_root = os.path.realpath(MOUNT_ROOT)
    internal_root = os.path.realpath(INTERNAL_MOUNT_ROOT)
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
        else:
            raw = src.get("path")
            p = _local_path_allowed(raw) if raw else None
        if p and p not in paths:
            paths.append(p)
    return paths


def apply_to_lyrion(state):
    """Write mediadirs into Lyrion prefs and restart + rescan."""
    try:
        import yaml
    except Exception:
        return False, "python3-yaml non installato"

    prefs = _ensure_prefs()
    if not prefs:
        return False, "File prefs di Lyrion non trovato. Verifica che Lyrion sia avviato (systemctl status lyrionmusicserver)."

    paths = current_paths(state)

    # Warn if an internal source is not mounted: applying would hand an empty
    # mountpoint to Lyrion and clear the library. The user must re-attach the
    # disk or remove the source.
    unmounted_internal = []
    for src in state.get("sources", []):
        if src.get("type") == "internal":
            mp = src.get("mountpoint")
            if not mp or not os.path.ismount(mp):
                unmounted_internal.append(src.get("name") or "interno")
    if unmounted_internal:
        return False, "Disco interno non montato: " + ", ".join(unmounted_internal) + ". Verifica il collegamento prima di applicare."

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

    return True, f"{len(paths)} sorgenti applicate. Lyrion riavviato e in scansione."


# ─────────────────────────── Backup / restore ────────────────────────
# Exports/imports the appliance's USER configuration: DAC selection, DSP/EQ
# state, pointer preference, OTA channel choice, music sources and any room-
# correction FIR filter. Deliberately excludes OS_VERSION/SYSTEM_VERSION (those
# are OTA bookkeeping, not user config — restoring them would desync the
# updater's view of what's installed) and anything network/credential-related
# beyond the SMB share passwords already stored in hifi-sources.json.
#
# Both directions use a fixed allow-list of exact paths (+ the FIR filters
# directory) — never the tar member's own path verbatim — so a malicious or
# corrupt archive can't write outside these locations (no path traversal, no
# symlinks, no device/special files: only regular files are ever opened).
BACKUP_FILES = [
    "/etc/hifi-player/pointer-enabled",
    "/etc/hifi-player/dsp.json",
    "/etc/hifi-player/dsp-presets.json",
    "/etc/hifi-player/ota-channel",
    "/etc/default/squeezelite",
    "/etc/camilladsp/config.yml",
    "/etc/hifi-sources.json",
    "/var/lib/hifi-player/dsp-target",
]
BACKUP_DIRS = [
    "/etc/camilladsp/filters",  # room-correction FIR file(s), if any
]
MAX_RESTORE_MEMBER_SIZE = 32 * 1024 * 1024  # 32MB per file is generous for config + a FIR filter
MAX_RESTORE_MEMBERS = 200
# Compressed-upload ceiling, checked BEFORE tarfile.open()/getmembers() ever
# runs. This is deliberately far tighter than MAX_RESTORE_MEMBERS *
# MAX_RESTORE_MEMBER_SIZE (6.4GB) — a real backup (see _backup_build) is only
# ever a handful of small config files plus at most a couple of FIR filters,
# so it's never anywhere near this size. Bounds how much a maliciously
# highly-compressed small archive can force tarfile to decompress while
# walking members, since getmembers() has to decompress the whole stream to
# enumerate entries before per-member size checks below ever get a chance to
# run.
MAX_RESTORE_ARCHIVE_SIZE = 64 * 1024 * 1024


def _backup_build():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in BACKUP_FILES:
            if os.path.isfile(path):
                tar.add(path, arcname=path.lstrip("/"))
        for d in BACKUP_DIRS:
            if os.path.isdir(d):
                tar.add(d, arcname=d.lstrip("/"))
    return buf.getvalue()


def _restore_dest_for_member(name):
    """Map a tar member name to an allowed absolute destination path, or None
    if it doesn't match the allow-list (exact file or under an allowed dir)."""
    normalized = os.path.normpath("/" + name.lstrip("/"))
    if normalized in BACKUP_FILES:
        return normalized
    for d in BACKUP_DIRS:
        prefix = d.rstrip("/") + "/"
        if normalized.startswith(prefix) and normalized != d:
            return normalized
    return None


def _restore_apply(archive_bytes):
    """Extract only allow-listed regular files from the archive. Returns
    (restored_paths, errors)."""
    restored, errors = [], []
    try:
        tar = tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz")
    except Exception:
        return [], ["Archivio non valido o corrotto"]

    with tar:
        members = tar.getmembers()
        if len(members) > MAX_RESTORE_MEMBERS:
            return [], ["Archivio non valido (troppi file)"]
        for member in members:
            if not member.isfile():
                continue  # skip dirs, symlinks, devices, etc.
            if member.size > MAX_RESTORE_MEMBER_SIZE:
                errors.append(f"{member.name}: troppo grande, saltato")
                continue
            dest = _restore_dest_for_member(member.name)
            if not dest:
                continue  # silently ignore anything outside the allow-list
            try:
                src = tar.extractfile(member)
                if src is None:
                    continue
                data = src.read()
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                tmp = dest + ".restore.tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)
                restored.append(dest)
            except Exception as e:
                print(f"[sources] restore failed for {dest}: {e}")
                errors.append(f"{os.path.basename(dest)}: ripristino fallito")
    return restored, errors


def _restore_apply_side_effects(restored):
    """Re-apply the config that was just restored (best-effort, non-fatal)."""
    notes = []
    if "/etc/hifi-sources.json" in restored:
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
    return notes


@app.route("/api/backup", methods=["GET"])
def api_backup():
    denied = _require_pair_token()
    if denied:
        return denied
    data = _backup_build()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    resp = Response(data, mimetype="application/gzip")
    resp.headers["Content-Disposition"] = f'attachment; filename="osmium-backup-{stamp}.tar.gz"'
    return resp


@app.route("/api/restore", methods=["POST"])
def api_restore():
    denied = _require_pair_token()
    if denied:
        return denied
    f = request.files.get("file")
    if not f:
        return jsonify({"success": False, "message": "Nessun file caricato"}), 400
    archive_bytes = f.read(MAX_RESTORE_ARCHIVE_SIZE + 1)
    if len(archive_bytes) > MAX_RESTORE_ARCHIVE_SIZE:
        return jsonify({"success": False, "message": "File troppo grande"}), 400
    restored, errors = _restore_apply(archive_bytes)
    if not restored and errors:
        return jsonify({"success": False, "message": "; ".join(errors)}), 400
    notes = _restore_apply_side_effects(restored)
    msg = f"{len(restored)} file ripristinati." + ((" " + " ".join(notes)) if notes else "")
    if errors:
        msg += " Avvisi: " + "; ".join(errors)
    return jsonify({"success": True, "message": msg, "restored": len(restored)})


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
        return jsonify({"success": False, "message": "Nessun file caricato"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in FIR_KINDS:
        return jsonify({"success": False, "message": "Formato non supportato (usa .wav o .txt)"}), 400
    data = f.read(FIR_MAX_SIZE + 1)
    if len(data) > FIR_MAX_SIZE:
        return jsonify({"success": False, "message": "File troppo grande (max 20MB)"}), 400
    if not data:
        return jsonify({"success": False, "message": "File vuoto"}), 400
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
        return jsonify({"success": False, "message": "Salvataggio fallito"}), 500
    return jsonify({"success": True, "message": "Filtro caricato. Attivalo da Impostazioni → DSP."})


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
        return jsonify({"success": False, "message": "Non consentito da remoto"}), 403
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
        return jsonify({"success": False, "message": "Non consentito da remoto"}), 403
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
        return jsonify({"success": False, "message": "Troppi tentativi, riprova tra qualche minuto"}), 429
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
        return jsonify({"success": False, "message": "Token di pairing mancante o non valido"}), 401
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


def _proxy_to_api_server(path, method="GET", body=None):
    req = urllib.request.Request(f"{_API_SERVER_BASE}{path}", method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8")), e.code
        except Exception:
            # api_server.py didn't return JSON for this error — don't forward
            # the raw exception text (may contain internal paths/details) to
            # the caller; log it server-side instead.
            print(f"[sources] proxy to {path} failed: {e}")
            return {"success": False, "message": "Servizio DSP non disponibile"}, e.code
    except Exception as e:
        print(f"[sources] proxy to {path} unreachable: {e}")
        return {"success": False, "message": "Servizio DSP non raggiungibile"}, 502


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
    body, status = _proxy_to_api_server("/dsp_set", method="POST", body=data)
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
    body, status = _proxy_to_api_server("/dsp_preset_load", method="POST", body=data)
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
    ("/api/system/updates/lyrion/check", "GET", "/lyrion_update/check"),
    ("/api/system/updates/lyrion/apply", "POST", "/lyrion_update/apply"),
    ("/api/system/updates/lyrion/status", "GET", "/lyrion_update/status"),
    ("/api/system/reboot", "POST", "/reboot"),
    ("/api/system/shutdown", "POST", "/shutdown"),
]


def _make_system_proxy_view(remote_path, method):
    def view():
        denied = _require_pair_token()
        if denied:
            return denied
        data = request.get_json(silent=True) if method == "POST" else None
        body, status = _proxy_to_api_server(remote_path, method=method, body=data)
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
    state = load_state()
    out = []
    for s in state.get("sources", []):
        item = dict(s)
        item.pop("password", None)
        item.pop("smbpassword", None)
        t = s.get("type")
        if t == "smb":
            item["mounted"] = os.path.ismount(s["mountpoint"])
        elif t == "internal":
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
        return jsonify({"success": False, "message": "Percorso mancante"}), 400
    path = _local_path_allowed(path)
    if not path:
        return jsonify({"success": False, "message": "Percorso non consentito"}), 400
    if not os.path.isdir(path):
        return jsonify({"success": False, "message": f"La cartella {path} non esiste"}), 400
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
        return jsonify({"success": False, "message": "Server e nome condivisione obbligatori"}), 400
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
        return jsonify({"success": False, "message": f"Mount fallito: {msg}"}), 400
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
                elif t == "internal":
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
        return jsonify({"success": False, "message": "Device non valido"}), 400

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
        return jsonify({"success": False, "message": "Disco non trovato o di sistema"}), 400
    if not part:
        # Whole disk with no partitions: reject.
        return jsonify({"success": False, "message": "Seleziona una partizione con filesystem"}), 400
    if not part.get("fstype"):
        return jsonify({"success": False, "message": "Partizione senza filesystem"}), 400

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
        return jsonify({"success": False, "message": f"Mount fallito: {msg}"}), 400

    with _lock:
        state = load_state()
        state["sources"] = [s for s in state["sources"] if s.get("id") != src["id"]]
        state["sources"].append(src)
        save_state(state)
        regen_samba_shares()
    apply_to_lyrion(state)
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
        return jsonify({"success": False, "message": "Device non valido"}), 400
    if fs not in ("ext4", "exfat"):
        return jsonify({"success": False, "message": "Filesystem non supportato"}), 400
    if not _label_ok(label):
        return jsonify({"success": False, "message": "Etichetta non valida"}), 400
    if fs == "exfat" and len(label) > 11:
        return jsonify({"success": False, "message": "Etichetta troppo lunga per exFAT (max 11)"}), 400

    disks = _internal_disks()
    disk = next((d for d in disks if d["path"] == device), None)
    if not disk:
        return jsonify({"success": False, "message": "Disco non trovato o di sistema"}), 400
    if disk.get("confirm") != confirm:
        return jsonify({"success": False, "message": "Conferma non corrispondente"}), 400
    if disk.get("adopted"):
        return jsonify({"success": False, "message": "Disco già adottato come sorgente"}), 400

    # Check no partitions are mounted.
    for p in disk.get("partitions") or []:
        if p.get("mountpoint"):
            return jsonify({"success": False, "message": "Disco montato, smontalo prima"}), 400

    # Check mkfs.exfat is available when requested.
    if fs == "exfat":
        if _run(["which", "mkfs.exfat"], timeout=5).returncode != 0:
            return jsonify({"success": False, "message": "Aggiornamento OS richiesto per formattare exFAT"}), 424

    # Interlock: no concurrent format job.
    if os.path.exists(FORMAT_STATUS):
        try:
            with open(FORMAT_STATUS) as f:
                st = json.load(f)
            if st.get("state") not in ("done", "error", "idle"):
                return jsonify({"success": False, "message": "Formattazione già in corso"}), 409
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
            for s in _adopted_internal_sources():
                if s.get("partuuid") == partuuid:
                    status["adopted"] = True
                    status["source_id"] = s.get("id")
                    status["share"] = s.get("share")
                    break
    return jsonify(status)


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
    for s in _adopted_internal_sources():
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
        return jsonify({"success": False, "message": "Samba non installato"}), 424
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
        })
    return jsonify({"disks": disks})


# ─────────────────────────── Web UI ─────────────────────────────────
@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Osmium Sound — Sorgenti musicali</title>
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
  .applybar { position:fixed; left:0; right:0; bottom:0; background:#0d0d0dee; backdrop-filter:blur(8px); border-top:1px solid var(--border); padding:12px 16px; }
  .applybar .inner { max-width:640px; margin:0 auto; display:flex; gap:10px; align-items:center; }
</style>
</head>
<body>
<div class="wrap">
  <h1><span class="dot"></span> Sorgenti musicali</h1>
  <p style="color:var(--silver);font-size:14px">Aggiungi le cartelle che contengono la tua musica. Al termine premi <b>Applica</b> per aggiornare la libreria.</p>

  <h2>Sorgenti attive</h2>
  <div class="card" id="list"><div style="color:var(--silver);font-size:14px">Caricamento…</div></div>

  <h2>Dischi USB</h2>
  <div class="card" id="usbList"><div style="color:var(--silver);font-size:14px">Nessun disco USB collegato. Inserisci una chiavetta o un hard disk USB.</div></div>

  <h2>Aggiungi cartella locale</h2>
  <div class="card">
    <label>Percorso sul dispositivo</label>
    <input id="localPath" placeholder="/media/musica">
    <div style="height:10px"></div>
    <button class="ghost" onclick="addLocal()">Aggiungi cartella locale</button>
    <div class="msg" id="localMsg"></div>
  </div>

  <h2>Aggiungi cartella di rete (SMB)</h2>
  <div class="card">
    <div class="row"><div style="flex:1"><label>Server / IP</label><input id="smbServer" placeholder="192.168.0.20"></div>
    <div style="flex:1"><label>Condivisione</label><input id="smbShare" placeholder="Musica"></div></div>
    <div class="row"><div style="flex:1"><label>Utente (vuoto = ospite)</label><input id="smbUser" placeholder="utente"></div>
    <div style="flex:1"><label>Password</label><input id="smbPass" type="password" placeholder="••••••"></div></div>
    <div style="height:12px"></div>
    <button class="ghost" onclick="addSmb()">Monta e aggiungi</button>
    <div class="msg" id="smbMsg"></div>
  </div>

  <h2>Correzione ambientale (filtro FIR)</h2>
  <div class="card">
    <p style="color:var(--silver);font-size:13px;margin:0 0 10px">Carica un filtro di convoluzione (risposta all'impulso) generato con REW o rePhase — formato WAV o testo (.txt, un coefficiente per riga). Verrà applicato identicamente a entrambi i canali. Attivalo poi da Impostazioni → DSP sul dispositivo.</p>
    <div id="firStatus" style="font-size:13px;color:var(--silver);margin-bottom:10px">Caricamento…</div>
    <div class="row">
      <label class="ghost" style="text-align:center;flex:1;cursor:pointer" for="firFile">⬆ Carica filtro</label>
      <button class="danger" style="flex:1" onclick="removeFir()">Rimuovi filtro</button>
    </div>
    <input type="file" id="firFile" accept=".wav,.txt" style="display:none" onchange="uploadFir(this)">
    <div class="msg" id="firMsg"></div>
  </div>

  <h2>Backup e ripristino</h2>
  <div class="card">
    <p style="color:var(--silver);font-size:13px;margin:0 0 10px">Esporta la configurazione del dispositivo (DAC, DSP/EQ, sorgenti, puntatore, canale aggiornamenti) in un file, o ripristinala da un backup precedente.</p>
    <div class="row">
      <a id="backupLink" class="ghost" style="text-decoration:none;display:inline-block;text-align:center;flex:1" href="/api/backup">⬇ Scarica backup</a>
      <label class="ghost" style="text-align:center;flex:1;cursor:pointer" for="restoreFile">⬆ Ripristina da file</label>
    </div>
    <input type="file" id="restoreFile" accept=".gz,.tar.gz,application/gzip" style="display:none" onchange="doRestore(this)">
    <div class="msg" id="restoreMsg"></div>
  </div>
</div>

<div class="applybar"><div class="inner">
  <button class="primary" style="flex:1" onclick="apply()">Applica e scansiona libreria</button>
  <span class="msg" id="applyMsg" style="margin:0"></span>
</div></div>

<script>
// A remote (non-localhost) visit — the "scan the QR from Settings → Backup e
// ripristino, no companion app needed" flow — carries a pairing token in the
// URL (?token=...), minted server-side when that QR was generated. Attach it
// to every call this page makes so /api/* routes that now require pairing
// (see _require_pair_token()) keep working from a plain phone/PC browser,
// not just from the Electron kiosk (which is exempt via 127.0.0.1).
const PAIR_TOKEN = new URLSearchParams(location.search).get('token') || '';
async function j(url, opts){
  opts = opts || {};
  if (PAIR_TOKEN) {
    opts.headers = Object.assign({}, opts.headers, {'Authorization': 'Bearer ' + PAIR_TOKEN});
  }
  const r=await fetch(url,opts); return r.json();
}
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
if (PAIR_TOKEN) {
  document.getElementById('backupLink').href = '/api/backup?token=' + encodeURIComponent(PAIR_TOKEN);
}
async function load(){
  const d=await j('/api/sources');
  const el=document.getElementById('list');
  if(!d.sources.length){ el.innerHTML='<div style="color:var(--silver);font-size:14px">Nessuna sorgente. Aggiungine una qui sotto.</div>'; return; }
  el.innerHTML=d.sources.map(s=>{
            const isSmb=s.type==='smb';
    const isInternal=s.type==='internal';
    const status=isSmb?(s.mounted?'<span class="ok">montato</span>':'<span class="bad">non montato</span>')
                      :isInternal?(s.mounted?'<span class="ok">montato</span>':'<span class="bad">non montato</span>')
                      :(s.exists?'<span class="ok">ok</span>':'<span class="bad">mancante</span>');
    const sub=isSmb?('//'+esc(s.server)+'/'+esc(s.share)+' → '+esc(s.mountpoint))
              :isInternal?(esc(s.mountpoint||s.path||''))
              :esc(s.path);
    const tag=isSmb?'SMB':isInternal?'INTERNO':'LOCALE';
    return `<div class="src"><div class="meta"><div class="name">${esc(s.name)}<span class="tag">${tag}</span></div>
      <div class="sub">${sub} · ${status}</div></div>
      <button class="danger" onclick="rm('${s.id}')">Rimuovi</button></div>`;
  }).join('');
}
async function addLocal(){
  const path=document.getElementById('localPath').value.trim();
  const m=document.getElementById('localMsg'); m.textContent='…';
  const r=await j('/api/sources/local',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  m.textContent=r.success?'Aggiunta ✓':(r.message||'Errore'); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){document.getElementById('localPath').value='';load();}
}
async function addSmb(){
  const body={server:smbServer.value,share:smbShare.value,username:smbUser.value,password:smbPass.value};
  const m=document.getElementById('smbMsg'); m.textContent='Montaggio…';
  const r=await j('/api/sources/smb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  m.textContent=r.success?('Montata ✓ '+(r.message||'')):(r.message||'Errore'); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){smbPass.value='';load();}
}
async function rm(id){ await j('/api/sources/'+id,{method:'DELETE'}); load(); }

// ── Room correction (FIR filter) ────────────────────────────────────
async function loadFir(){
  let d; try{ d=await j('/api/dsp/fir'); }catch(e){ return; }
  const el=document.getElementById('firStatus');
  el.textContent=d.present ? ('Filtro attivo: '+d.filename+' ('+Math.round(d.size/1024)+' KB)') : 'Nessun filtro caricato.';
}
async function uploadFir(input){
  const file=input.files && input.files[0]; if(!file) return;
  const m=document.getElementById('firMsg'); m.textContent='Caricamento…'; m.className='msg';
  const body=new FormData(); body.append('file', file);
  try{
    const d=await j('/api/dsp/fir',{method:'POST',body});
    m.textContent=d.message||(d.success?'Fatto':'Errore'); m.className='msg '+(d.success?'ok':'bad');
    if(d.success) loadFir();
  }catch(e){ m.textContent='Errore di rete'; m.className='msg bad'; }
  input.value='';
}
async function removeFir(){
  const m=document.getElementById('firMsg'); m.textContent='Rimozione…'; m.className='msg';
  const r=await j('/api/dsp/fir',{method:'DELETE'});
  m.textContent=r.removed?'Rimosso ✓':'Nessun filtro da rimuovere'; m.className='msg '+(r.removed?'ok':'');
  loadFir();
}
loadFir();

// ── Backup / restore ───────────────────────────────────────────────
async function doRestore(input){
  const file=input.files && input.files[0]; if(!file) return;
  const m=document.getElementById('restoreMsg'); m.textContent='Ripristino…'; m.className='msg';
  const body=new FormData(); body.append('file', file);
  try{
    const d=await j('/api/restore',{method:'POST',body});
    m.textContent=d.message||(d.success?'Fatto':'Errore'); m.className='msg '+(d.success?'ok':'bad');
  }catch(e){ m.textContent='Errore di rete'; m.className='msg bad'; }
  input.value='';
}
async function apply(){
  const m=document.getElementById('applyMsg'); m.textContent='Applico…'; m.className='msg';
  const r=await j('/api/apply',{method:'POST'});
  m.textContent=r.message||(r.success?'Fatto':'Errore'); m.className='msg '+(r.success?'ok':'bad');
}

// ── USB disks ───────────────────────────────────────────────────────
// Paths are kept in an array and referenced by index in onclick handlers, so a
// folder name with quotes/specials can never break the markup.
let usbPaths=[];
async function loadUsb(){
  let d; try{ d=await j('/api/usb'); }catch(e){ return; }
  const el=document.getElementById('usbList'); usbPaths=[];
  if(!d.disks || !d.disks.length){
    el.innerHTML='<div style="color:var(--silver);font-size:14px">Nessun disco USB collegato. Inserisci una chiavetta o un hard disk USB.</div>';
    return;
  }
  el.innerHTML=d.disks.map(dk=>{
    const di=usbPaths.push(dk.mountpoint)-1;
    const tag=`USB${dk.fstype?(' '+esc(dk.fstype)):''}${dk.size?(' · '+esc(dk.size)):''}`;
    const head=`<div class="name">${esc(dk.label)||'USB'}<span class="tag">${tag}</span></div><div class="sub">${esc(dk.mountpoint)}</div>`;
    const all=`<button class="ghost" onclick="addUsb(${di})">Aggiungi tutto il disco</button>`;
    const fold=(dk.folders||[]).map(f=>{
      const i=usbPaths.push(f.path)-1;
      return `<div class="src"><div class="meta"><div class="sub">📁 ${esc(f.name)}</div></div><button class="ghost" onclick="addUsb(${i})">Aggiungi</button></div>`;
    }).join('');
    return `<div style="margin-bottom:14px">${head}<div style="height:8px"></div>${all}${fold?('<div style="height:8px"></div>'+fold):''}</div>`;
  }).join('');
}
async function addUsb(i){
  const path=usbPaths[i]; if(!path) return;
  const r=await j('/api/sources/local',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  if(r.success){ load(); } else { alert(r.message||'Errore'); }
}

load();
loadUsb();
setInterval(loadUsb, 4000);
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
