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
import socket
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
# PARTUUID/UUID. This is the only mountpoint a USB stick ever gets — see the
# USB drives section below.
USB_ADOPTED_ROOT = "/mnt/hifi-usb"
# Local music folders may only be added from these base directories. This
# keeps the (root-privileged) service from being pointed at arbitrary paths
# such as /etc or /root via the add-local-source API.
ALLOWED_LOCAL_ROOTS = ("/mnt", "/media", "/srv", "/home", MOUNT_ROOT, INTERNAL_MOUNT_ROOT, USB_ADOPTED_ROOT)
LYRION_SERVICE = "lyrionmusicserver.service"
SAMBA_SHARES_FILE = "/etc/samba/hifi-shares.conf"
SAMBA_CRED_FILE = "/etc/hifi-player/samba-cred.json"
SAMBA_USER = "hifimusic"
# LAN discovery for those shares (see _publish_smb_discovery): a Bonjour record
# for macOS/Linux and the wsdd2 daemon (WS-Discovery + LLMNR) for Windows. Both
# are published only while the shares actually exist.
AVAHI_SMB_SERVICE = "/etc/avahi/services/hifi-smb.service"
WSDD_UNIT = "wsdd2.service"
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
    """Mount one SMB source. Returns (ok, message).

    Read-only by default (matches "add a NAS folder to browse into the
    library" — most SMB sources are someone else's existing music
    collection, not a target the appliance should be able to modify).
    src["rw"]=True mounts read-write instead, with the same uid=/gid=
    mapping the FAT-like adopted-disk mounts use (mount.cifs presents every
    file under that uid/gid regardless of what wrote it, so unlike ext4
    there's no post-write chown step needed) — opt-in, e.g. for CD-ripping
    onto a NAS share (see _rip_writable_sources())."""
    server = src["server"].strip().strip("/")
    share = src["share"].strip().strip("/")
    username = src.get("username", "")
    password = src.get("password", "")
    for value in (server, share, username, password):
        if not _field_ok(value):
            return False, _ht('mount.invalidFields', _hlang())

    # The mountpoint is derived from user-supplied server/share; resolve it and
    # make sure it can never escape MOUNT_ROOT before we create or mount onto it.
    root = os.path.realpath(MOUNT_ROOT)
    mountpoint = os.path.realpath(src["mountpoint"])
    if mountpoint != root and not mountpoint.startswith(root + os.sep):
        return False, _ht('mount.invalidMountpoint', _hlang())
    os.makedirs(mountpoint, exist_ok=True)

    if os.path.ismount(mountpoint):
        return True, _ht('mount.alreadyMounted', _hlang())

    # mount.cifs against an unreachable/silently-dropping host can block the
    # kernel-level mount() syscall in uninterruptible sleep (D state) for far
    # longer than _run()'s own timeout — a SIGKILL can't interrupt that until
    # the blocking syscall itself gives up, which can take minutes or hang
    # indefinitely, wedging the request. A plain TCP probe on the SMB port
    # first fails fast (5s) instead of ever reaching that risky call when the
    # server just isn't there.
    try:
        with socket.create_connection((server, 445), timeout=5):
            pass
    except OSError:
        return False, _ht('mount.smbUnreachable', _hlang(), server=server)

    unc = f"//{server}/{share}"
    if src.get("rw"):
        uid, gid = _ensure_samba_uid_gid()
        base_opts = f"uid={uid},gid={gid},iocharset=utf8,rw,file_mode=0664,dir_mode=0775"
    else:
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
                return True, _ht('mount.mountedSmb', _hlang(), vers=vers)
            last = (r.stderr or r.stdout).strip()
        return False, last or _ht('mount.genericFailed', _hlang())
    finally:
        if cred_path:
            try:
                os.remove(cred_path)
            except OSError:
                pass


def umount(mountpoint):
    if os.path.ismount(mountpoint):
        _run(["umount", "-l", mountpoint])


def umount_clean(mountpoint):
    """Unmount an adopted disk the way a removable device deserves: flush
    first, then a plain umount, and the lazy detach only as a fallback.

    `umount -l` on its own (what umount() does, and what removing a source
    used to call) returns immediately and leaves the writeback to happen
    whenever the kernel gets round to it. On a USB stick — which the user
    pulls out the moment the entry disappears from the list — that is
    precisely how a FAT filesystem ends up corrupted. `sync` first, so
    there is nothing left to write back; the plain umount then fails loudly
    if something still holds the mount (the Lyrion scanner walking it, an
    open Samba handle), and only then do we detach lazily rather than leave
    the user with a source that refuses to go away.

    Returns (ok, lazy_used)."""
    if not mountpoint or not os.path.ismount(mountpoint):
        return True, False
    _run(["sync"], timeout=60)
    if _run(["umount", mountpoint], timeout=30).returncode == 0:
        return True, False
    r = _run(["umount", "-l", mountpoint], timeout=30)
    return r.returncode == 0, True


def _drop_adopted_mountpoint(mountpoint):
    """Remove the now-unused mountpoint directory of an adopted disk.

    Not housekeeping for its own sake: an empty /mnt/hifi-usb/<LABEL>-<id>
    left behind is indistinguishable, to os.path.isdir(), from a real folder,
    and _sync_from_lyrion() takes exactly that test as permission to offer a
    stale Lyrion mediadir back as a new `local` source. Seen in the field: an
    Osmium install stick adopted as a music source, unplugged, its source
    deleted — and the entry reappearing on the very next poll, for good.

    Confined to the two roots we create ourselves, and only when the
    directory is really unmounted and really empty, so this can never eat a
    user's folder."""
    if not mountpoint:
        return
    p = os.path.realpath(mountpoint)
    for root in (os.path.realpath(USB_ADOPTED_ROOT), os.path.realpath(INTERNAL_MOUNT_ROOT)):
        if p.startswith(root + os.sep):
            break
    else:
        return
    if os.path.ismount(p):
        return
    try:
        os.rmdir(p)                      # fails, harmlessly, if not empty
    except OSError:
        pass


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
                        "PATH,NAME,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,RM,FSTYPE,LABEL,UUID,PARTUUID,"
                        "PKNAME,MOUNTPOINT,PARTTYPENAME"],
                       timeout=10)


def _is_efi_partition(part):
    """True for an EFI System Partition, on GPT or MBR alike. Identified by
    lsblk's own PARTTYPENAME (util-linux resolves both the GPT ESP GUID
    c12a7328-f81f-11d2-ba4b-00a0c93ec93b and the MBR 0xEF type code to a name
    containing "EFI"), not by filesystem label -- a user's own USB stick can
    be vfat-formatted and labeled anything, but its partition *type* is set by
    whatever tool made it bootable and isn't something a music folder would
    ever legitimately have. Seen in the field: a bootable installer USB stick
    plugged in for something unrelated got its ESP auto-adopted as a music
    source alongside the real data partition, cluttering "Music sources" with
    a permanently-empty/junk entry."""
    return "efi" in (part.get("parttypename") or "").lower()


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
                    for root in ("/mnt", "/media", INTERNAL_MOUNT_ROOT):
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
            if _is_efi_partition(part):
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
    """Adopted internal disks, adopted (read-write) USB disks, and local
    rootfs folders opted into Samba sharing (`type == "local"` with
    `samba: true`) -- every source type that gets a Samba share. Only the
    first two get a stable mountpoint/CD-rip-destination status; a shared
    local folder is just a plain rootfs path (see api_add_local())."""
    return [s for s in load_state().get("sources", [])
            if s.get("type") in ("internal", "usb")
            or (s.get("type") == "local" and s.get("samba"))]


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


def _existing_adopted_source(source_type, partuuid, fsuuid):
    """An already-adopted "internal"/"usb" source for this exact physical
    partition, if any — matched by partuuid, falling back to fsuuid for a
    "superfloppy" disk with no partition table. Re-adopting an
    already-adopted disk (a double tap, a retry after a slow response)
    should reuse that source's id/share/mountpoint, not mint a second one
    under a different share name via _share_name() — the id is derived from
    the share, so a fresh share means a fresh id, and the old entry never
    gets cleaned up since nothing then matches its id."""
    for s in _adopted_disk_sources():
        if s.get("type") != source_type:
            continue
        if partuuid and s.get("partuuid") == partuuid:
            return s
        if not partuuid and fsuuid and s.get("fsuuid") == fsuuid:
            return s
    return None


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


# Announced as the host's own mDNS name (%h -> hifiplayer.local), so it follows
# a renamed device for free. _device-info._tcp carries no port of its own (0 is
# the Bonjour convention for a record that only describes the host); it exists
# purely so Finder draws a server icon instead of a generic PC.
_AVAHI_SMB_XML = """<?xml version="1.0" standalone='no'?><!--*-nxml-*-->
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<!-- HiFi Player - written by sources_server.py, do not edit by hand. -->
<service-group>
  <name replace-wildcards="yes">%h</name>
  <service>
    <type>_smb._tcp</type>
    <port>445</port>
  </service>
  <service>
    <type>_device-info._tcp</type>
    <port>0</port>
    <txt-record>model=RackMac</txt-record>
  </service>
</service-group>
"""


def _unit_available(unit):
    """True if systemd knows a unit file by that name (i.e. pkg installed)."""
    r = _run(["systemctl", "list-unit-files", unit], timeout=5)
    return r.returncode == 0 and unit in (r.stdout or "")


def _publish_smb_discovery(enabled):
    """Make the shares show up in the network browser of the three OSes.

    None of them browses SMB servers over SMB itself: Windows Explorer's
    "Network" uses WS-Discovery (the wsdd2 daemon — NetBIOS browsing died with
    SMB1, and nmbd is masked here for boot speed, see apply.d/0031), while
    macOS Finder and GNOME's "Networks" use the Bonjour `_smb._tcp` record.
    Publish neither and the shares still work, but the device is invisible and
    the user has to type \\\\<ip>\\<share> by hand.

    Tied to the shares existing rather than left permanently on: with no
    adopted disk smbd is stopped, and advertising a server that refuses every
    connection is worse than advertising nothing.
    """
    try:
        if enabled:
            os.makedirs(os.path.dirname(AVAHI_SMB_SERVICE), exist_ok=True)
            cur = None
            try:
                with open(AVAHI_SMB_SERVICE) as f:
                    cur = f.read()
            except OSError:
                pass
            if cur != _AVAHI_SMB_XML:
                tmp = AVAHI_SMB_SERVICE + ".tmp"
                with open(tmp, "w") as f:
                    f.write(_AVAHI_SMB_XML)
                os.chmod(tmp, 0o644)
                # avahi-daemon watches this directory and reloads on its own.
                os.replace(tmp, AVAHI_SMB_SERVICE)
        elif os.path.exists(AVAHI_SMB_SERVICE):
            os.remove(AVAHI_SMB_SERVICE)
    except Exception as e:
        print(f"[sources] avahi smb service: {e}")

    # wsdd2 is left disabled by the OS update that installs it (a daemon idling
    # for nothing costs boot time), and is missing outright on a device that
    # hasn't taken that update yet — either way it only costs Windows browsing,
    # never the shares themselves, so a failure here is not fatal.
    try:
        if not _unit_available(WSDD_UNIT):
            return
        action = "enable" if enabled else "disable"
        _run(["systemctl", action, "--now", WSDD_UNIT], timeout=30)
    except Exception as e:
        print(f"[sources] {WSDD_UNIT}: {e}")


def regen_samba_shares():
    """Rewrite the included shares file and start/stop smbd accordingly."""
    disks = _adopted_disk_sources()
    lines = []
    for src in disks:
        share = src.get("share") or "Musica"
        mp = src.get("mountpoint") or src.get("path")  # "path" for a shared local folder
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
        _publish_smb_discovery(False)
        return
    if smbd:
        _create_samba_user()
        _run(["systemctl", "enable", "--now", "smbd"], timeout=30)
        _run(["systemctl", "reload", "smbd"], timeout=10)
    _publish_smb_discovery(smbd)


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
        return False, _ht('mount.missingIdentifiers', _hlang())
    root = os.path.realpath(root)
    p = os.path.realpath(mountpoint)
    if p != root and not p.startswith(root + os.sep):
        return False, _ht('mount.invalidMountpoint', _hlang())
    os.makedirs(mountpoint, exist_ok=True)
    if os.path.ismount(mountpoint):
        return True, _ht('mount.alreadyMounted', _hlang())

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
        return False, (r.stderr or r.stdout or _ht('mount.genericFailed', _hlang())).strip()

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
    return True, _ht('mount.mounted', _hlang())


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
# USB sticks / external drives are auto-adopted the moment they're plugged
# in: mounted read-write under USB_ADOPTED_ROOT and Samba-shared, with no
# user action needed (see usb_sync() below). This is deliberately more
# aggressive than the "mount read-only, ask before enabling read-write" model
# some similar appliances use — chosen so a device is immediately usable
# without a trip to Settings. The only thing that still needs an explicit
# tap is the (rarer) manual retry for a device whose auto-mount failed, and
# joining Lyrion's actual media library scan ("Apply & rescan"), which stays
# manual so plugging in a stick never interrupts playback with a forced
# Lyrion restart. There used to also be a separate ephemeral, automatic,
# read-only browse mount under /media/hifi-usb so a stick would show up
# before adoption; it was removed because it gave every USB drive two
# different paths (one read-only, one read-write) and users kept pointing
# Lyrion's playlist/media folders at the read-only one, where writes silently
# fail.
_FAT_LIKE = ("vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "msdos")
# Legacy mountpoint root from the removed ephemeral browse mount — kept only
# so _migrate_stale_usb_sources() can recognize and drop old "local" sources
# that pointed into it.
_LEGACY_USB_MOUNT_ROOT = "/media/hifi-usb"
# Latest snapshot from usb_sync(), refreshed by the background usb_monitor thread
# every few seconds — USB devices that still need attention (no filesystem, or
# auto-mount failed). /api/usb serves this instead of running the full lsblk
# scan on every poll (the web UI polls /api/usb every 4s and the monitor
# already scans that often). None = no scan has completed yet.
_usb_state = None


def _fs_mount_type(fstype):
    """Explicit `mount -t` type for a given fstype, used by the adopted
    (internal/USB) read-write mount so it gets a consistent kernel-driver
    mapping rather than relying on autodetection."""
    if fstype == "ntfs":
        return "ntfs3"                       # in-kernel NTFS (no ntfs-3g needed)
    if fstype in ("vfat", "exfat", "ntfs3", "msdos"):
        return fstype
    return "auto"


def _adopted_usb_ids():
    """(partuuid, fsuuid) lowercased sets of already-adopted "usb" sources —
    used to drop them from _usb_partitions() once they're mounted read-write
    under USB_ADOPTED_ROOT, so usb_sync() doesn't try to adopt them again."""
    partuuids, fsuuids = set(), set()
    for s in load_state().get("sources", []):
        if s.get("type") == "usb":
            if s.get("partuuid"):
                partuuids.add(s["partuuid"].lower())
            if s.get("fsuuid"):
                fsuuids.add(s["fsuuid"].lower())
    return partuuids, fsuuids


def _ignored_usb_ids():
    """(partuuid, fsuuid) lowercased sets the user explicitly removed (via
    DELETE /api/sources/<id>) while the device was still connected — kept out
    of auto-adoption so removing a source actually sticks instead of usb_sync()
    silently re-mounting it a few seconds later. Pruned once the device is no
    longer physically present (see usb_sync()), mirroring the client-side
    "forget the dismissal once it's unplugged" behaviour already used for the
    insertion toast in App.jsx."""
    partuuids, fsuuids = set(), set()
    for e in load_state().get("usb_ignored", []):
        if e.get("partuuid"):
            partuuids.add(e["partuuid"].lower())
        if e.get("fsuuid"):
            fsuuids.add(e["fsuuid"].lower())
    return partuuids, fsuuids


def _usb_scan():
    """Every USB block device that could carry a filesystem, no adopted/
    ignored filtering → [{path,name,fstype,label,size,uuid,partuuid}].
    `fstype` is empty/missing for a blank/unformatted device. Handles
    partitioned (sdX1) and whole-disk filesystems; skips optical drives
    (type 'rom'), any non-USB transport (internal SATA/eMMC), and EFI System
    Partitions (see _is_efi_partition) -- a bootable installer stick has one
    alongside its real data partition, and it's never a legitimate music
    source.

    Returns None -- not [] -- when the scan itself failed (lsblk missing,
    timed out, unparseable output). "The scan did not work" and "no USB
    device is plugged in" must never collapse into the same value now that
    usb_sync() *removes* things for devices it no longer sees."""
    try:
        r = _run(["lsblk", "-J", "-o",
                  "PATH,NAME,TYPE,FSTYPE,LABEL,SIZE,TRAN,UUID,PARTUUID,PARTTYPENAME"], timeout=10)
        data = json.loads(r.stdout or "{}")
    except Exception:
        return None
    out = []
    for dev in data.get("blockdevices", []):
        if dev.get("tran") != "usb" or dev.get("type") != "disk":
            continue
        kids = dev.get("children") or []
        if kids:
            out.extend(p for p in kids if p.get("type") == "part" and not _is_efi_partition(p))
        else:
            out.append(dev)
    return out


def _usb_raw_partitions():
    """_usb_scan() with a failed scan flattened to "found nothing" — for the
    callers that only ever enumerate and have no absence to react to."""
    return _usb_scan() or []


def _usb_partitions():
    """USB partitions not yet adopted and not explicitly ignored — the pool
    usb_sync() auto-adopts from and api_usb_adopt() (manual retry) picks
    from."""
    adopted_partuuids, adopted_fsuuids = _adopted_usb_ids()
    ignored_partuuids, ignored_fsuuids = _ignored_usb_ids()
    return [
        p for p in _usb_raw_partitions()
        if (p.get("partuuid") or "").lower() not in adopted_partuuids
        and (p.get("uuid") or "").lower() not in adopted_fsuuids
        and (p.get("partuuid") or "").lower() not in ignored_partuuids
        and (p.get("uuid") or "").lower() not in ignored_fsuuids
    ]


def _usb_key(p):
    return (p.get("partuuid") or p.get("uuid") or p.get("path") or "").lower()


def _detach_source(state, src, remember_ignored):
    """Unmount, unshare and forget one source, in place on `state` — the
    caller holds _lock and does the save. Shared by DELETE /api/sources/<id>
    and by the disconnected-USB cleanup in usb_sync(), so a source is torn
    down exactly the same way whether the user asked for it or the device
    simply vanished.

    `remember_ignored` records the device in `usb_ignored`: right when the
    user removed it by hand and the stick may well still be plugged in
    (without it, usb_sync() auto-adopts the thing back within seconds),
    wrong when the device is already physically gone — there is nothing left
    to suppress, and the entry would only sit there until it is pruned
    again."""
    t = src.get("type")
    if t == "smb":
        umount(src["mountpoint"])
    elif t in ("internal", "usb"):
        ok, lazy = umount_clean(src.get("mountpoint"))
        if not ok:
            print(f"[sources] umount failed for {src.get('mountpoint')}")
        elif lazy:
            print(f"[sources] {src.get('mountpoint')} was busy — detached lazily")
    # Leftover mountpoint directory, for every type — `path` and not just
    # `mountpoint` because that is how these usually present: a stale Lyrion
    # mediadir pointing at the mountpoint of a device long unplugged,
    # re-imported by _sync_from_lyrion() as a `local` source. The call is
    # inert anywhere else (SMB mounts, a real music folder): it only ever
    # touches an empty, unmounted directory under the two roots we create
    # ourselves.
    _drop_adopted_mountpoint(src.get("mountpoint") or src.get("path"))
    if t == "usb" and remember_ignored:
        # Auto-adoption (usb_sync()) would otherwise re-mount this within a
        # few seconds, since the device is still plugged in and no longer in
        # `sources`. Remember it as ignored until it's unplugged (pruned
        # there once it's gone).
        state.setdefault("usb_ignored", []).append(
            {"partuuid": src.get("partuuid"), "fsuuid": src.get("fsuuid")})
    state["sources"] = [s for s in state.get("sources", []) if s.get("id") != src.get("id")]


# In-memory backoff for failed auto-adopt attempts: _usb_key(part) -> (last
# attempt time (monotonic), error message). Stops a stubbornly-broken
# filesystem from spamming `mount`/the logs on every usb_monitor() tick;
# cleared once the device is no longer plugged in.
_usb_fail_backoff = {}
_USB_RETRY_BACKOFF = 15

# How long a USB device has to stay unseen before usb_sync() acts on its
# absence, and when each currently-missing identifier was first missed.
_USB_GONE_GRACE = 30
_usb_missing_since = {}


def _usb_gone_for_good(ids, raw_ids):
    """True once every identifier in `ids` has been missing from the USB scan
    for _USB_GONE_GRACE seconds straight. Any scan that sees the device again
    clears its timer.

    The grace period is the whole point. sources_server is up well before
    udev has finished enumerating USB, so the first scans after a reboot come
    back empty for perfectly healthy hardware — acting on that immediately
    would delete every adopted USB source on every single boot, and throw
    away the usb_ignored entries whose only job is to stop a hand-removed
    stick from being auto-adopted seconds later. A device with no identifier
    at all is never considered gone: there is nothing to match it by, so its
    absence can't be told apart from a scan that simply reports less."""
    ids = [i.lower() for i in ids if i]
    if not ids:
        return False
    if any(i in raw_ids for i in ids):
        for i in ids:
            _usb_missing_since.pop(i, None)
        return False
    now = time.monotonic()
    return now - min(_usb_missing_since.setdefault(i, now) for i in ids) >= _USB_GONE_GRACE


def _drop_disconnected_usb(state, raw_ids):
    """Forget every adopted USB source whose device is no longer physically
    there — the stick pulled out without going through "Remove" first.

    Left alone, such a source stays in Music Sources for good: red and
    unmounted, its Samba share still declared, and its mountpoint still in
    Lyrion's mediadirs pointing at an empty directory — which is exactly what
    makes the next library scan prune those tracks, and what
    _sync_from_lyrion() later re-imports as a bogus `local` source once the
    directory outlives the source (see _drop_adopted_mountpoint()). Tearing
    it down the same way an explicit removal does — same _detach_source(),
    same live mediadir drop, no Lyrion restart — is the only state that
    matches reality.

    A drive merely unplugged for a while therefore does go away, and comes
    back on its own once it is plugged in again: auto-adoption is the normal
    path for every healthy USB device, and it reuses the same share name and
    mountpoint (see _existing_adopted_source()).

    Caller holds _lock. Returns True if anything was dropped."""
    gone = [
        s for s in state.get("sources", [])
        if s.get("type") == "usb"
        and _usb_gone_for_good((s.get("partuuid"), s.get("fsuuid")), raw_ids)
    ]
    if not gone:
        return False
    for src in gone:
        _detach_source(state, src, remember_ignored=False)
        print(f"[sources] USB source dropped, device disconnected: "
              f"{src.get('name')} ({src.get('mountpoint')})")
    save_state(state)
    regen_samba_shares()
    # Lyrion last and still inside the lock, exactly as api_remove() does: a
    # GET /api/sources landing between the save and this call would see a
    # mediadir belonging to no source and re-import it as a `local` one.
    roots = [r for src in gone for r in _source_lyrion_roots(src)]
    if roots:
        try:
            _lyrion_remove_mediadir_live(roots)
        except Exception as e:
            print(f"[sources] could not drop {roots} from Lyrion mediadirs: {e}")
    return True


def _remount_reconnected_usb(raw_ids):
    """Re-mount an already-adopted USB source whose device has just
    reappeared (unplugged, then plugged back in). usb_sync()'s adoption loop
    below never touches it: _usb_partitions() explicitly excludes anything
    already in the adopted set, so without this a reconnected drive stayed
    "not mounted" — requiring the user to open Settings and press "Apply &
    rescan library" (which doesn't even mount anything itself, it only checks
    and refuses if a disk isn't mounted) — until the whole box was next
    rebooted (remount_all_retry only ever runs once, at startup). Mirrors
    _adopt_usb_partition()'s post-mount step (live mediadir add, no Lyrion
    restart) but skips the state/Samba-share writes, which are already in
    place for a source that's merely reconnecting, not being adopted fresh."""
    for src in load_state().get("sources", []):
        if src.get("type") != "usb":
            continue
        ids = [i.lower() for i in (src.get("partuuid"), src.get("fsuuid")) if i]
        mountpoint = src.get("mountpoint")
        if not any(i in raw_ids for i in ids) or not mountpoint or os.path.ismount(mountpoint):
            continue
        ok, msg = mount_usb_adopted(src)
        if not ok:
            print(f"[sources] reconnected USB remount failed for {src.get('name')}: {msg}")
            continue
        print(f"[sources] reconnected USB source remounted: {src.get('name')}")
        try:
            _lyrion_add_mediadir_live(mountpoint)
        except Exception as e:
            print(f"[sources] live mediadir add/rescan failed for {mountpoint}: {e}")


def usb_sync():
    """Auto-adopt every USB partition with a recognized filesystem as soon as
    it's seen (mount read-write + Samba share — see _adopt_usb_partition()),
    no user action needed. Partitions with no filesystem, or whose last
    auto-adopt attempt failed, are left for /api/usb to surface as "needs
    attention" instead. Also drops sources whose device has been physically
    disconnected, and prunes usb_ignored entries for devices no longer
    present. Publishes the needs-attention list to _usb_state for /api/usb to
    read cheaply."""
    global _usb_state
    with _lock:
        raw = _usb_scan()
        # Everything below that reacts to a device being *absent* runs only
        # on a scan that actually worked — see _usb_scan()'s None contract.
        scan_ok = raw is not None
        raw = raw or []
        raw_keys = {_usb_key(p) for p in raw}
        # Both identifiers of every device present, not just the one
        # _usb_key() picks: a source stores partuuid *and* fsuuid, and it is
        # still plugged in if either of them turns up.
        raw_ids = {v.lower() for p in raw
                   for v in (p.get("partuuid"), p.get("uuid")) if v}

        if scan_ok:
            state = load_state()
            _drop_disconnected_usb(state, raw_ids)
            ignored = state.get("usb_ignored", [])
            still_present = [
                e for e in ignored
                if not _usb_gone_for_good((e.get("partuuid"), e.get("fsuuid")), raw_ids)
            ]
            if len(still_present) != len(ignored):
                state["usb_ignored"] = still_present
                save_state(state)

            for key in list(_usb_fail_backoff):
                if key not in raw_keys:
                    _usb_fail_backoff.pop(key, None)

    # _adopt_usb_partition() takes _lock itself (a plain, non-reentrant
    # threading.Lock()) to save state, so it must run outside the block
    # above — calling it while already holding _lock here previously
    # self-deadlocked the whole thread on the very first successful mount:
    # mount_usb_adopted() succeeded (so the drive showed up mounted), but
    # the thread then hung forever trying to re-acquire _lock to persist
    # that source, silently — no exception, no log — and every other part of
    # the service that needs _lock (adding/removing sources, etc.) froze
    # right along with it until the process was restarted.
    _remount_reconnected_usb(raw_ids)

    needs_attention = []
    for p in _usb_partitions():
        if not p.get("fstype"):
            needs_attention.append({**p, "needs_format": True})
            continue
        key = _usb_key(p)
        last_ts, last_msg = _usb_fail_backoff.get(key, (None, None))
        if last_ts is not None and time.monotonic() - last_ts < _USB_RETRY_BACKOFF:
            needs_attention.append({**p, "error": last_msg})
            continue
        ok, msg, _src = _adopt_usb_partition(p)
        if not ok:
            if key not in _usb_fail_backoff:
                print(f"[sources] auto-adopt failed for {p.get('path')}: {msg}")
            _usb_fail_backoff[key] = (time.monotonic(), msg)
            needs_attention.append({**p, "error": msg})

    _usb_state = needs_attention
    return needs_attention


def _migrate_stale_usb_sources():
    """One-time startup cleanup: drop "local" sources whose path lives under
    the removed ephemeral read-only USB browse mount (_LEGACY_USB_MOUNT_ROOT).
    That mountpoint is never recreated anymore, so these are permanently dead
    — left in place they'd keep getting handed to Lyrion as nonexistent
    mediadirs on every apply. No-op once a device has been upgraded once."""
    with _lock:
        state = load_state()
        prefix = _LEGACY_USB_MOUNT_ROOT + os.sep
        stale = [
            s for s in state.get("sources", [])
            if s.get("type") == "local"
            and (s.get("path") or "").startswith(prefix)
        ]
        if not stale:
            return
        stale_ids = {s.get("id") for s in stale}
        state["sources"] = [s for s in state["sources"] if s.get("id") not in stale_ids]
        save_state(state)
    for s in stale:
        print(f"[sources] dropped stale local source under {_LEGACY_USB_MOUNT_ROOT}: {s.get('path')}")


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


def _lyrion_present():
    """Whether a LOCAL Lyrion exists on this device at all.

    Deliberately NOT `bool(_find_prefs())`. server.prefs only appears the first
    time Lyrion actually RUNS, so on a device where the setup wizard has just
    installed the package — which is exactly the moment the wizard then asks
    about the web-player skin — prefs are still missing and the prefs-based
    check reported "Lyrion is not installed on this device" about a Lyrion that
    was installed and simply had not started yet.

    Ask dpkg (then the unit) instead, and leave the waiting to _ensure_prefs().
    A device in external/"follow" mode still answers False here, which is the
    case the message was written for."""
    if _find_prefs():
        return True
    try:
        r = _run(["dpkg-query", "-W", "-f=${db:Status-Status}", "lyrionmusicserver"])
        if r.returncode == 0 and (r.stdout or "").strip() == "installed":
            return True
    except Exception:
        pass
    try:
        r = _run(["systemctl", "list-unit-files", LYRION_SERVICE])
        return r.returncode == 0 and LYRION_SERVICE in (r.stdout or "")
    except Exception:
        return False


def _squeezebox_ids():
    """(uid, gid) of the squeezeboxserver user, or (None, None)."""
    try:
        import pwd
        ent = pwd.getpwnam("squeezeboxserver")
        return ent.pw_uid, ent.pw_gid
    except Exception:
        return None, None


def _make_playlist_folder(target):
    """Create `target` if needed and hand it to the Lyrion user, so "save queue
    as playlist" can actually write there. Shared by the automatic provisioning
    below and the user-picked folder (/api/playlistdir)."""
    uid, gid = _squeezebox_ids()
    try:
        os.makedirs(target, exist_ok=True)
        if uid is not None:
            os.chown(target, uid, gid)
    except Exception as e:
        print(f"[sources] playlistdir mkdir failed: {e}")
        return False
    return os.path.isdir(target)


def _provision_playlistdir(data):
    """Given the loaded prefs dict, make sure `playlistdir` points at an
    existing, writable folder (creating/chowning it). Returns the (possibly
    updated) dict and a bool telling whether anything changed."""
    cur = (data.get("playlistdir") or "").strip()
    if cur and os.path.isdir(cur) and os.access(cur, os.W_OK):
        return data, False
    target = cur or DEFAULT_PLAYLISTDIR
    if not _make_playlist_folder(target):
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


# Tailscale's CGNAT range (100.64.0.0/10) isn't RFC1918, so appending it to
# Lyrion's allowedHosts allow-list still left some Settings/config pages
# unreachable for Tailscale-only clients (e.g. Lyrplay) -- LMS applies host
# filtering in more than one place, not just that one pref. Since nothing on
# the Osmium side restricts :9000 anyway (no firewall/reverse-proxy, see
# webui_server.py), Lyrion's own IP filter buys this appliance no security,
# so just turn it off outright instead of chasing every allow-list.
def _disable_ip_filtering(data):
    """Given the loaded prefs dict, turn OFF Lyrion's IP-based access control
    (filterHosts) if the operator has it turned on. Returns the (possibly
    updated) dict and a bool telling whether anything changed."""
    if not data.get("filterHosts"):
        return data, False
    data["filterHosts"] = 0
    return data, True


def ensure_lms_trusted_networks():
    """Standalone provisioning used at service start, same pattern as
    ensure_playlistdir(): idempotent, only stops/edits/starts Lyrion when
    something actually needs to change."""
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
    data, changed = _disable_ip_filtering(data)
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
        print(f"[sources] lms trusted-networks prefs write failed: {e}")
    finally:
        _run(["systemctl", "start", LYRION_SERVICE], timeout=60)
    print(f"[sources] disabled Lyrion's IP-based access control (filterHosts)")


# ─────────────────────────── LMS skin (Osmium / Material) ───────────────────
# The appliance ships an "Osmium" look for Lyrion's web UI, built as a custom
# theme + global css on top of the third-party Material Skin plugin (never a
# from-scratch LMS skin). The user's choice lives in LMS_SKIN_FILE:
#   osmium   → Material installed, root skin = material, global Osmium css on
#   material → Material installed, root skin = material, global css removed
#   (absent) → "unset": legacy device, nothing about its skin is ever touched,
#              except that Material itself gets auto-installed (user decision
#              2026-08-19) so the /material/ web remote the kiosk QR already
#              points at actually works.
LMS_SKIN_FILE = "/etc/hifi-player/lms-skin"
LMS_SKIN_ASSET_DIRS = [
    "/usr/local/share/hifi-lms-skin",
    # Dev checkout fallback: the committed source of the same assets.
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "distro",
                 "config", "includes.chroot", "usr", "local", "share",
                 "hifi-lms-skin"),
]
LMS_SKIN_MARKER = "managed-by: osmium-appliance"
# Material's documented hook for adding entries to its own menus: a json file
# in the same prefs dir as the theme/css above. Each entry lands in the section
# it is listed under ("settings" = the Impostazioni block of the nav drawer),
# and an entry with an "iframe" url opens that url in Material's built-in
# dialog — which is how the appliance gets an "Osmium Admin" button into Lyrion
# without patching a single Material file (so it survives Material updates).
# The file belongs to the user as much as to us: we own exactly the entries
# whose id starts with LMS_SKIN_ACTION_ID_PREFIX and merge them into whatever
# else is already in there.
LMS_SKIN_ACTIONS_FILE = "actions.json"
LMS_SKIN_ACTION_ID_PREFIX = "osmium-"
LMS_PLUGIN_REPO_XML = \
    "https://lms-community.github.io/lms-plugin-repository/extensions.xml"
# The repository is served from GitHub Pages, which answers 403 to urllib's
# default "Python-urllib/3.x" User-Agent (verified 2026-08-20 against the live
# host, from the appliance and from a dev machine: default UA → 403, any other
# UA → 200). Without this every repo lookup failed and Material only ever
# installed from the pinned fallback below — silently, since the failure just
# logged and fell through. Any non-default UA works; this one says who we are.
LMS_HTTP_UA = "Osmium-Sound/1.0 (+https://osmiumsound.it)"
# Last-resort pinned Material release, used only when the repo XML is
# unreachable/unparseable. sha is SHA1 — that is what LMS's own
# PluginDownloader verifies, and what the repo XML publishes.
LMS_MATERIAL_FALLBACK = (
    "https://github.com/CDrummond/lms-material/releases/download/6.4.6/lms-material-6.4.6.zip",
    "8e7830a148acab4971b9acd0654ae2cee6254521",
)
# Pinned last-resort releases, by plugin name. Only Material has one: it is the
# single plugin this appliance MUST be able to install even with the repo
# unreachable (the whole web UI hangs off it). Everything else simply fails and
# stays offered for a later retry.
LMS_PLUGIN_FALLBACKS = {"MaterialSkin": LMS_MATERIAL_FALLBACK}

# ── LMS first-run setup (the wizard hand-off) ───────────────────────────────
# Lyrion ships its own setup wizard and redirects every visit to :9000 into it
# until server.prefs' `wizardDone` is 1 (Slim/Web/Settings/Server/Wizard.pm).
# That wizard asks four things — language, which plugins to install, the music
# folder, the playlist folder — and this appliance already answers three of
# them (Sources owns mediadirs, ensure_playlistdir() owns playlistdir, the skin
# step owns Material). So the Osmium wizard asks the one remaining question in
# a step of its own and finalises Lyrion through /api/lms_setup, instead of
# handing the user over to a second, redundant wizard.
#
# The offered list mirrors Lyrion's own recommendations
# (HTML/EN/settings/wizard.json) minus MaterialSkin (always installed, see the
# skin section above) and minus Analytics (opt-in telemetry — see below).
LMS_SETUP_PLUGINS = [           # (id, ticked by default)
    ("MusicArtistInfo", True),  # Lyrion ticks this one by default too
    ("Spotty", False),
    ("TIDAL", False),
    ("Qobuz", False),
    ("Deezer", False),
    ("RadioNowPlaying", False),
    ("RadioNet", False),
]
# Bundled inside Lyrion itself (Slim/Plugin/<name>/), so there is nothing to
# download: these are switched on by writing 'needs-enable' into their plugin
# state, which LMS turns into 'enabled' on its next start
# (Slim/Utils/PluginManager.pm::_needsEnable). Analytics is the usage report to
# stats.lms-community.org; it ships `defaultState: disabled` and the wizard
# only ever enables it on an explicit, unticked-by-default opt-in.
LMS_ANALYTICS_PLUGIN = "Analytics"
LMS_BUILTIN_PLUGINS = {LMS_ANALYTICS_PLUGIN}
LMS_WIZARD_DONE_PREF = "wizardDone"

_SKIN_LOCK = threading.Lock()
_SKIN_STATUS = {"state": "idle"}
# Serializes the actual install/apply work (user-triggered apply thread vs the
# startup autoinstall thread) — both stop/start Lyrion, so they must not
# overlap. _SKIN_LOCK above only guards the status dict.
_SKIN_JOB_LOCK = threading.Lock()
# Same split for the LMS first-run setup job: its own status dict + lock, but
# the SAME _SKIN_JOB_LOCK for the work itself — it stops/starts Lyrion just
# like the skin job does, and the two must never overlap.
_LMS_SETUP_LOCK = threading.Lock()
_LMS_SETUP_STATUS = {"state": "idle"}


def _skin_status():
    with _SKIN_LOCK:
        return dict(_SKIN_STATUS)


def _skin_status_set(state, progress, code, **extra):
    payload = {"state": state, "progress": progress, "code": code,
               "message": _m(code)}
    payload.update(extra)
    with _SKIN_LOCK:
        _SKIN_STATUS.clear()
        _SKIN_STATUS.update(payload)


def _skin_job_running():
    return _skin_status().get("state") in ("installing", "applying")


def _lms_skin_choice():
    try:
        with open(LMS_SKIN_FILE) as f:
            v = f.read().strip()
        return v if v in ("osmium", "material") else None
    except OSError:
        return None


def _skin_asset_dir():
    for d in LMS_SKIN_ASSET_DIRS:
        if os.path.isdir(d):
            return d
    return None


def _plugin_prefs_dir():
    """<prefsdir>/plugin — where Lyrion keeps state.prefs/extensions.prefs."""
    prefs = _find_prefs()
    return os.path.join(os.path.dirname(prefs), "plugin") if prefs else None


def _plugin_state(name):
    """`name`'s value in Lyrion's plugin/state.prefs ('enabled', 'disabled',
    'needs-install', …), or None when the file/key isn't there."""
    d = _plugin_prefs_dir()
    if not d:
        return None
    try:
        import yaml
        with open(os.path.join(d, "state.prefs")) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return None
    v = data.get(name)
    return v if isinstance(v, str) else None


def _builtin_plugin_enabled(name):
    """Built-in plugins never land in InstalledPlugins/ — their state file is
    the only record of whether they're on. 'needs-enable' counts as on: it is
    the transition state LMS resolves to 'enabled' on its next start."""
    return _plugin_state(name) in ("enabled", "needs-enable")


def _plugin_installed(name):
    if name in LMS_BUILTIN_PLUGINS:
        return _builtin_plugin_enabled(name)
    cache = _lyrion_cache_dir()
    if not cache:
        return False
    return os.path.isfile(os.path.join(
        cache, "InstalledPlugins", "Plugins", name, "install.xml"))


def _material_installed():
    return _plugin_installed("MaterialSkin")


def _material_skin_dir():
    """<prefsdir>/material-skin — where Material looks for user themes/css."""
    prefs = _find_prefs()
    if not prefs:
        return None
    return os.path.join(os.path.dirname(prefs), "material-skin")


def _lms_skin_applied(choice):
    """Whether the stored choice is fully reflected on disk (drives the
    Settings UIs' retry affordance)."""
    if not choice or not _material_installed():
        return False
    ms = _material_skin_dir()
    if not ms:
        return False
    desktop = os.path.join(ms, "css", "desktop.css")
    managed = _is_skin_managed_css(desktop)
    return managed if choice == "osmium" else not managed


def _is_skin_managed_css(path):
    """True when `path` is a css file this appliance wrote (marker header).
    A user's own hand-made custom css never carries the marker and is never
    deleted by us."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return LMS_SKIN_MARKER in f.read(512)
    except OSError:
        return False


def _plugin_repo_entry(name):
    """`name`'s (zip_url, sha1) from the official LMS plugin repository — the
    same metadata LMS's own extension manager consumes."""
    req = urllib.request.Request(LMS_PLUGIN_REPO_XML,
                                 headers={"User-Agent": LMS_HTTP_UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        xml = resp.read(8 * 1024 * 1024).decode("utf-8", "replace")
    m = re.search(r'<plugin\s+[^>]*\bname="%s"[^>]*>' % re.escape(name), xml)
    if not m:
        raise ValueError(f"{name} not found in plugin repository")
    tag = m.group(0)
    url = re.search(r'\burl="([^"]+)"', tag)
    sha = re.search(r'\bsha="([0-9a-fA-F]{40})"', tag)
    # A sha1 is mandatory; the zip URL itself may be plain http. Several
    # community plugins host their releases that way (RadioNowPlaying, for
    # one), and refusing them outright would mean offering a plugin that can
    # never install. Integrity does not rest on the payload's transport: the
    # manifest that carries the sha1 comes over HTTPS, and the download is
    # checked against it (_download_plugin_zip), so a tampered zip is rejected
    # whatever the wire looked like. This is exactly the model LMS's own
    # Slim::Utils::PluginDownloader uses for the same repository.
    if not url or not sha or not re.match(r'https?://', url.group(1)):
        raise ValueError(f"{name} repo entry malformed")
    return url.group(1), sha.group(1).lower()


def _yaml_pref_edit(path, mutate):
    """Load one plugin prefs YAML (missing file → {}), run mutate(dict) → bool
    changed, write back atomically + chown to the Lyrion user. Caller is
    responsible for Lyrion being stopped (prefs are rewritten from memory on
    exit — see _stop_lyrion)."""
    import yaml
    data = {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except OSError:
        pass
    if not mutate(data):
        return False
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    os.replace(tmp, path)
    _chown_lyrion([path])
    return True


def _download_plugin_zip(name, cache):
    """sha1-verified download of `name`'s zip into <cache>/DownloadedPlugins/,
    where LMS's own PluginManager picks it up on its next start. Returns the
    zip path; raises on any lookup/download/verification failure."""
    try:
        url, sha = _plugin_repo_entry(name)
    except Exception as e:
        fallback = LMS_PLUGIN_FALLBACKS.get(name)
        if not fallback:
            raise
        print(f"[sources] lms-plugins: {name} repo lookup failed ({e}), "
              "using pinned fallback")
        url, sha = fallback
    dl_dir = os.path.join(cache, "DownloadedPlugins")
    os.makedirs(dl_dir, exist_ok=True)
    zip_path = os.path.join(dl_dir, f"{name}.zip")
    tmp = zip_path + ".tmp"
    req = urllib.request.Request(url, headers={"User-Agent": LMS_HTTP_UA})
    h = hashlib.sha1()
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            h.update(chunk)
            out.write(chunk)
            if out.tell() > 64 * 1024 * 1024:
                raise ValueError(f"{name} download too large")
    if h.hexdigest().lower() != sha:
        os.remove(tmp)
        raise ValueError(f"{name} download sha1 mismatch")
    os.replace(tmp, zip_path)
    _chown_lyrion([zip_path])
    return zip_path


def _ensure_plugins_installed(names, builtin_states=None):
    """Install `names` and set the on/off state of the built-in plugins in
    `builtin_states` ({name: bool}) — all inside ONE Lyrion stop/start, because
    prefs written under a running server are overwritten from memory when it
    exits (see _stop_lyrion).

    Deterministic install path via LMS's own needs-install mechanism
    (validated live on the test device, 2026-08-19):

      1. sha1-verified zip → <cache>/DownloadedPlugins/<name>.zip
      2. plugin/state.prefs:      <name>: needs-install
         plugin/extensions.prefs: plugin: {<name>: 1}  (so the extension
         manager keeps managing/updating it afterwards)
      3. restart Lyrion → its PluginManager extracts and enables the plugin

    Merely seeding extensions.prefs does NOT work: at startup LMS prunes
    selected-but-missing plugins from that list instead of re-downloading them
    (Slim::Utils::ExtensionsManager "failed to download... let's not re-try").

    Built-in plugins (LMS_BUILTIN_PLUGINS) skip all of that: they ship inside
    Lyrion, so they only need a state of 'needs-enable' (→ 'enabled' on the
    next start) or 'disabled'.

    Returns (installed, failed). A download that fails costs only its own
    plugin — the rest still go in — so an offline device gets what it can and
    the user can retry the others later from Lyrion. Raises nothing."""
    builtin_states = dict(builtin_states or {})
    prefs = _ensure_prefs()
    cache = _lyrion_cache_dir()
    if not prefs or not cache:
        print("[sources] lms-plugins: no local Lyrion — nothing to install")
        return [], list(names) + list(builtin_states)

    installed, failed, to_seed = [], [], []
    for name in names:
        if name in LMS_BUILTIN_PLUGINS:
            # Callers pass built-ins through `builtin_states`; ignore them here
            # rather than trying to download something that has no zip.
            continue
        if _plugin_installed(name):
            installed.append(name)
            continue
        try:
            _download_plugin_zip(name, cache)
            to_seed.append(name)
        except Exception as e:
            print(f"[sources] lms-plugins: {name} download failed: {e}")
            failed.append(name)

    # Only touch prefs whose state actually has to change: an unnecessary
    # stop/start would interrupt playback for nothing.
    builtin_todo = {n: bool(on) for n, on in builtin_states.items()
                    if _plugin_state(n) != ("enabled" if on else "disabled")}
    if not to_seed and not builtin_todo:
        return installed, failed

    plugin_prefs_dir = os.path.join(os.path.dirname(prefs), "plugin")
    os.makedirs(plugin_prefs_dir, exist_ok=True)
    _stop_lyrion()
    try:
        now = int(time.time())

        def set_state(data):
            for name in to_seed:
                data[name] = "needs-install"
                data["_ts_" + name] = now
            for name, on in builtin_todo.items():
                data[name] = "needs-enable" if on else "disabled"
                data["_ts_" + name] = now
            return True

        def set_selected(data):
            plugins = data.get("plugin")
            if not isinstance(plugins, dict):
                plugins = {}
            for name in to_seed:
                plugins[name] = 1
            data["plugin"] = plugins
            data["_ts_plugin"] = now
            return True

        _yaml_pref_edit(os.path.join(plugin_prefs_dir, "state.prefs"),
                        set_state)
        if to_seed:
            _yaml_pref_edit(os.path.join(plugin_prefs_dir, "extensions.prefs"),
                            set_selected)
    except Exception as e:
        print(f"[sources] lms-plugins: seeding plugin prefs failed: {e}")
        failed += [n for n in to_seed if n not in failed]
        to_seed = []
    finally:
        _start_lyrion()

    for _ in range(60):  # up to ~120s
        if all(_plugin_installed(n) for n in to_seed):
            break
        time.sleep(2)
    for name in to_seed:
        (installed if _plugin_installed(name) else failed).append(name)
    if failed:
        print(f"[sources] lms-plugins: not installed: {', '.join(failed)}")
    return installed, failed


def _ensure_material_installed():
    """Material Skin specifically: install it if missing, then wait until it
    actually serves /material/ — the plugin appearing on disk is a moment
    earlier than its web endpoint being up, and the skin is only usable once
    the latter is true. Returns True when Material is installed and serving.
    Raises nothing — errors are printed and reported as False."""
    if _material_installed():
        return True
    try:
        installed, _ = _ensure_plugins_installed(["MaterialSkin"])
        if "MaterialSkin" not in installed:
            return False
        for _ in range(60):  # up to ~120s
            try:
                req = urllib.request.Request(
                    "http://127.0.0.1:9000/material/", method="HEAD")
                with urllib.request.urlopen(req, timeout=3):
                    return True
            except Exception:
                time.sleep(2)
        print("[sources] lms-skin: Material did not come up after install")
        return False
    except Exception as e:
        print(f"[sources] lms-skin: Material install failed: {e}")
        return False


def _install_skin_theme_files(choice):
    """Sync the Osmium theme/css files (and our custom-action entries) under
    <prefsdir>/material-skin.

    Always installs themes/dark/Osmium.css (a harmless extra entry in
    Material's own theme picker). The global css/desktop.css + css/mobile.css
    — the lever that restyles EVERY client — are written only for the
    'osmium' choice and removed (only if marker-managed) for 'material'.
    choice=None (unset/legacy device) leaves the global css alone entirely.

    Returns True when the sync actually ran, False when it could not. The
    caller MUST honour False: this used to return None silently, so a device
    missing the asset dir still reported "Skin applied." while installing
    nothing at all — which is exactly how the OTA never shipping
    /usr/local/share (see hifi-system-update.sh) stayed invisible."""
    src = _skin_asset_dir()
    ms = _material_skin_dir()
    if not src:
        print("[sources] lms-skin: asset dir missing "
              f"(looked in {LMS_SKIN_ASSET_DIRS}) — nothing to install")
        return False
    if not ms:
        print("[sources] lms-skin: no Lyrion prefs dir found — cannot install")
        return False
    uid, gid = _squeezebox_ids()

    def put(rel_src, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(src, rel_src), dest)
        try:
            os.chmod(dest, 0o644)
            if uid is not None:
                os.chown(dest, uid, gid)
        except OSError:
            pass

    # Material must be able to traverse the tree; _chown_lyrion's 0640 is for
    # single prefs files, dirs need to stay listable.
    for d in (ms, os.path.join(ms, "themes"), os.path.join(ms, "themes", "dark"),
              os.path.join(ms, "css")):
        try:
            os.makedirs(d, exist_ok=True)
            os.chmod(d, 0o755)
            if uid is not None:
                os.chown(d, uid, gid)
        except OSError:
            pass
    put(os.path.join("themes", "Osmium.css"),
        os.path.join(ms, "themes", "dark", "Osmium.css"))
    if choice == "osmium":
        put(os.path.join("css", "desktop.css"), os.path.join(ms, "css", "desktop.css"))
        put(os.path.join("css", "mobile.css"), os.path.join(ms, "css", "mobile.css"))
    elif choice == "material":
        for name in ("desktop.css", "mobile.css"):
            path = os.path.join(ms, "css", name)
            if _is_skin_managed_css(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
    # Menu entry, not styling: installed for every choice (and for unset
    # devices, like the theme file above) — it is what puts the appliance's own
    # web admin one tap away from Lyrion's UI.
    _install_skin_actions(src, ms, uid, gid)
    return True


def _install_skin_actions(src, ms, uid, gid):
    """Merge our entries into Material's custom-actions file
    (<prefsdir>/material-skin/actions.json).

    Additive by design: entries already in the file are kept, ours (id prefixed
    with LMS_SKIN_ACTION_ID_PREFIX) are replaced, so a user's own custom actions
    survive every re-sync. Material eval()s this file, which means it is allowed
    to hold hand-written javascript rather than strict json — anything we cannot
    parse is left exactly as it is instead of being overwritten.

    Failures here never fail the skin sync: the theme is the contract, this
    button is a convenience on top of it."""
    dest = os.path.join(ms, LMS_SKIN_ACTIONS_FILE)
    try:
        with open(os.path.join(src, LMS_SKIN_ACTIONS_FILE), encoding="utf-8") as f:
            ours = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[sources] lms-skin: no usable {LMS_SKIN_ACTIONS_FILE} asset ({e})")
        return
    current = {}
    if os.path.exists(dest):
        try:
            with open(dest, encoding="utf-8") as f:
                current = json.load(f)
        except (OSError, ValueError) as e:
            print(f"[sources] lms-skin: {dest} is not plain json — left alone ({e})")
            return
        if not isinstance(current, dict):
            print(f"[sources] lms-skin: unexpected shape in {dest} — left alone")
            return
    merged = {k: v for k, v in current.items()}
    for section, entries in ours.items():
        existing = merged.get(section, [])
        if not isinstance(existing, list):
            print(f"[sources] lms-skin: section '{section}' in {dest} is not a "
                  "list — left alone")
            continue
        merged[section] = [e for e in existing
                           if not _is_osmium_action(e)] + entries
    if merged == current:
        return
    try:
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, dest)
        os.chmod(dest, 0o644)
        if uid is not None:
            os.chown(dest, uid, gid)
        print(f"[sources] lms-skin: custom actions written to {dest}")
    except OSError as e:
        print(f"[sources] lms-skin: could not write {dest}: {e}")


def _is_osmium_action(entry):
    return (isinstance(entry, dict)
            and str(entry.get("id", "")).startswith(LMS_SKIN_ACTION_ID_PREFIX))


def _get_lms_pref(key, default=None):
    """Read one server.prefs pref. Live JSON-RPC first — Lyrion keeps prefs in
    memory and only flushes them to disk periodically, so a running server is
    the authoritative source — with the prefs file as the fallback for when it
    isn't running."""
    try:
        v = _lyrion_request(["pref", key, "?"]).get("_p2")
        if v is not None:
            return v
    except Exception:
        pass
    prefs = _find_prefs()
    if not prefs:
        return default
    try:
        import yaml
        with open(prefs) as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return default
    v = data.get(key)
    return default if v is None else v


def _set_lms_pref(key, value):
    """Write one server.prefs pref. Live JSON-RPC first (no restart, LMS
    persists it on its own); stop→edit→start fallback when LMS isn't
    reachable."""
    try:
        _lyrion_request(["pref", key, value])
        return True
    except Exception:
        pass
    prefs = _find_prefs()
    if not prefs:
        return False
    try:
        import yaml
        _stop_lyrion()
        try:
            with open(prefs) as f:
                data = yaml.safe_load(f) or {}
            data[key] = value
            tmp = prefs + ".tmp"
            with open(tmp, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False,
                               allow_unicode=True)
            os.replace(tmp, prefs)
            _chown_lyrion([prefs])
        finally:
            _start_lyrion()
        return True
    except Exception as e:
        print(f"[sources] lms pref write failed ({key}): {e}")
        return False


def _set_root_skin_material():
    """Make :9000/ serve Material instead of the classic Default skin."""
    return _set_lms_pref("skin", "material")


def _lms_skin_apply(choice):
    """Worker thread behind POST /api/lms_skin. Every step idempotent."""
    try:
        _skin_status_set("installing", 10, "msg.skinInstalling")
        with _SKIN_JOB_LOCK:
            # Lyrion may have been installed minutes ago by the setup wizard and
            # never started, in which case there is no prefs dir yet for Material
            # or the theme files to land in. Start it and wait here, inside the
            # lock, so every step below has one.
            if not _ensure_prefs():
                _skin_status_set("error", 0, "msg.skinLmsMissing")
                return
            if not _ensure_material_installed():
                _skin_status_set("error", 0, "msg.skinInstallFailed")
                return
            _skin_status_set("applying", 70, "msg.skinApplying")
            if not _install_skin_theme_files(choice):
                _skin_status_set("error", 0, "msg.skinApplyFailed")
                return
            if not _set_root_skin_material():
                _skin_status_set("error", 0, "msg.skinApplyFailed")
                return
        _skin_status_set("done", 100, "msg.skinApplied")
    except Exception as e:
        print(f"[sources] lms-skin apply failed: {e}")
        _skin_status_set("error", 0, "msg.skinApplyFailed")


def _lms_skin_autoinstall():
    """Startup convergence thread (user requirement 2026-08-19: Material gets
    installed automatically whenever missing). Waits for a local LMS, then
    ensures Material + the Osmium theme file exist, and re-syncs the global
    css to the stored choice if there is one. Never touches the root `skin`
    pref or the global css on 'unset' devices — their look must not change
    until the user actively picks a skin. Exits once converged; retries with
    backoff while offline (boot without network)."""
    delays = [60, 300, 1800, 21600]
    attempt = 0
    while True:
        try:
            if _find_prefs() and not _skin_job_running() \
                    and _restore_status().get("state") in ("idle", "done", "error") \
                    and _SKIN_JOB_LOCK.acquire(blocking=False):
                try:
                    # Only treat this as converged when the sync really ran:
                    # returning here on a False would strand a device that has
                    # the code but not the asset dir (it would never retry,
                    # and /api/lms_skin would report applied=false forever).
                    if _ensure_material_installed() \
                            and _install_skin_theme_files(_lms_skin_choice()):
                        print("[sources] lms-skin: converged "
                              f"(choice={_lms_skin_choice() or 'unset'})")
                        return
                finally:
                    _SKIN_JOB_LOCK.release()
        except Exception as e:
            print(f"[sources] lms-skin autoinstall error: {e}")
        time.sleep(delays[min(attempt, len(delays) - 1)])
        attempt += 1


@app.route("/api/lms_skin", methods=["GET"])
def api_lms_skin_get():
    choice = _lms_skin_choice()
    return jsonify({
        "success": True,
        "skin": choice or "unset",
        "lms_installed": _lyrion_present(),
        "material_installed": _material_installed(),
        "applied": _lms_skin_applied(choice),
        "busy": _skin_job_running(),
    })


@app.route("/api/lms_skin", methods=["POST"])
def api_lms_skin_set():
    skin = ((request.get_json(silent=True) or {}).get("skin") or "").strip()
    if skin not in ("osmium", "material"):
        return _err("msg.skinInvalid", 400)
    if _skin_job_running():
        return _err("msg.skinBusy", 409)
    if not _lyrion_present():
        # No local LMS at all (external/"follow" mode). A local Lyrion that has
        # simply never run yet is NOT this case — the worker waits for it.
        return _err("msg.skinLmsMissing", 409)
    # Record the intent first: even if the apply fails (offline), the choice
    # survives and Settings can retry.
    try:
        tmp = LMS_SKIN_FILE + ".tmp"
        with open(tmp, "w") as f:
            f.write(skin + "\n")
        os.replace(tmp, LMS_SKIN_FILE)
        os.chmod(LMS_SKIN_FILE, 0o644)
    except OSError:
        return _err("msg.saveFailed", 500)
    # Status is set here, not in the thread, so a poll that lands right after
    # this response never sees a stale idle/done from a previous run.
    _skin_status_set("installing", 5, "msg.skinInstalling")
    threading.Thread(target=_lms_skin_apply, args=(skin,),
                     daemon=True, name="lms-skin-apply").start()
    return jsonify({"success": True, "started": True})


@app.route("/api/lms_skin_status", methods=["GET"])
def api_lms_skin_status():
    return jsonify(_skin_status())


# ─────────────────── LMS first-run setup (wizard hand-off) ──────────────────
# See LMS_SETUP_PLUGINS above for why this exists. Shape deliberately mirrors
# the skin job right above: POST starts a worker thread, a status endpoint is
# polled for progress, and the actual work takes _SKIN_JOB_LOCK so the two can
# never stop/start Lyrion at the same time.

def _lms_setup_status():
    with _LMS_SETUP_LOCK:
        return dict(_LMS_SETUP_STATUS)


def _lms_setup_status_set(state, progress, code, **extra):
    payload = {"state": state, "progress": progress, "code": code,
               "message": _m(code)}
    payload.update(extra)
    with _LMS_SETUP_LOCK:
        _LMS_SETUP_STATUS.clear()
        _LMS_SETUP_STATUS.update(payload)


def _lms_setup_job_running():
    return _lms_setup_status().get("state") in ("installing", "applying")


def _lms_wizard_done():
    return bool(_get_lms_pref(LMS_WIZARD_DONE_PREF))


def _lms_setup_apply(plugins, analytics, language):
    """Worker thread behind POST /api/lms_setup.

    Order matters twice over:
      * playlistdir BEFORE the live pref writes — ensure_playlistdir() reads
        the prefs file, then stops Lyrion, then writes the whole dict back, so
        anything set live just before it would be clobbered by that stale read.
      * wizardDone LAST — a device that dies halfway through then comes back
        still showing Lyrion's own wizard (recoverable) instead of a
        half-configured server with no wizard left to finish the job.

    Every step is idempotent, so re-running this is harmless."""
    try:
        _lms_setup_status_set("installing", 10, "msg.lmsSetupInstalling")
        with _SKIN_JOB_LOCK:
            # Same first-run wait as the skin worker: everything below reads or
            # writes server.prefs, which only exists once Lyrion has run.
            if not _ensure_prefs():
                _lms_setup_status_set("error", 0, "msg.skinLmsMissing")
                return
            # MaterialSkin is normally already in by now (the skin step runs
            # first); listing it here costs nothing and covers the case where
            # that step was skipped or failed.
            installed, failed = _ensure_plugins_installed(
                ["MaterialSkin"] + list(plugins),
                {LMS_ANALYTICS_PLUGIN: bool(analytics)})
            _lms_setup_status_set("applying", 70, "msg.lmsSetupApplying")
            try:
                ensure_playlistdir()
            except Exception as e:
                print(f"[sources] lms-setup: playlistdir failed: {e}")
            _set_lms_pref("language", "IT" if language == "it" else "EN")
            if not _set_lms_pref(LMS_WIZARD_DONE_PREF, 1):
                _lms_setup_status_set("error", 0, "msg.lmsSetupFailed")
                return
        # Lyrion's own wizard ends with a library scan and nothing else does it
        # for a first-boot device. Best-effort: a device whose sources are
        # still empty simply has nothing to scan.
        try:
            _lyrion_rescan()
        except Exception:
            pass
        _lms_setup_status_set("done", 100, "msg.lmsSetupDone",
                              installed=installed, failed=failed)
    except Exception as e:
        print(f"[sources] lms-setup failed: {e}")
        _lms_setup_status_set("error", 0, "msg.lmsSetupFailed")


@app.route("/api/lms_setup", methods=["GET"])
def api_lms_setup_get():
    denied = _require_pair_token()
    if denied:
        return denied
    return jsonify({
        "success": True,
        "lms_installed": _lyrion_present(),
        "wizard_done": _lms_wizard_done(),
        "analytics": _builtin_plugin_enabled(LMS_ANALYTICS_PLUGIN),
        "plugins": [{"id": name, "default": default,
                     "installed": _plugin_installed(name)}
                    for name, default in LMS_SETUP_PLUGINS],
        "busy": _lms_setup_job_running(),
    })


@app.route("/api/lms_setup", methods=["POST"])
def api_lms_setup_set():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    requested = data.get("plugins")
    if not isinstance(requested, list):
        requested = []
    known = [name for name, _ in LMS_SETUP_PLUGINS]
    # Allow-list, not free text: whatever survives here becomes a key in
    # Lyrion's own plugin state file and a download URL looked up by name.
    if any(n not in known for n in requested):
        return _err("msg.lmsSetupBadPlugin", 400)
    plugins = [n for n in known if n in set(requested)]
    # Telemetry is a separate boolean rather than an id in the list above, so
    # it can never be switched on by smuggling a plugin name through.
    analytics = bool(data.get("analytics"))
    language = "it" if (data.get("language") or _req_lang()) == "it" else "en"
    if _lms_setup_job_running() or _skin_job_running():
        return _err("msg.lmsSetupBusy", 409)
    if not _lyrion_present():
        # No local LMS at all (external/"follow" mode) — there is no wizard to
        # skip and nothing to install into. A freshly installed Lyrion that has
        # not run yet is NOT this case; the worker waits for its first run.
        return _err("msg.skinLmsMissing", 409)
    _lms_setup_status_set("installing", 5, "msg.lmsSetupInstalling")
    threading.Thread(target=_lms_setup_apply,
                     args=(plugins, analytics, language),
                     daemon=True, name="lms-setup-apply").start()
    return jsonify({"success": True, "started": True})


@app.route("/api/lms_setup_status", methods=["GET"])
def api_lms_setup_status():
    return jsonify(_lms_setup_status())


# ─────────────────────────── Playlist folder ────────────────────────────────
# Where Lyrion saves "save queue as playlist". ensure_playlistdir() picks a
# sane default on its own; this is the user-facing override, so the last thing
# Lyrion's own setup wizard used to ask has a home in our Sources page.

@app.route("/api/playlistdir", methods=["GET"])
def api_playlistdir_get():
    denied = _require_pair_token()
    if denied:
        return denied
    path = (_get_lms_pref("playlistdir") or "").strip()
    return jsonify({
        "success": True,
        "path": path,
        "default": DEFAULT_PLAYLISTDIR,
        "is_default": bool(path) and os.path.realpath(path) == os.path.realpath(DEFAULT_PLAYLISTDIR),
        "exists": bool(path) and os.path.isdir(path),
        "lms_installed": _lyrion_present(),
    })


@app.route("/api/playlistdir", methods=["POST"])
def api_playlistdir_set():
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    raw = (data.get("path") or "").strip()
    if not raw:
        return _err("msg.pathMissing", 400)
    target = os.path.realpath(raw)
    # Same confinement a media folder gets, plus the appliance's own default —
    # that one lives under /var/lib and is therefore outside
    # ALLOWED_LOCAL_ROOTS on purpose (it is ours, not user-picked), but it must
    # stay reachable so "restore the default" works.
    if target != os.path.realpath(DEFAULT_PLAYLISTDIR) \
            and not _local_path_allowed(target):
        return _err("msg.pathNotAllowed", 400)
    if not _make_playlist_folder(target):
        return _err("msg.playlistdirNotWritable", 400, path=target)
    if not _set_lms_pref("playlistdir", target):
        return _err("msg.saveFailed", 500)
    return jsonify({"success": True, "path": target,
                    "message": _m("msg.playlistdirSaved")})


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
        if p and t in ("smb", "internal", "usb"):
            sub = (src.get("subpath") or "").strip("/")
            if sub:
                mount_root = p
                cand = os.path.realpath(os.path.join(mount_root, sub))
                # Re-confine to this source's own mountpoint (not just the
                # shared smb_root/internal_root/usb_root) so a subpath can
                # never wander into a sibling mount, let alone escape it
                # entirely. An invalid/escaping subpath just falls back to
                # the mount root rather than being handed to Lyrion.
                if cand == mount_root or cand.startswith(mount_root + os.sep):
                    p = cand
        if p and p not in paths:
            paths.append(p)
    return paths


def _sync_from_lyrion(state):
    """Pull any change made directly in Lyrion's own source list into our
    state, so the next Apply doesn't blindly clobber it with a mount root.
    Without this, a subfolder picked in Lyrion's own setup wizard (rather
    than through our subpath control) gets silently replaced the next time
    current_paths()/apply_to_lyrion() rebuilds mediadirs purely from our own
    state -- the two lists otherwise "fight" over whichever applied last.

    Critical: this must NOT treat "our own state has a pending edit we
    haven't pushed yet" as "Lyrion changed" -- those look identical if you
    just compare live Lyrion mediadirs against current state (a subpath
    picked in Music Sources but not yet Applied would get reverted by this
    function on the very next poll/GET, before the user ever reaches
    Apply). So a source whose `subpath_pending` flag is set (api_set_subpath
    sets it; apply_to_lyrion clears it once actually pushed) is left alone
    here entirely -- its local value wins until the next Apply, at which
    point it's what actually gets written and the flag clears.

    For each OTHER managed smb/internal/usb source (not pending), an
    adopted live mediadir that resolves under that source's mountpoint
    updates its stored subpath. A mediadir that isn't under any managed
    mount at all is offered as a new `local` source (confined to
    ALLOWED_LOCAL_ROOTS, same as api_add_local()) instead of silently
    vanishing on the next Apply -- but only when it's a real directory
    inside those safe roots; anything else is left alone exactly as before.

    Best-effort: any failure to reach Lyrion (not installed yet, service
    down) just leaves state untouched. Returns True if state was modified,
    so the caller knows whether to save_state()."""
    try:
        current = _lyrion_request(["pref", "mediadirs", "?"]).get("_p2")
    except Exception:
        return False
    if not isinstance(current, list):
        current = [current] if current else []
    if not current:
        return False

    sources = state.get("sources", [])
    managed = [(s, os.path.realpath(s["mountpoint"]))
               for s in sources if s.get("type") in ("smb", "internal", "usb") and s.get("mountpoint")]
    local_paths = {os.path.realpath(s["path"]) for s in sources if s.get("type") == "local" and s.get("path")}

    changed = False
    for raw in current:
        if not raw:
            continue
        p = os.path.realpath(raw)
        owner = next(((s, root) for s, root in managed
                      if p == root or p.startswith(root + os.sep)), None)
        if owner:
            src, root = owner
            if src.get("subpath_pending"):
                # A local edit is staged for this source and hasn't been
                # pushed yet -- Lyrion still shows the old value, which is
                # expected, not an external change. Leave it alone; Apply
                # will reconcile them.
                continue
            sub = "" if p == root else os.path.relpath(p, root)
            if src.get("subpath", "") != sub:
                src["subpath"] = sub
                changed = True
            continue

        # Not under any mount we manage: offer it as a `local` source rather
        # than let it disappear on the next Apply, but only inside the same
        # confinement api_add_local() itself enforces.
        allowed = _local_path_allowed(raw)
        if not allowed or allowed in local_paths or not os.path.isdir(allowed):
            continue
        sid = _slug("local", os.path.basename(allowed.rstrip("/")))
        if any(s.get("id") == sid for s in sources):
            continue
        sources.append({"id": sid, "type": "local", "name": allowed, "path": allowed})
        local_paths.add(allowed)
        changed = True

    if changed:
        state["sources"] = sources
    return changed


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

    # Absorb any change made directly in Lyrion's own source list first, so
    # this Apply (which may be running unattended, e.g. right after USB
    # auto-adopt) doesn't clobber it with a bare mount root — see
    # _sync_from_lyrion()'s docstring.
    with _lock:
        if _sync_from_lyrion(state):
            save_state(state)

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

    # Whatever subpaths were staged are now actually live in Lyrion --
    # clear the pending flag so _sync_from_lyrion() resumes reconciling
    # these sources normally. Re-read+save rather than reuse the `state`
    # object passed in, in case something else touched sources while
    # Lyrion was stopped.
    with _lock:
        fresh = load_state()
        for s in fresh.get("sources", []):
            s.pop("subpath_pending", None)
        save_state(fresh)

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

# _restore_members() writes every member 0600 root:root — the right default
# for anything sensitive, but wrong for the handful of /etc/hifi-player files
# the unprivileged "hifi" user's X session reads DIRECTLY off disk, before
# Electron even starts and before the root API is anywhere in the loop:
# ~/.xsession itself reads pointer-enabled, and hifi-ui-resolution.sh apply
# (invoked from there) reads ui-resolution. Normal writes leave both 644
# (api_server.py's set_pointer() uses a plain open(); hifi-ui-resolution.sh's
# own `set` subcommand explicitly `chmod 644`s it) — restoring them 0600
# silently reverts the kiosk session to its defaults (cursor always hidden;
# no UI downscaling on large panels) regardless of what the backup actually
# had, with no error anywhere pointing at why. Checked the rest of every
# restored category for the same class of bug (root:0600 vs. what the actual
# reader expects) — this is the only other case beyond the Lyrion plugin
# cache: everything else here is read only by hifi-api/hifi-sources/hifi-webui
# (root) or NetworkManager/CamillaDSP/squeezelite (also root; NM's connection
# profiles are the one place 0600 is what's WANTED, and that's already forced
# explicitly in _restore_apply_side_effects).
WORLD_READABLE_RESTORES = frozenset((
    "/etc/hifi-player/pointer-enabled",
    "/etc/hifi-player/ui-resolution",
))

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
        return [], [_ht('restore.archiveInvalidTooManyFiles', _hlang())]
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
            errors.append(_ht('restore.memberTooLarge', _hlang(), name=member.name))
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
                errors.append(_ht('restore.checksumInvalid', _hlang(), name=os.path.basename(dest)))
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
            errors.append(_ht('restore.memberFailed', _hlang(), name=os.path.basename(dest)))
    if progress_cb:
        progress_cb(total, total)
    return restored, errors


def _lyrion_paths_touched(restored):
    # Also cache/InstalledPlugins/Plugins/ — that's real plugin CODE (a
    # downloaded skin like Material, not just a manifest of what's enabled),
    # and _restore_members() writes every member 0600 owned by whoever this
    # process runs as (root). Missing it here left restored plugin files
    # unreadable by the squeezeboxserver/lyrionmusicserver user Lyrion
    # actually runs as — reproduced live: Material's Plugin.pm/HTML/*.css
    # sat there as `-rw------- root root`, so Lyrion silently couldn't load
    # the skin and served /skin.css empty, i.e. Lyrion's page looking totally
    # unstyled right after a restore.
    return [p for p in restored
            if "/prefs/" in p or "/playlists/" in p
            or "/cache/InstalledPlugins/Plugins/" in p]


def _stop_lyrion():
    """Lyrion caches its prefs in memory and rewrites them on exit, so writing
    prefs underneath a running server would simply be overwritten. Unlike the
    backup path — which never stops anything — a restore is an explicit, rare
    action where a short pause is the right trade."""
    _run(["systemctl", "stop", "lyrionmusicserver"], timeout=60)


def _start_lyrion():
    _run(["systemctl", "start", "lyrionmusicserver"], timeout=60)


def _lyrion_cache_dir():
    """The active var-lib base's cache/ dir (squeezeboxserver or
    lyrionmusicserver layout — same dual-package story as everywhere else in
    this file), or None if neither is found."""
    prefs = _find_prefs()
    if prefs:
        cache = os.path.join(os.path.dirname(os.path.dirname(prefs)), "cache")
        if os.path.isdir(cache):
            return cache
    for base in ("/var/lib/squeezeboxserver", "/var/lib/lyrionmusicserver"):
        cache = os.path.join(base, "cache")
        if os.path.isdir(cache):
            return cache
    return None


def _invalidate_lyrion_plugin_cache():
    """Force Lyrion to rebuild its plugin listing from scratch on next start.

    Reproduced live: even after _chown_lyrion() fixes ownership, Lyrion's own
    cache/plugin-data.yaml (built by scanning cache/InstalledPlugins/Plugins/
    at startup) stays whatever it last managed to build. If that build ran
    while a plugin's files were still unreadable — as every restore did before
    _lyrion_paths_touched() covered this directory — the plugin (e.g. the
    Material skin) stays "missing" in that cache forever, permission fix or
    not: /skin.css kept serving empty and /material/ kept 404ing even with
    every file correctly chowned, until this cache was cleared. Deleting it is
    safe — Lyrion regenerates it from the Plugins/ directory on every start
    regardless — and this makes an already-affected device (one that hit the
    bug on a past restore, before this fix shipped) self-heal on its next one
    instead of needing a manual cache wipe.
    """
    cache_dir = _lyrion_cache_dir()
    if not cache_dir:
        return
    targets = [os.path.join(cache_dir, "plugin-data.yaml")]
    targets += glob.glob(os.path.join(cache_dir, "stringcache.*.bin"))
    for path in targets:
        try:
            os.remove(path)
        except OSError:
            pass


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


def _fix_restored_permissions(restored):
    """Re-widen the handful of restored files a non-root reader needs — see
    WORLD_READABLE_RESTORES. Best-effort, same as _chown_lyrion."""
    for path in restored:
        if path in WORLD_READABLE_RESTORES:
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass


def _restore_apply_side_effects(restored):
    """Re-apply the config that was just restored (best-effort, non-fatal)."""
    notes = []
    if STATE_FILE in restored:
        try:
            remount_all()
            ok, msg = apply_to_lyrion(load_state())
            notes.append(msg if ok else _ht('restore.sourcesFailed', _hlang(), msg=msg))
        except Exception as e:
            print(f"[sources] restore side-effect (sources) failed: {e}")
            notes.append(_ht('restore.sourcesNotReapplied', _hlang()))
    if "/etc/hostname" in restored:
        # /etc/hostname was restored as a plain file, but the live kernel
        # hostname (what hostnamectl/socket.gethostname() actually report) is
        # separate state nothing in a restore re-derives on its own — same
        # story as /etc/timezone just below. Proxies to api_server.py's
        # _apply_hostname (via /hostname_apply) instead of duplicating its
        # hostnamectl/avahi/etc-hosts logic here, and deliberately does NOT go
        # through /device_name — that would also force the Bluetooth/
        # squeezelite player name to match, clobbering the player name
        # /etc/default/squeezelite just restored on its own (see the
        # squeezelite-restart branch below).
        try:
            with open("/etc/hostname") as f:
                name = f.read().strip()
            if name:
                body, status = _proxy_to_api_server(
                    "/hostname_apply", method="POST", body={"name": name}, timeout=30)
                if status == 200 and body.get("success"):
                    notes.append(_ht('restore.hostnameApplied', _hlang(), name=name))
        except Exception as e:
            print(f"[sources] restore side-effect (hostname) failed: {e}")
    if "/etc/timezone" in restored:
        # /etc/timezone was restored as a plain file, but that's just the IANA
        # name -- /etc/localtime (the symlink libc/Chromium/timedatectl actually
        # resolve wall-clock time against) is a separate artifact that nothing
        # in a restore touches. Left alone, the restored name shows up in
        # Settings while every clock on the box keeps running on whatever zone
        # the image shipped with (UTC).
        #
        # Handed to api_server.py's /timezone rather than re-implemented here:
        # applying a zone means validating the name, writing the symlink,
        # keeping the two files in sync and restarting the kiosk so Chromium
        # re-reads ICU, and having two copies of that is how the pair drifted
        # in the first place. Same proxy pattern as the hostname re-apply above.
        try:
            with open("/etc/timezone") as f:
                tz = f.read().strip()
            if tz:
                body, status = _proxy_to_api_server(
                    "/timezone", method="POST", body={"timezone": tz}, timeout=30)
                if status == 200 and body.get("success"):
                    notes.append(_ht('restore.timezoneApplied', _hlang(), tz=tz))
                else:
                    print(f"[sources] restore side-effect (timezone) rejected: {body}")
        except Exception as e:
            print(f"[sources] restore side-effect (timezone) failed: {e}")
    if any(p in restored for p in ("/etc/default/squeezelite", "/var/lib/hifi-player/dsp-target")):
        _run(["systemctl", "restart", "squeezelite"], timeout=30)
        notes.append(_ht('restore.squeezeliteRestarted', _hlang()))
    if any(p in restored for p in ("/etc/camilladsp/config.yml", "/etc/hifi-player/dsp.json")) \
            or any(p.startswith("/etc/camilladsp/filters/") for p in restored):
        # Only restart CamillaDSP if it was already running — restoring a
        # backup must never turn DSP on by itself.
        try:
            active = _run(["systemctl", "is-active", "camilladsp.service"], timeout=10)
            if (active.stdout or "").strip() == "active":
                _run(["systemctl", "restart", "camilladsp.service"], timeout=30)
                notes.append(_ht('restore.camillaRestarted', _hlang()))
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
        notes.append(_ht('restore.wifiReloaded', _hlang()))
    if "/etc/hifi-player/webui.db" in restored:
        # The admin account changed underneath the running daemon; restart so
        # it reopens the database. No note here — restarting hifi-webui.service
        # is not "the appliance restarted" (it doesn't reboot anything), and
        # admin-webui reloads itself on a successful restore anyway, which
        # lands the operator back on the login page on its own.
        _run(["systemctl", "restart", "hifi-webui"], timeout=30)
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
        notes.append(_ht('restore.smbResynced', _hlang()))
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
        report("opening", 20, _ht('restore.openingArchive', _hlang()))
        try:
            tar, manifest = hb.open_backup(path, workdir, passphrase)
        except hb.BackupError as e:
            return {"success": False, "message": str(e)}, 400

        # A backup written by a newer build may use members or semantics this
        # code does not understand; refuse rather than half-apply it.
        if manifest and int(manifest.get("schema") or 1) > hb.SCHEMA:
            return {"success": False,
                    "message": _ht('restore.newerVersion', _hlang())}, 409

        available = hb.categories_in_manifest(manifest)
        wanted = set(requested_categories or available)
        categories = [c for c in available if c in wanted]
        if not categories:
            return {"success": False,
                    "message": _ht('restore.noCategories', _hlang())}, 400

        lyrion_stopped = False
        if "lyrion" in categories:
            report("stopping_lyrion", 25, _ht('restore.stoppingLyrion', _hlang()))
            _stop_lyrion()
            lyrion_stopped = True
        try:
            def _member_progress(done, total):
                pct = 30 + int(done / total * 45) if total else 30
                report("restoring", pct, _ht('restore.restoringFiles', _hlang(), done=done, total=total))
            restored, errors = _restore_members(tar, manifest, categories, _member_progress)
            _fix_restored_permissions(restored)
        finally:
            if lyrion_stopped:
                report("starting_lyrion", 80, _ht('restore.startingLyrion', _hlang()))
                touched = _lyrion_paths_touched(restored if restored else [])
                _chown_lyrion(touched)
                if any("/cache/InstalledPlugins/Plugins/" in p for p in touched):
                    _invalidate_lyrion_plugin_cache()
                _start_lyrion()

        if not restored and errors:
            return {"success": False, "message": "; ".join(errors)}, 400

        report("applying", 90, _ht('restore.applyingChanges', _hlang()))
        notes = _restore_apply_side_effects(restored)
        if lyrion_stopped:
            # Restoring prefs/playlists makes Lyrion treat them as changed on
            # its own next start, so it runs its own library rescan — nothing
            # this code drives or can see the end of, and the LMS web UI's
            # "please wait" banner during that looks a lot like something
            # stuck. Say so up front instead of leaving the user to wonder.
            notes.append(_ht('restore.lyrionScanning', _hlang()))
        msg = _ht('restore.filesRestored', _hlang(), count=len(restored))
        if notes:
            msg += " " + " ".join(notes)
        if errors:
            msg += _ht('restore.warningsPrefix', _hlang()) + "; ".join(errors)
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
        _write_restore_status("preparing", 5, _ht('restore.preparing', _hlang()))
        _write_restore_status("snapshotting", 10, _ht('restore.snapshotting', _hlang()))
        _snapshot_before_restore()

        def report(state, progress, message):
            _write_restore_status(state, progress, message)

        payload, status = _restore_from_path(path, passphrase, categories, report)
        if status == 200 and payload.get("success"):
            _write_restore_status("done", 100, payload.get("message", _ht('restore.completed', _hlang())),
                                  restored=payload.get("restored"), categories=payload.get("categories"))
        else:
            _write_restore_status("error", 0, payload.get("message", _ht('restore.failed', _hlang())))
    except Exception as e:
        print(f"[sources] restore job failed: {e}")
        _write_restore_status("error", 0, _ht('restore.failedDetail', _hlang(), err=e))
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
    _write_restore_status("preparing", 0, _ht('common.starting', _hlang()))
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
        return jsonify({"success": False, "message": _ht('backup.createFailed', _hlang())}), 500
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
        return jsonify({"success": False, "message": _ht('backup.invalidPassphrase', _hlang())}), 400
    categories = hb.selected_categories(data.get("categories"), bool(passphrase))
    if not categories:
        return jsonify({"success": False,
                        "message": _ht('backup.noCategoriesSelected', _hlang())}), 400

    job = {"categories": categories, "passphrase": passphrase,
           "trigger": "manual", "keep": hb.read_settings()["keep"]}
    # /run is tmpfs and this may carry the passphrase: write it 0600, and the
    # worker deletes it the moment it has been read.
    fd = os.open(BACKUP_JOB, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(job, f)
    with open(hb.STATUS_FILE, "w") as f:
        json.dump({"state": "preparing", "progress": 0, "message": _ht('common.starting', _hlang())}, f)
    try:
        r = _run(["systemd-run", "--no-block", "--collect", "--unit=" + BACKUP_UNIT,
                  BACKUP_SCRIPT, BACKUP_JOB], timeout=15)
        launch_err = None if r.returncode == 0 else (r.stderr or r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        launch_err = _ht('install.systemdRunNoResponse', _hlang())
    if launch_err:
        # Without this, a systemd-run failure (unit already active, dbus, etc.)
        # leaves the "Starting…"/0% placeholder above in place forever, since
        # nothing ever starts to overwrite it — the UI just polls a frozen
        # status and looks hung.
        with open(hb.STATUS_FILE, "w") as f:
            json.dump({"state": "error", "progress": 0,
                       "message": _ht('backup.startFailedDetail', _hlang(), detail=launch_err)[:300]}, f)
        try:
            os.unlink(BACKUP_JOB)
        except OSError:
            pass
        return jsonify({"success": False, "message": _ht('backup.startFailed', _hlang())}), 500
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
        return jsonify({"success": False, "message": _ht('backup.notFound', _hlang())}), 404
    manifest = hb.read_manifest(hb.STORE_DIR, gen_id)
    if not manifest:
        return jsonify({"success": False, "message": _ht('backup.notFound', _hlang())}), 404

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
        return jsonify({"success": False, "message": _ht('backup.unreadable', _hlang())}), 500
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
        return jsonify({"success": False, "message": _ht('backup.notFound', _hlang())}), 404
    path = os.path.join(hb.STORE_DIR, gen_id)
    if not os.path.isdir(path):
        return jsonify({"success": False, "message": _ht('backup.notFound', _hlang())}), 404
    shutil.rmtree(path, ignore_errors=True)
    hb.record_history(hb.STORE_DIR, f"delete\t{gen_id}")
    return jsonify({"success": True, "message": _ht('backup.deleted', _hlang())})


@app.route("/api/backup/<gen_id>/restore", methods=["POST"])
def api_backup_restore(gen_id):
    denied = _require_pair_token()
    if denied:
        return denied
    if not hb.valid_gen_id(gen_id):
        return jsonify({"success": False, "message": _ht('backup.notFound', _hlang())}), 404
    manifest = hb.read_manifest(hb.STORE_DIR, gen_id)
    if not manifest:
        return jsonify({"success": False, "message": _ht('backup.notFound', _hlang())}), 404
    data = request.get_json(silent=True) or {}
    passphrase = data.get("passphrase") or ""
    if not _passphrase_ok(passphrase):
        return jsonify({"success": False, "message": _ht('backup.invalidPassphrase', _hlang())}), 400

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
            return jsonify({"success": False,
                            "message": _ht('restore.prepareFailed', _hlang(), err=e)}), 500

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
        return jsonify({"success": False, "message": _ht('backup.saveFailed', _hlang(), err=e)}), 500
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
        return jsonify({"success": False, "message": _ht('backup.invalidPassphrase', _hlang())}), 400
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
    # Renames BOTH the hostname and the squeezelite/Bluetooth player name
    # together (api_server.py's set_device_name) — the companion app's
    # rename field uses this instead of player_name above, so a rename from
    # the phone stays in sync with the kiosk/web-admin ones.
    ("/api/system/device_name", "GET", "/device_name"),
    ("/api/system/device_name", "POST", "/device_name"),
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


def _fs_usage(path):
    """Total/free bytes of the filesystem holding `path`, or None when it
    can't be stat'd (not mounted, gone). Reported per source by /api/sources
    so "Active sources" can show how much room a disk still has without the
    UI needing a second endpoint per row."""
    if not path:
        return None
    try:
        st = os.statvfs(path)
    except (OSError, ValueError):
        return None
    total = st.f_blocks * st.f_frsize
    if total <= 0:
        return None
    return {"total": total, "free": st.f_bavail * st.f_frsize}


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
    with _lock:
        state = load_state()
        if _sync_from_lyrion(state):
            save_state(state)
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
        if item.get("mounted") or item.get("exists"):
            item["usage"] = _fs_usage(s.get("mountpoint") or s.get("path"))
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
    _lyrion_push_live(add_paths=[src["mountpoint"]])


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
    """Add a rootfs folder as a `local` source. With `samba: true`, also
    turn it into a network-writable Samba share (same ownership/mode
    treatment ext4 internal disks get -- see _mount_adopted_disk()) so
    music can be copied onto the appliance over the network instead of
    needing SSH/a USB stick -- the folder is created if it doesn't exist
    yet, since the whole point is often to make a fresh empty share to
    upload into."""
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    path = (data.get("path") or "").strip()
    samba = bool(data.get("samba"))
    if not path:
        return _err("msg.pathMissing", 400)
    path = _local_path_allowed(path)
    if not path:
        return _err("msg.pathNotAllowed", 400)
    if not os.path.isdir(path):
        if not samba:
            return _err("msg.folderMissing", 400, path=path)
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            return _err("msg.mountFailed", 400, detail=str(e))

    with _lock:
        state = load_state()
        sid = _slug("local", os.path.basename(path.rstrip("/")))
        src = {"id": sid, "type": "local", "name": path, "path": path}
        if samba:
            uid, gid = _ensure_samba_uid_gid()
            try:
                os.chown(path, uid, gid)
                os.chmod(path, 0o2775)
            except Exception as e:
                print(f"[sources] chown/chmod for shared local folder {path} failed: {e}")
            existing = next((s for s in state["sources"] if s.get("id") == sid), None)
            src["samba"] = True
            src["share"] = (existing or {}).get("share") or _share_name(os.path.basename(path.rstrip("/")))
        state["sources"] = [s for s in state["sources"] if s.get("id") != sid]
        state["sources"].append(src)
        save_state(state)
        # Always regenerate, not just when samba=True now: re-adding the
        # same path with the box unchecked must also drop a share it had
        # from a previous add.
        regen_samba_shares()
    _lyrion_push_live(add_paths=[path])
    return jsonify({"success": True})


@app.route("/api/local/browse", methods=["GET"])
def api_browse_local():
    """List immediate subdirectories under any path, starting from / when
    no ?path= is given -- powers the "Add local folder" picker's
    file-browser UI, mirroring Lyrion's own folder picker (which also
    starts at / and can browse the whole filesystem) rather than a
    free-text path box. Deliberately NOT confined to ALLOWED_LOCAL_ROOTS:
    that confinement guards what may actually become a Lyrion media
    directory or a Samba share (api_add_local()/api_mkdir_local() still
    enforce it), not read-only directory-name listing for an
    already-pair-token-authenticated admin session. Distinct from
    api_browse_subpath(): that one browses under an existing source's own
    mountpoint; this one has no source yet."""
    denied = _require_pair_token()
    if denied:
        return denied
    rel = (request.args.get("path") or "").strip() or "/"
    cand = os.path.realpath(rel)
    if not os.path.isdir(cand):
        return _err("msg.folderMissing", 400, path=rel)
    try:
        dirs = sorted(
            e.path for e in os.scandir(cand)
            if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")
        )
    except OSError:
        dirs = []
    parent = os.path.dirname(cand.rstrip("/")) or "/"
    if parent == cand:
        parent = None  # already at /, nowhere further up
    return jsonify({"path": cand, "parent": parent, "dirs": dirs})


@app.route("/api/local/mkdir", methods=["POST"])
def api_mkdir_local():
    """Create a new subfolder inside an ALLOWED_LOCAL_ROOTS-confined path --
    the picker's "new folder" action, for making a fresh empty folder to
    share/upload into rather than only picking among what already exists."""
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    parent = (data.get("path") or "").strip()
    name = (data.get("name") or "").strip()
    if not parent or not name or "/" in name or name in (".", ".."):
        return _err("msg.pathNotAllowed", 400)
    parent_ok = _local_path_allowed(parent)
    if not parent_ok or not os.path.isdir(parent_ok):
        return _err("msg.folderMissing", 400, path=parent)
    target = _local_path_allowed(os.path.join(parent_ok, name))
    if not target:
        return _err("msg.pathNotAllowed", 400)
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as e:
        return _err("msg.mountFailed", 400, detail=str(e))
    return jsonify({"success": True, "path": target})


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
        # Opt-in — see mount_smb()'s docstring. Off by default: most SMB
        # sources are an existing NAS library the appliance should only read.
        "rw": bool(data.get("rw")),
    }
    ok, msg = mount_smb(src)
    if not ok:
        return _err("msg.mountFailed", 400, detail=msg)
    with _lock:
        state = load_state()
        state["sources"] = [s for s in state["sources"] if s.get("id") != sid]
        state["sources"].append(src)
        save_state(state)
    _lyrion_push_live(add_paths=[src["mountpoint"]])
    return jsonify({"success": True, "message": msg})


@app.route("/api/sources/<sid>/rw", methods=["POST"])
def api_set_smb_rw(sid):
    """Flip an SMB source's stored read-only/read-write flag. Takes effect on
    the next reboot rather than live: CIFS doesn't support changing
    uid=/gid=/file_mode=/dir_mode= with an `-o remount`, so making this live
    would mean unmount+remount while Lyrion (or an in-progress CD rip) may
    still have the old mount open. A lazy `umount -l` doesn't break already-
    open reads, but anything that opens a *new* file during the swap window
    hits a dead mountpoint, an in-flight rip's write handles stay bound to
    the old (soon fully torn down) CIFS session instead of the new one — a
    real risk of silently losing ripped tracks — and a library scan that
    catches the transient failure can misread it as "file gone" and prune
    the track from the database. None of that is worth risking for a
    rarely-toggled setting, so this just persists the new flag; boot's
    remount_all_retry() re-mounts every SMB source from state fresh, picking
    it up with mount_smb()'s current option set."""
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    rw = bool(data.get("rw"))
    with _lock:
        state = load_state()
        src = next((s for s in state["sources"] if s.get("id") == sid and s.get("type") == "smb"), None)
        if not src:
            return _err("msg.sourceNotFound", 404)
        if src.get("rw", False) == rw:
            return jsonify({"success": True, "message": _m("msg.noChange")})
        src["rw"] = rw
        save_state(state)
    return jsonify({"success": True, "message": _m("msg.rebootRequired")})


@app.route("/api/sources/<sid>/subpath", methods=["POST"])
def api_set_subpath(sid):
    """Set (or clear, with an empty subpath) the subfolder under a
    smb/internal/usb source's mount that Lyrion should actually scan, instead
    of always the whole mount. This is what lets Music Sources fully replace
    Lyrion's own "pick a folder" step in its setup wizard: the subfolder
    choice now lives in state we control (current_paths() applies it) and
    survives the next Apply instead of being silently reset to the mount
    root."""
    denied = _require_pair_token()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    subpath = (data.get("subpath") or "").strip("/")
    with _lock:
        state = load_state()
        src = next((s for s in state["sources"] if s.get("id") == sid), None)
        if not src:
            return _err("msg.sourceNotFound", 404)
        if src.get("type") not in ("smb", "internal", "usb"):
            return _err("msg.subpathNotSupported", 400)
        mountpoint = src.get("mountpoint")
        if subpath and mountpoint:
            root = os.path.realpath(mountpoint)
            cand = os.path.realpath(os.path.join(root, subpath))
            if cand != root and not cand.startswith(root + os.sep):
                return _err("msg.pathNotAllowed", 400)
            if os.path.ismount(mountpoint) and not os.path.isdir(cand):
                return _err("msg.folderMissing", 400, path=cand)
        src["subpath"] = subpath
        # Staged until the live push below lands -- tell _sync_from_lyrion()
        # to leave this source alone in the meantime, otherwise a GET
        # /api/sources poll landing in that window sees Lyrion still showing
        # the old mediadir and "reconciles" this pick right back out.
        src["subpath_pending"] = True
        save_state(state)
        target = current_paths({"sources": [src]})
    # Swap the old mediadir for the newly picked subfolder right away: there
    # is no Apply button to reach any more.
    if _lyrion_push_live(drop_roots=[mountpoint] if mountpoint else (),
                         add_paths=target):
        with _lock:
            fresh = load_state()
            for s in fresh.get("sources", []):
                if s.get("id") == sid:
                    s.pop("subpath_pending", None)
            save_state(fresh)
    return jsonify({"success": True, "message": _m("msg.subpathSaved")})


@app.route("/api/sources/<sid>/browse", methods=["GET"])
def api_browse_subpath(sid):
    """List immediate subdirectories under a source's mount (optionally under
    a further relative ?path=), so the subpath control above can offer a
    folder picker instead of free-text entry -- no such browse endpoint
    existed before this."""
    denied = _require_pair_token()
    if denied:
        return denied
    state = load_state()
    src = next((s for s in state["sources"] if s.get("id") == sid), None)
    if not src:
        return _err("msg.sourceNotFound", 404)
    if src.get("type") not in ("smb", "internal", "usb"):
        return _err("msg.subpathNotSupported", 400)
    mountpoint = src.get("mountpoint")
    if not mountpoint or not os.path.ismount(mountpoint):
        return _err("msg.folderMissing", 400, path=mountpoint or "")
    root = os.path.realpath(mountpoint)
    rel = (request.args.get("path") or "").strip("/")
    cand = os.path.realpath(os.path.join(root, rel))
    if cand != root and not cand.startswith(root + os.sep):
        return _err("msg.pathNotAllowed", 400)
    if not os.path.isdir(cand):
        return _err("msg.folderMissing", 400, path=cand)
    try:
        dirs = sorted(
            e.name for e in os.scandir(cand)
            if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")
        )
    except OSError:
        dirs = []
    parent = None
    if cand != root:
        parent = os.path.relpath(os.path.dirname(cand), root)
        if parent == ".":
            parent = ""
    return jsonify({"path": rel, "parent": parent, "dirs": dirs})


@app.route("/api/sources/<sid>", methods=["DELETE"])
def api_remove(sid):
    denied = _require_pair_token()
    if denied:
        return denied
    with _lock:
        state = load_state()
        removed = [s for s in state.get("sources", []) if s.get("id") == sid]
        for src in removed:
            # remember_ignored: the user asked for this one, and the device
            # may well still be plugged in — see _detach_source().
            _detach_source(state, src, remember_ignored=True)
        save_state(state)
        regen_samba_shares()
        # Lyrion, still inside the lock: a GET /api/sources landing between
        # the save above and this call would see a mediadir belonging to no
        # source and re-import it through _sync_from_lyrion(), undoing the
        # removal the user just asked for.
        roots = [r for src in removed for r in _source_lyrion_roots(src)]
        if roots:
            try:
                _lyrion_remove_mediadir_live(roots)
            except Exception as e:
                # Not fatal: the source is gone from our state either way and
                # the next apply rewrites mediadirs from it.
                print(f"[sources] could not drop {roots} from Lyrion mediadirs: {e}")
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
    existing = _existing_adopted_source("internal", partuuid, fsuuid)
    if existing:
        share = existing["share"]
        mountpoint = existing["mountpoint"]
        sid = existing["id"]
    else:
        share = _share_name(label)
        mountpoint = os.path.join(INTERNAL_MOUNT_ROOT,
                                  _slug(label) + "-" + (partuuid or fsuuid or "adopt")[:8])
        sid = _slug("internal", share)

    src = {
        "id": sid,
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
    # Live add rather than apply_to_lyrion(): that stops/starts
    # lyrionmusicserver, which would cut off whatever is playing — exactly
    # what adopting a second disk should not do.
    _lyrion_push_live(add_paths=[src["mountpoint"]])
    return jsonify({"success": True, "source_id": src["id"], "share": share})


def _adopt_usb_partition(part):
    """Mount `part` (one of _usb_partitions()'s dicts) read-write under
    USB_ADOPTED_ROOT and register it as a persistent, Samba-shared "usb"
    source. Pure — no Flask request/response — so it's safe to call both from
    an HTTP request (api_usb_adopt(), the manual retry path) and from the
    usb_monitor background thread (the automatic path every healthy device
    takes, see usb_sync()). Returns (ok, message, src_dict_or_None)."""
    partuuid = part.get("partuuid")
    fsuuid = part.get("uuid")
    fstype = (part.get("fstype") or "").lower()
    label = part.get("label") or part.get("name") or "USB"
    existing = _existing_adopted_source("usb", partuuid, fsuuid)
    if existing:
        share = existing["share"]
        mountpoint = existing["mountpoint"]
        sid = existing["id"]
    else:
        share = _share_name(label)
        mountpoint = os.path.join(USB_ADOPTED_ROOT,
                                  _slug(label) + "-" + (partuuid or fsuuid or "adopt")[:8])
        sid = _slug("usb", share)

    src = {
        "id": sid,
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
        return False, msg, None

    with _lock:
        state = load_state()
        state["sources"] = [s for s in state["sources"] if s.get("id") != src["id"]]
        state["sources"].append(src)
        save_state(state)
        regen_samba_shares()
    # Deliberately does NOT call apply_to_lyrion() — that does a full
    # systemctl stop/start of lyrionmusicserver, which drops the squeezelite
    # connection and kills any music currently playing. The Samba share is
    # already live at this point (regen_samba_shares() above) without it.
    # Instead, add the folder to Lyrion's live mediadirs and trigger a scan
    # over JSON-RPC (_lyrion_add_mediadir_live) — same non-disruptive
    # approach _rip_watcher() already uses after a CD rip — so the music
    # shows up in the library without a restart. Best-effort: if Lyrion isn't
    # reachable this silently does nothing, and the folder still gets picked
    # up whenever the user next presses "Apply & rescan library" (which
    # recomputes mediadirs from state regardless, so there's nothing to
    # reconcile either way).
    try:
        _lyrion_add_mediadir_live(mountpoint)
    except Exception as e:
        print(f"[sources] live mediadir add/rescan failed for {mountpoint}: {e}")
    return True, "", src


@app.route("/api/usb/adopt", methods=["POST"])
def api_usb_adopt():
    """Manual retry for a USB partition that usb_sync()'s automatic adoption
    couldn't mount (recognized filesystem, transient mount error) — every
    healthy device is adopted automatically as soon as it's plugged in, no
    user action needed."""
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

    ok, msg, src = _adopt_usb_partition(part)
    if not ok:
        return _err("msg.mountFailed", 400, detail=msg)
    return jsonify({"success": True, "source_id": src["id"], "share": src["share"]})


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
        json.dump({"state": "idle", "progress": 0, "message": _ht('common.starting', _hlang())}, f)

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


def _lyrion_request(params, timeout=10):
    """POST one slim.request command to Lyrion's JSON-RPC endpoint and return
    its `result` dict. Raises on any transport/JSON error — callers decide
    whether that's fatal for them."""
    payload = {"id": 1, "method": "slim.request", "params": ["", params]}
    req = urllib.request.Request(
        LYRION_RPC, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8")).get("result") or {}


def _lyrion_rescan():
    _lyrion_request(["rescan"])


def _lyrion_edit_mediadirs_live(drop_roots=(), add_paths=(), force_rescan=False):
    """Drop every live mediadir at or under `drop_roots`, append everything in
    `add_paths`, then rescan — in one read-modify-write round-trip and,
    crucially, without stopping/starting lyrionmusicserver the way
    apply_to_lyrion() does, so whatever is playing keeps going. mediadirs is
    an array pref and Lyrion's CLI can't set array values (JSON-RPC only —
    confirmed against the Lyrion forum's own guidance for this exact pref),
    hence reading the live list first rather than trusting our own state.

    This is what makes every edit in Music Sources take effect by itself:
    there is no "Apply & rescan" button in the kiosk/web-admin UIs any more,
    so adding, removing and re-pointing a source each push themselves through
    here. Deliberately targeted rather than rewriting the whole list from
    current_paths(): an unrelated source whose disk happens to be unplugged
    keeps its folder in Lyrion instead of being scanned away to nothing.

    Raises on failure (e.g. Lyrion not reachable) — callers treat that as
    non-fatal, since /api/apply still recomputes mediadirs from state.
    Returns True if the list actually changed."""
    current = _lyrion_request(["pref", "mediadirs", "?"]).get("_p2")
    if not isinstance(current, list):
        current = [current] if current else []
    victims = [os.path.realpath(r) for r in drop_roots if r]
    wanted = []
    for d in current:
        if not d:
            continue
        p = os.path.realpath(d)
        if any(p == v or p.startswith(v + os.sep) for v in victims):
            continue
        wanted.append(d)
    for path in add_paths:
        if path and path not in wanted:
            wanted.append(path)
    changed = wanted != current
    if changed:
        _lyrion_request(["pref", "mediadirs", wanted])
    if changed or force_rescan:
        _lyrion_rescan()
    return changed


def _lyrion_push_live(drop_roots=(), add_paths=()):
    """Best-effort _lyrion_edit_mediadirs_live() for the HTTP handlers. Music
    Sources has no "Apply & rescan" button any more, so every mutation calls
    this — and a Lyrion that is still starting (or not installed yet on a
    fresh unit) must not turn an otherwise successful edit into an HTTP
    error. /api/apply, still used by the first-run setup pages, rebuilds
    mediadirs from state regardless, so nothing is lost when this misses."""
    try:
        _lyrion_edit_mediadirs_live(drop_roots=drop_roots, add_paths=add_paths,
                                    force_rescan=bool(add_paths))
        return True
    except Exception as e:
        print(f"[sources] live mediadirs update failed "
              f"(drop={list(drop_roots)}, add={list(add_paths)}): {e}")
        return False


def _lyrion_add_mediadir_live(path):
    """Add `path` to Lyrion's live mediadirs and trigger a scan. Always
    rescans even when the folder is already listed — the other caller of this
    is the CD ripper, where the destination folder is unchanged and it is the
    new files inside it that need picking up."""
    _lyrion_edit_mediadirs_live(add_paths=[path], force_rescan=True)


def _source_lyrion_roots(src):
    """Every path in Lyrion's mediadirs that belongs to `src`: its mount root
    for an adopted/SMB source, its folder for a `local` one. The subpath is
    deliberately not applied — what Lyrion holds may be the root, a subpath,
    or (after an edit that was never applied) both, and all of it goes when
    the source goes."""
    if src.get("type") in ("smb", "internal", "usb"):
        mp = src.get("mountpoint")
        return [os.path.realpath(mp)] if mp else []
    raw = src.get("path")
    return [os.path.realpath(raw)] if raw else []


def _lyrion_remove_mediadir_live(roots):
    """The counterpart of _lyrion_add_mediadir_live(): drop every live
    mediadir at or under `roots`, then rescan — again without restarting
    lyrionmusicserver, so removing a source doesn't cut the music off.

    Without this, removing a source only ever took it out of our own state:
    Lyrion kept the folder, and the very next GET /api/sources handed it
    back through _sync_from_lyrion(), which re-imports any mediadir it does
    not recognise as a `local` source. The user's deletion undid itself
    within the second, forever — and neither the kiosk nor the web UI could
    do anything about it, since both go through this same endpoint.

    Raises on failure (Lyrion unreachable): the caller decides, and the next
    "Apply & rescan" recomputes mediadirs from state regardless."""
    return _lyrion_edit_mediadirs_live(drop_roots=roots)


def _rip_watcher():
    """Background thread (spawned per rip): when the worker reports done, fix
    ownership for Samba access (ext4 destinations only — see
    _mount_adopted_disk()'s docstring; SMB/FAT-like destinations already
    present every file under a fixed uid/gid via mount options, so nothing to
    fix there) and add the destination to Lyrion's library live — not
    apply_to_lyrion(), so LMS is not restarted mid-listen."""
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
                    local_roots = (INTERNAL_MOUNT_ROOT + "/", USB_ADOPTED_ROOT + "/")
                    if dest.startswith(local_roots) and os.path.isdir(dest):
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
                        _lyrion_add_mediadir_live(dest)
                    except Exception as e:
                        print(f"[sources] rip library add/rescan failed: {e}")
                return
        except Exception as e:
            print(f"[sources] rip watcher error: {e}")


def _rip_writable_sources():
    """Sources the rip can write into: adopted (rw, hifimusic-owned) internal
    or USB disks, plus any SMB share explicitly mounted read-write (opt-in —
    see mount_smb())."""
    out = []
    for s in load_state().get("sources", []):
        t = s.get("type")
        if t not in ("internal", "usb") and not (t == "smb" and s.get("rw")):
            continue
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
            return _err("msg.noWritableTarget", 400)

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
                   "progress": 0, "message": _ht('common.starting', _hlang())}, f)

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
            "mountpoint": s.get("mountpoint") or s.get("path"),
            "source_id": s.get("id"),
            "type": s.get("type"),
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
    """List USB devices that need attention: no recognized filesystem
    (needs_format) or the last automatic mount attempt failed (error).
    Healthy devices don't appear here — usb_sync() auto-adopts them as soon
    as they're plugged in and they show up under /api/sources instead."""
    denied = _require_pair_token()
    if denied:
        return denied
    # Serve the snapshot kept fresh by the background usb_monitor thread instead
    # of re-scanning on every poll. Only force a scan if none has run yet.
    entries = _usb_state
    if entries is None:
        try:
            entries = usb_sync()
        except Exception:
            app.logger.exception("Failed to enumerate USB disks")
            return jsonify({"disks": [], "error": "Unable to enumerate USB disks."}), 500
    disks = [
        {
            "label": p.get("label") or p.get("name"),
            "fstype": p.get("fstype"),
            "size": p.get("size"),
            "needs_format": p.get("needs_format", False),
            "error": p.get("error"),
            # Device node, used by the "Riprova" (manual retry adopt) action.
            "path": p.get("path"),
        }
        for p in entries
    ]
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
        "sources.usbAttention": "USB devices needing attention",
        "sources.usbNeedsFormat": "No recognized filesystem — format it from a computer.",
        "sources.usbMountError": "Mount error",
        "sources.usbRetry": "Retry",
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
        "sources.smbRw": "Allow writing (needed to use it as a CD-rip destination)",
        "sources.smbMakeRw": "Make writable",
        "sources.smbMakeRo": "Make read-only",
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
        "sources.playlistdirTitle": "Playlist folder",
        "sources.playlistdirHint": "Where Lyrion saves the playlists you create from the player. The default is fine for most setups — pick a folder on your own disk if you want the playlists next to your music.",
        "sources.playlistdirCurrent": "Current folder",
        "sources.playlistdirUse": "Use this folder",
        "sources.playlistdirDefault": "Restore default",
        "sources.playlistdirSaving": "Saving…",
        "sources.applying": "Applying…",
        "sources.applied": "Done ✓",
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
        "msg.skinInvalid": "Invalid skin value.",
        "msg.skinBusy": "A skin change is already in progress.",
        "msg.skinLmsMissing": "Lyrion is not installed on this device.",
        "msg.skinInstalling": "Installing the Material web interface…",
        "msg.skinApplying": "Applying the skin…",
        "msg.skinApplied": "Skin applied.",
        "msg.skinInstallFailed": "Could not download the Material web interface. Check the network connection and try again.",
        "msg.skinApplyFailed": "Could not apply the skin.",
        "msg.lmsSetupBusy": "Lyrion is already being set up.",
        "msg.lmsSetupBadPlugin": "Unknown plugin.",
        "msg.lmsSetupInstalling": "Installing the selected services…",
        "msg.lmsSetupApplying": "Finishing the Lyrion setup…",
        "msg.lmsSetupDone": "Lyrion is set up.",
        "msg.lmsSetupFailed": "Could not finish the Lyrion setup.",
        "msg.playlistdirSaved": "Playlist folder saved.",
        "msg.playlistdirNotWritable": "Could not use {path} as the playlist folder.",
        "msg.pathMissing": "Path missing.",
        "msg.pathNotAllowed": "This path is not allowed.",
        "msg.folderMissing": "The folder {path} does not exist.",
        "msg.smbFieldsRequired": "Server and share name are required.",
        "msg.mountFailed": "Mount failed: {detail}",
        "msg.badDevice": "Invalid device.",
        "msg.diskNotFound": "Disk not found, or it is a system disk.",
        "msg.sourceNotFound": "Source not found.",
        "msg.noChange": "No change needed.",
        "msg.subpathNotSupported": "This source type doesn't support a subfolder.",
        "msg.subpathSaved": "Subfolder saved — the library is being updated.",
        "msg.rebootRequired": "Saved — reboot the device for this to take effect.",
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
        "sources.usbAttention": "Dispositivi USB da controllare",
        "sources.usbNeedsFormat": "Nessun filesystem riconosciuto — formattala da un computer.",
        "sources.usbMountError": "Errore di montaggio",
        "sources.usbRetry": "Riprova",
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
        "sources.smbRw": "Consenti scrittura (necessario per usarla come destinazione del rip CD)",
        "sources.smbMakeRw": "Rendi scrivibile",
        "sources.smbMakeRo": "Rendi sola lettura",
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
        "sources.playlistdirTitle": "Cartella playlist",
        "sources.playlistdirHint": "Dove Lyrion salva le playlist che crei dal player. Per la maggior parte dei casi va bene quella predefinita — scegli una cartella sul tuo disco se le vuoi vicino alla musica.",
        "sources.playlistdirCurrent": "Cartella attuale",
        "sources.playlistdirUse": "Usa questa cartella",
        "sources.playlistdirDefault": "Ripristina predefinita",
        "sources.playlistdirSaving": "Salvataggio…",
        "sources.applying": "Applico…",
        "sources.applied": "Fatto ✓",
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
        "msg.skinInvalid": "Valore skin non valido.",
        "msg.skinBusy": "Un cambio di skin è già in corso.",
        "msg.skinLmsMissing": "Lyrion non è installato su questo dispositivo.",
        "msg.skinInstalling": "Installazione dell'interfaccia web Material…",
        "msg.skinApplying": "Applicazione della skin…",
        "msg.skinApplied": "Skin applicata.",
        "msg.skinInstallFailed": "Impossibile scaricare l'interfaccia web Material. Controlla la connessione di rete e riprova.",
        "msg.skinApplyFailed": "Impossibile applicare la skin.",
        "msg.lmsSetupBusy": "La configurazione di Lyrion è già in corso.",
        "msg.lmsSetupBadPlugin": "Plugin sconosciuto.",
        "msg.lmsSetupInstalling": "Installazione dei servizi selezionati…",
        "msg.lmsSetupApplying": "Completamento della configurazione di Lyrion…",
        "msg.lmsSetupDone": "Lyrion è configurato.",
        "msg.lmsSetupFailed": "Impossibile completare la configurazione di Lyrion.",
        "msg.playlistdirSaved": "Cartella playlist salvata.",
        "msg.playlistdirNotWritable": "Impossibile usare {path} come cartella playlist.",
        "msg.pathMissing": "Percorso mancante.",
        "msg.pathNotAllowed": "Percorso non consentito.",
        "msg.folderMissing": "La cartella {path} non esiste.",
        "msg.smbFieldsRequired": "Server e nome condivisione obbligatori.",
        "msg.mountFailed": "Mount fallito: {detail}",
        "msg.badDevice": "Device non valido.",
        "msg.diskNotFound": "Disco non trovato o di sistema.",
        "msg.sourceNotFound": "Sorgente non trovata.",
        "msg.noChange": "Nessuna modifica necessaria.",
        "msg.subpathNotSupported": "Questo tipo di sorgente non supporta una sottocartella.",
        "msg.subpathSaved": "Sottocartella salvata — la libreria si sta aggiornando.",
        "msg.rebootRequired": "Salvato — riavvia il dispositivo perché la modifica abbia effetto.",
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
    # with ?setup=1): the library scan is kicked off once at the end of the
    # setup wizard (see _lms_setup_apply), so "Apply & rescan library" is
    # misleading/redundant here — swap in setup-appropriate copy for just these
    # two strings, in whichever language is active. Overriding this local dict
    # (not SOURCES_I18N itself) leaves the normal Settings -> Sources page's
    # wording untouched.
    if request.args.get("setup") == "1":
        strings["sources.apply"] = {"en": "Save sources", "it": "Salva sorgenti"}.get(lang, "Save sources")
        strings["sources.applyHint"] = {
            "en": "Saves the sources above. Your library is scanned once, at the end of the setup.",
            "it": "Salva le sorgenti qui sopra. La libreria viene scansionata una volta sola, al termine della configurazione.",
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

  <div id="usbSection" style="display:none">
  <h2 data-i18n="sources.usbAttention"></h2>
  <div class="card" id="usbList"></div>
  </div>

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
    <div style="height:10px"></div>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--silver)">
      <input type="checkbox" id="smbRw" style="width:auto"> <span data-i18n="sources.smbRw"></span>
    </label>
    <div style="height:12px"></div>
    <button class="ghost" onclick="addSmb()" data-i18n="sources.mountAndAdd"></button>
    <div class="msg" id="smbMsg"></div>
  </div>

  <h2 data-i18n="sources.playlistdirTitle"></h2>
  <div class="card">
    <p class="hint" style="margin:0 0 10px" data-i18n="sources.playlistdirHint"></p>
    <label data-i18n="sources.playlistdirCurrent"></label>
    <input id="playlistdir" placeholder="/var/lib/squeezeboxserver/playlists">
    <div style="height:10px"></div>
    <div class="row">
      <button class="ghost" onclick="savePlaylistdir()" data-i18n="sources.playlistdirUse"></button>
      <button class="ghost" onclick="resetPlaylistdir()" data-i18n="sources.playlistdirDefault"></button>
    </div>
    <div class="msg" id="playlistdirMsg"></div>
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
// A remote (non-localhost) visit — reached either embedded in the web admin's
// Settings/Setup pages (see admin-webui's SourcesFrame.vue, which mints this
// token itself) or via webui_server.py's own sources_app() route — carries a
// pairing token in the URL (?token=...). Attach it to every call this page
// makes so /api/* routes that now require pairing (see _require_pair_token())
// keep working from a plain phone/PC browser, not just from the Electron
// kiosk (which is exempt via 127.0.0.1). Backup/restore lives natively in the
// web admin's own Settings page now (Vue, calling the same /api/backup/*
// endpoints directly) — this page no longer duplicates it.
const QS = new URLSearchParams(location.search);
const PAIR_TOKEN = QS.get('token') || '';
const LANG = document.documentElement.lang || 'it';
// Reached mid first-boot setup (webui_server.py's captive page links here
// with ?setup=1): Apply shouldn't force an immediate Lyrion restart/scan,
// since the wizard applies the final source list itself, once, right before
// handing off to Lyrion's own setup wizard.
const SETUP_MODE = QS.get('setup') === '1';

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
    const tag=isSmb?(s.rw?T('sources.smbTag')+' · RW':T('sources.smbTag')):isInternal?T('sources.internal.tag'):isUsb?'USB':T('sources.local');
    const rwBtn=isSmb?`<button class="ghost" onclick="setSmbRw('${s.id}',${s.rw?'false':'true'})">${esc(s.rw?T('sources.smbMakeRo'):T('sources.smbMakeRw'))}</button>`:'';
    return `<div class="src"><div class="meta"><div class="name">${esc(s.name)}<span class="tag">${esc(tag)}</span></div>
      <div class="sub">${sub} · ${status}</div></div>
      <div style="display:flex;gap:6px">${rwBtn}<button class="danger" onclick="rm('${s.id}')">${esc(T('sources.remove'))}</button></div></div>`;
  }).join('');
}
async function addLocal(){
  const path=document.getElementById('localPath').value.trim();
  const m=document.getElementById('localMsg'); m.textContent='…';
  const r=await j('/api/sources/local',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  m.textContent=r.success?T('sources.added'):(r.message||T('sources.error')); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){document.getElementById('localPath').value='';load();}
}
// Playlist folder — where Lyrion saves playlists created from the player.
// ensure_playlistdir() already picks a working default; this is the override,
// the last thing Lyrion's own setup wizard used to ask for.
let PLAYLISTDIR_DEFAULT = '';
async function loadPlaylistdir(){
  const d = await j('/api/playlistdir');
  if (!d || !d.success) return;
  PLAYLISTDIR_DEFAULT = d.default || '';
  document.getElementById('playlistdir').value = d.path || '';
}
async function setPlaylistdir(path){
  const m=document.getElementById('playlistdirMsg'); m.textContent=T('sources.playlistdirSaving'); m.className='msg';
  const r=await j('/api/playlistdir',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path})});
  m.textContent=r.success?(r.message||T('sources.applied')):(r.message||T('sources.error'));
  m.className='msg '+(r.success?'ok':'bad');
  if(r.success) document.getElementById('playlistdir').value=r.path||path;
}
function savePlaylistdir(){
  const path=document.getElementById('playlistdir').value.trim();
  if(!path) return;
  setPlaylistdir(path);
}
function resetPlaylistdir(){ if(PLAYLISTDIR_DEFAULT) setPlaylistdir(PLAYLISTDIR_DEFAULT); }
async function addSmb(){
  const body={server:smbServer.value,share:smbShare.value,username:smbUser.value,password:smbPass.value,rw:document.getElementById('smbRw').checked};
  const m=document.getElementById('smbMsg'); m.textContent=T('sources.mounting');
  const r=await j('/api/sources/smb',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  m.textContent=r.success?(T('sources.mounted')+' '+(r.message||'')):(r.message||T('sources.error')); m.className='msg '+(r.success?'ok':'bad');
  if(r.success){smbPass.value='';document.getElementById('smbRw').checked=false;load();}
}
async function rm(id){ await j('/api/sources/'+id,{method:'DELETE'}); load(); }
async function setSmbRw(id,rw){
  const m=document.getElementById('smbMsg'); m.textContent=T('sources.mounting');
  const r=await j('/api/sources/'+id+'/rw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rw})});
  m.textContent=r.success?(r.message||T('sources.mounted')):(r.message||T('sources.error')); m.className='msg '+(r.success?'ok':'bad');
  if(r.success) load();
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

// ── USB devices needing attention ───────────────────────────────────
// Healthy USB drives auto-adopt the instant they're plugged in (mount
// read-write + Samba share, see sources_server.py's usb_sync()) — no action
// here, they just show up in the sources list above. This panel only ever
// lists what auto-adoption couldn't handle on its own: no recognized
// filesystem, or a failed mount attempt. Device paths are kept in an array
// and referenced by index in onclick handlers, so a label with quotes/
// specials can never break the markup.
let usbDevices=[];
async function loadUsb(){
  let d; try{ d=await j('/api/usb'); }catch(e){ return; }
  const section=document.getElementById('usbSection');
  const el=document.getElementById('usbList'); usbDevices=[];
  if(!d.disks || !d.disks.length){ section.style.display='none'; return; }
  section.style.display='';
  el.innerHTML=d.disks.map(dk=>{
    const devi=usbDevices.push(dk.path||'')-1;
    const tag=`USB${dk.fstype?(' '+esc(dk.fstype)):''}${dk.size?(' · '+esc(dk.size)):''}`;
    const head=`<div class="name">${esc(dk.label)||'USB'}<span class="tag">${tag}</span></div>`;
    const reason=`<div class="sub" style="color:#e66">${dk.needs_format?esc(T('sources.usbNeedsFormat')):esc(T('sources.usbMountError'))+': '+esc(dk.error||'')}</div>`;
    const retry=(!dk.needs_format&&dk.path)?`<button class="ghost" onclick="retryUsb(${devi})">${esc(T('sources.usbRetry'))}</button>`:'';
    return `<div style="margin-bottom:14px">${head}${reason}<div style="height:8px"></div><div class="row" style="gap:8px">${retry}</div></div>`;
  }).join('');
}
async function retryUsb(i){
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
loadPlaylistdir();
// sources_server.py auto-adopts USB drives in the background, so poll the
// active-sources list too — matches loadUsb()'s cadence, picks up a freshly
// mounted drive without a manual reload.
setInterval(load, 4000);
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
    # Auto-adopt USB sticks/drives as soon as they're plugged in (mount
    # read-write + Samba share, no user action needed — see usb_sync()).
    threading.Thread(target=usb_monitor, daemon=True, name="usb-monitor").start()
    # One-time cleanup of "local" sources left over from the old ephemeral
    # read-only USB browse mount (removed — see the USB drives section above).
    try:
        _migrate_stale_usb_sources()
    except Exception as e:
        print(f"[sources] _migrate_stale_usb_sources error: {e}")
    # Watch for completed disk-format jobs and adopt the resulting partition.
    threading.Thread(target=_format_watcher, daemon=True, name="format-watcher").start()
    # Make sure Lyrion has a writable playlist folder ("save as playlist")
    try:
        ensure_playlistdir()
    except Exception as e:
        print(f"[sources] ensure_playlistdir error: {e}")
    # Let Tailscale-only clients (e.g. Lyrplay) through Lyrion's own IP-based
    # access control, if the operator has it enabled.
    try:
        ensure_lms_trusted_networks()
    except Exception as e:
        print(f"[sources] ensure_lms_trusted_networks error: {e}")
    # Auto-install Material Skin (and sync the Osmium theme files) whenever a
    # local Lyrion is present — see _lms_skin_autoinstall for the contract.
    threading.Thread(target=_lms_skin_autoinstall, daemon=True,
                     name="lms-skin-autoinstall").start()
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
