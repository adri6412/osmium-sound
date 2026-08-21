#!/usr/bin/env python3
"""
HiFi Player — backup/restore core (shared library).

Imported by BOTH the HTTP layer (`sources_server.py`, which exposes the routes)
and the async worker (`/usr/local/sbin/hifi-backup-run.py`, which builds a
generation on-device). Keeping the manifest in one place is the whole point:
the set of paths that may be written by a restore MUST be exactly the set that
a backup can produce, and two copies of that table would drift.

WHAT THIS BACKS UP — and what it deliberately does not
------------------------------------------------------
This is a *profile* backup: user configuration and user-created state. It is
NOT a rootfs image, and that is a design decision, not a limitation. The OS on
this appliance is already reproducible from the install ISO plus the cumulative,
idempotent OS-update migrations, so restoring OS files would only ever fight the
updater: `OS_VERSION`/`SYSTEM_VERSION` are the updater's own bookkeeping, and
rolling them back would make a device claim to be running a release it isn't.
(A rootfs restore is also what forces DietPi's dietpi-backup to reconcile fstab
UUIDs and re-run update-grub on restore — a class of risk this appliance has no
reason to take on, and one its OTA rules forbid outright.)

Everything is organised into CATEGORIES, and each category is flagged secret or
not. Secret categories (Wi-Fi PSKs, SMB passwords, the web-admin account, the
Bluetooth link keys) are only ever written into an archive when the user has
supplied a passphrase — a plaintext `.tar.gz` sitting in a Downloads folder must
not be a copy of the household's credentials. The one exception is handled by
redaction rather than exclusion: see `_transform_sources`.

INTEGRITY MODEL
---------------
A generation on disk is a directory containing the archive plus a
`manifest.json` that is written LAST. A generation without a manifest is
incomplete by definition — it is never listed, never restorable, and is pruned
on the next run. This is what makes an interrupted or power-cut backup
self-evident instead of silently passing as a good one.

The manifest carries a sha256 for every member, verified before that member is
written back during a restore, and (when encrypted) an HMAC over the ciphertext
that is checked BEFORE decryption is attempted.

TESTABILITY
-----------
Every path constant here is absolute and anchored at "/", but every function
that touches the filesystem takes a `root` prefix. Tests point `root` at a temp
directory and exercise the real code paths without needing a live appliance —
archive member names are always root-relative, so an archive built under a fake
root restores identically under the real one.
"""
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone

try:                        # only used to validate Lyrion's YAML prefs
    import yaml             # python3-yaml ships on the appliance
except Exception:           # pragma: no cover - dev machines may lack it
    yaml = None


# ── layout ───────────────────────────────────────────────────────────
SCHEMA = 1
STORE_DIR = "/var/lib/hifi-player/backups"
STATUS_FILE = "/run/hifi-backup-status.json"
SETTINGS_FILE = "/etc/hifi-player/backup.json"
ARCHIVE_NAME = "backup.tar.gz"
ENC_NAME = "backup.tar.gz.enc"
MANIFEST_NAME = "manifest.json"
HISTORY_NAME = "history"
# The manifest is also carried INSIDE the flat archive, as its last member.
# That is what lets a downloaded file be restored on a different device (or
# after a reinstall) without the generation directory it came from — and the
# dotted name keeps it out of every category's allow-list, so a restore can
# never mistake it for a file to write somewhere.
MANIFEST_MEMBER = ".hifi-manifest.json"
DEFAULT_KEEP = 5
# Headroom demanded on top of the estimated archive size before anything is
# written. Same spirit as the free-space guard in hifi-ota-update.sh: a full
# disk mid-tar silently truncates, and a truncated backup that looks fine is
# worse than no backup at all.
FREE_SPACE_MARGIN = 64 * 1024 * 1024


# ── never, under any circumstances ───────────────────────────────────
# Checked on the way IN (nothing here is ever archived) and on the way OUT
# (nothing here is ever written by a restore, even if a crafted archive
# contains it). Two independent chances to catch a mistake.
DENY_FILES = frozenset((
    # OTA bookkeeping — restoring these desyncs the updater's view of reality.
    "/etc/hifi-player/OS_VERSION",
    "/etc/hifi-player/SYSTEM_VERSION",
    "/etc/hifi-player/UI_VERSION",
    # Trust root for the signed OS channel. An archive must never be able to
    # swap the key that decides which OS payloads are allowed to run as root.
    "/etc/hifi-player/ota-pubkey.pem",
    # Per-device identity: cookie signing key. Cloning it across devices would
    # let one box's session cookies work on another. A restored webui.db is
    # enough to get the account back.
    "/etc/hifi-player/webui-secret.key",
    # Support/provisioning state that is re-derived, not user config.
    "/etc/hifi-player/github-support-pat",
    "/etc/hifi-player/shell-account",
    "/etc/hifi-player/provisioning-pending",
    "/etc/hifi-player/provisioning-state.json",
    "/etc/machine-id",
    "/var/lib/dbus/machine-id",
    # The OS migration ledger is history, not configuration.
    "/var/lib/hifi-player/os-migrations",
))
DENY_PREFIXES = (
    "/var/lib/hifi-player/backups/",   # no backups inside backups
    "/etc/ssh/",                       # host keys are machine identity
)


def is_denied(logical):
    """True if this "/"-anchored path may never be archived or restored."""
    if logical in DENY_FILES:
        return True
    return any(logical.startswith(p) for p in DENY_PREFIXES)


# ── the manifest ─────────────────────────────────────────────────────
# Kept in sync with hifi-factory-reset.sh, which enumerates the same "this is
# user state" surface from the opposite direction (it deletes what this saves).
# When one changes, check the other.
#
# entry kinds:
#   ("file", "/abs/path")                    a single regular file
#   ("dir",  "/abs/dir", (excluded names,))  a directory, non-recursive on the
#                                            excluded top-level names
CATEGORIES = {
    "core": {
        "secret": False,
        "entries": [
            ("file", "/etc/hifi-player/pointer-enabled"),
            ("file", "/etc/hifi-player/dsp.json"),
            ("file", "/etc/hifi-player/dsp-presets.json"),
            ("file", "/etc/hifi-player/ota-channel"),
            ("file", "/etc/hifi-player/display-mode"),
            ("file", "/etc/hifi-player/ui-resolution"),
            ("file", "/etc/hifi-player/lyrion-channel"),
            ("file", "/etc/hifi-player/lms-skin"),
            # The standard Debian file, not a custom /etc/hifi-player/ one —
            # same reasoning as /etc/timezone below. Every appliance ships
            # with the same hardcoded "hifiplayer" (0100-system-setup.hook.
            # chroot), so two units on a LAN collide on hifiplayer.local until
            # the owner picks a name in the setup wizard (api_server.py's
            # set_device_name). That chosen name is exactly the kind of user
            # state this profile exists to protect, unlike /etc/machine-id or
            # the SSH host keys (DENY_FILES/DENY_PREFIXES above), which are
            # per-installation identity and must never travel between boxes.
            # A restore only writes this file back -- it does NOT itself
            # re-run `hostnamectl set-hostname`, so sources_server.py's
            # _restore_apply_side_effects re-applies it from the restored
            # value, the same pattern used for /etc/timezone below.
            ("file", "/etc/hostname"),
            # The standard Debian file (not a custom /etc/hifi-player/ one).
            # It holds only the IANA name: /etc/localtime, the symlink every
            # clock on the box actually resolves against, is a separate
            # artifact (api_server.py's set_timezone writes both, precisely
            # because systemd's timedated does not maintain this one on
            # trixie). A restore only writes this file back -- it does NOT
            # re-derive /etc/localtime, so sources_server.py's
            # _restore_apply_side_effects re-applies the restored name through
            # api_server's /timezone to bring the symlink along with it. Keep
            # that in mind if this entry ever moves/renames.
            ("file", "/etc/timezone"),
            ("file", "/etc/default/squeezelite"),
            ("file", "/etc/camilladsp/config.yml"),
            ("file", "/var/lib/hifi-player/dsp-target"),
            ("file", "/var/lib/hifi-player/roomcorr-result.json"),
            ("dir", "/etc/camilladsp/filters", ()),
        ],
    },
    "sources": {
        # NOT flagged secret: the source list is the single most valuable thing
        # to get back, and losing it from every unencrypted backup would be a
        # regression against the current behaviour. The credentials inside are
        # handled by redaction instead — see _transform_sources.
        "secret": False,
        "entries": [("file", "/etc/hifi-sources.json")],
    },
    "lyrion": {
        "secret": False,
        "entries": [
            # Both package layouts: squeezeboxserver is the Debian package
            # name, lyrionmusicserver the newer .debs. Whichever exists wins;
            # having both listed costs nothing.
            ("dir", "/var/lib/squeezeboxserver/prefs", ()),
            ("dir", "/var/lib/squeezeboxserver/playlists", ()),
            ("dir", "/var/lib/lyrionmusicserver/prefs", ()),
            ("dir", "/var/lib/lyrionmusicserver/playlists", ()),
            # cache/ as a whole is deliberately absent: it is the scanned
            # library database, it is large, and Lyrion rebuilds it from the
            # music itself. Backing it up would dominate the archive size
            # while restoring nothing the user would miss. InstalledPlugins/
            # is the one exception carved out of it below: it is small (just
            # which plugins are installed/enabled, not any scanned data) and
            # losing it means every plugin — including a non-default default
            # skin like Material — has to be reinstalled by hand after a
            # restore, which is a much worse first impression than the extra
            # few KB cost.
            ("dir", "/var/lib/squeezeboxserver/cache/InstalledPlugins/Plugins", ()),
            ("dir", "/var/lib/lyrionmusicserver/cache/InstalledPlugins/Plugins", ()),
        ],
    },
    "network": {
        "secret": True,
        "entries": [("dir", "/etc/NetworkManager/system-connections", ())],
    },
    "accounts": {
        "secret": True,
        "entries": [
            ("file", "/etc/hifi-player/webui.db"),
            ("file", "/etc/hifi-player/samba-cred.json"),
            ("file", "/etc/hifi-pairing-tokens.json"),
        ],
    },
    "bluetooth": {
        "secret": True,
        "entries": [
            ("file", "/etc/hifi-player/bluetooth.json"),
            ("dir", "/var/lib/bluetooth", ()),
        ],
    },
}

# Categories a scheduled (unattended) run can produce. A timer has nobody to
# ask for a passphrase and we never persist one, so an automatic backup is
# simply the non-secret half of the profile — stated plainly in the UI rather
# than papered over.
UNATTENDED_CATEGORIES = tuple(k for k, v in CATEGORIES.items() if not v["secret"])
ALL_CATEGORIES = tuple(CATEGORIES.keys())
SECRET_CATEGORIES = tuple(k for k, v in CATEGORIES.items() if v["secret"])


def selected_categories(requested, encrypted):
    """Normalise a requested category list.

    Unknown names are dropped. Secret categories are dropped unless the archive
    is going to be encrypted — this is the single chokepoint that decides
    whether credentials may be written out, so it is enforced here rather than
    at each call site.
    """
    if not requested:
        requested = ALL_CATEGORIES
    out = [c for c in ALL_CATEGORIES if c in set(requested)]
    if not encrypted:
        out = [c for c in out if not CATEGORIES[c]["secret"]]
    return out


# ── per-entry transforms ─────────────────────────────────────────────
# A transform returns the bytes to archive for a given source file, or None to
# skip it. This is where formats that cannot simply be copied get handled.

def _transform_sqlite(src, _ctx):
    """Consistent snapshot of a live SQLite file without stopping its daemon.

    webui.db is open and possibly mid-transaction in hifi-webui; a byte copy can
    catch a torn WAL state. sqlite3's own backup API takes a proper snapshot,
    which is why nothing here has to be stopped for the backup to be safe.
    """
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as srccon:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            with sqlite3.connect(tmp) as dstcon:
                srccon.backup(dstcon)
            with open(tmp, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _transform_sources(src, ctx):
    """Music sources, with SMB passwords stripped on unencrypted archives.

    The source list itself is not a secret and is the thing users most want
    back, so it stays in every backup. The passwords inside it are a secret, so
    an unencrypted archive gets them blanked and the manifest records that the
    file was redacted. On restore, a blank password is treated as "keep whatever
    this device already has" (see merge_sources_state), so re-restoring onto the
    same box loses nothing at all.
    """
    with open(src, "rb") as f:
        raw = f.read()
    if ctx.get("encrypted"):
        return raw
    try:
        state = json.loads(raw.decode("utf-8"))
    except Exception:
        return raw
    redacted = False
    for entry in state.get("sources", []):
        if entry.get("password"):
            entry["password"] = ""
            redacted = True
    if redacted:
        ctx.setdefault("notes", []).append("sources:redacted")
    return json.dumps(state, indent=2).encode("utf-8")


def _transform_nm_connection(src, _ctx):
    """Only Wi-Fi profiles. Ethernet profiles carry no secret and no value —
    they are just "get an IP over this cable", which any device recreates by
    itself. Same reasoning hifi-factory-reset.sh uses when it deletes Wi-Fi
    profiles but deliberately leaves Ethernet alone."""
    with open(src, "rb") as f:
        raw = f.read()
    if b"type=wifi" in raw or b"802-11-wireless" in raw:
        return raw
    return None


def _transform_lyrion_prefs(src, ctx):
    """Lyrion rewrites its YAML prefs while running, so a copy can catch a
    half-written file. Rather than stopping the music to avoid that (which is
    what a whole-system backup tool has to do), read it and check it parses —
    retry once, and if it still does not, skip that one file and say so in the
    manifest. Nothing is silently archived broken.

    server.prefs also gets its server_uuid dropped: it identifies this
    specific Lyrion instance on the LAN (SqueezeCenter/SB discovery), so a
    backup that still carried it would hand a second server — set up from
    this same backup, e.g. a spare box — a duplicate UUID and confuse
    discovery for both. Lyrion just mints a fresh one on next start if the
    key is missing, so dropping it costs nothing on a normal same-device
    restore either."""
    for attempt in (1, 2):
        with open(src, "rb") as f:
            raw = f.read()
        if yaml is None:
            return raw
        try:
            data = yaml.safe_load(raw.decode("utf-8", "replace"))
        except Exception:
            if attempt == 2:
                ctx.setdefault("notes", []).append(f"skipped-unparsable:{src}")
                return None
            continue
        if os.path.basename(src) == "server.prefs" and isinstance(data, dict) and "server_uuid" in data:
            del data["server_uuid"]
            ctx.setdefault("notes", []).append(f"stripped-server-uuid:{src}")
            return yaml.safe_dump(data, default_flow_style=False, allow_unicode=True).encode("utf-8")
        return raw
    return None


def _transform_for(logical):
    if logical == "/etc/hifi-player/webui.db":
        return _transform_sqlite
    if logical == "/etc/hifi-sources.json":
        return _transform_sources
    if logical.startswith("/etc/NetworkManager/system-connections/"):
        return _transform_nm_connection
    if "/prefs/" in logical and logical.endswith(".prefs"):
        return _transform_lyrion_prefs
    return None


# ── enumeration ──────────────────────────────────────────────────────
def _abs(root, logical):
    """Map a "/"-anchored logical path onto the (possibly faked) filesystem."""
    return os.path.join(root, logical.lstrip("/")) if root != "/" else logical


def iter_members(categories, root="/"):
    """Yield (logical_path, real_path) for everything the given categories
    cover and that actually exists. Order is stable so archives are diffable."""
    for cat in categories:
        spec = CATEGORIES.get(cat)
        if not spec:
            continue
        for entry in spec["entries"]:
            if entry[0] == "file":
                logical = entry[1]
                if is_denied(logical):
                    continue
                real = _abs(root, logical)
                if os.path.isfile(real) and not os.path.islink(real):
                    yield logical, real
            else:
                _, logical_dir, excluded = entry
                real_dir = _abs(root, logical_dir)
                if not os.path.isdir(real_dir):
                    continue
                for dirpath, dirnames, filenames in os.walk(real_dir):
                    rel_dir = os.path.relpath(dirpath, real_dir)
                    if rel_dir == ".":
                        dirnames[:] = [d for d in dirnames if d not in excluded]
                    for name in sorted(filenames):
                        real = os.path.join(dirpath, name)
                        if os.path.islink(real) or not os.path.isfile(real):
                            continue
                        rel = os.path.relpath(real, real_dir).replace(os.sep, "/")
                        logical = f"{logical_dir}/{rel}"
                        if is_denied(logical):
                            continue
                        yield logical, real


def estimate_size(categories, root="/"):
    """Sum of the bytes we are about to read. Used for the free-space guard —
    an over-estimate (compression is ignored) is exactly what we want here."""
    total = 0
    for _logical, real in iter_members(categories, root):
        try:
            total += os.path.getsize(real)
        except OSError:
            pass
    return total


# ── archive construction ─────────────────────────────────────────────
def build_archive(dest_path, categories, root="/", encrypted=False, extra=None):
    """Write a .tar.gz of `categories` to `dest_path`; return its manifest.

    The manifest is appended as the archive's LAST member, which is possible in
    a single streaming pass because tar is sequential — the per-member digests
    are known by the time the last member is written. That last member is also
    the archive's completeness marker: a truncated file simply has no manifest.

    Nothing here writes the generation's own `manifest.json`; the caller does
    that, after any encryption step, so an aborted build can never leave behind
    a directory that looks complete.
    """
    ctx = {"encrypted": encrypted, "notes": []}
    members = {}
    manifest = dict(extra or {})
    tmp = dest_path + ".part"
    with tarfile.open(tmp, "w:gz") as tar:
        for logical, real in iter_members(categories, root):
            transform = _transform_for(logical)
            try:
                if transform:
                    data = transform(real, ctx)
                    if data is None:
                        continue
                else:
                    with open(real, "rb") as f:
                        data = f.read()
            except Exception as e:
                ctx["notes"].append(f"unreadable:{logical}:{e.__class__.__name__}")
                continue
            arc = logical.lstrip("/")
            _add_member(tar, arc, data, int(os.path.getmtime(real)))
            members[arc] = hashlib.sha256(data).hexdigest()

        manifest.update({"schema": SCHEMA, "categories": list(categories),
                         "members": members, "notes": ctx["notes"]})
        _add_member(tar, MANIFEST_MEMBER,
                    json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
    os.replace(tmp, dest_path)
    return manifest


def _add_member(tar, arc, data, mtime=None):
    info = tarfile.TarInfo(arc)
    info.size = len(data)
    info.mode = 0o600
    if mtime is not None:
        info.mtime = mtime
    tar.addfile(info, _BytesReader(data))


def read_embedded_manifest(tar):
    """The manifest carried inside an archive, or None for a legacy backup."""
    try:
        member = tar.getmember(MANIFEST_MEMBER)
    except KeyError:
        return None
    try:
        return json.loads(tar.extractfile(member).read().decode("utf-8"))
    except Exception:
        return None


class _BytesReader:
    """Minimal file-like wrapper so tarfile can stream transformed bytes."""

    def __init__(self, data):
        self._data = data
        self._pos = 0

    def read(self, size=-1):
        if size is None or size < 0:
            chunk = self._data[self._pos:]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


# ── encryption (encrypt-then-MAC) ────────────────────────────────────
# openssl is already on the image; `age` is not, and it cannot take a
# passphrase non-interactively (no --passphrase-file), so it is unusable from a
# daemon. openssl enc gives confidentiality but no authentication, so an HMAC
# over the ciphertext is computed separately and verified BEFORE decryption —
# a tampered or truncated archive is rejected without its bytes ever being fed
# to the cipher, and a wrong passphrase fails here rather than producing
# garbage that a restore would then try to interpret.
_KDF_ITER = 600000
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1


class BackupError(Exception):
    """Anything that must abort a backup or restore with a message for the UI."""


def _hmac_key(passphrase, salt):
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt,
                          n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                          dklen=32, maxmem=64 * 1024 * 1024)


def _file_hmac(path, key):
    mac = hmac.new(key, digestmod=hashlib.sha256)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            mac.update(chunk)
    return mac.hexdigest()


def _openssl(args, passphrase):
    try:
        proc = subprocess.run(["openssl"] + args, input=passphrase + "\n",
                              capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        # Never fall back to writing the plaintext: the whole reason a
        # passphrase was given is that this archive contains credentials.
        raise BackupError("openssl non disponibile: backup cifrato rifiutato")
    except subprocess.TimeoutExpired:
        raise BackupError("Timeout durante la cifratura")
    if proc.returncode != 0:
        raise BackupError("Cifratura/decifratura fallita (passphrase errata?)")


def encrypt_archive(plain_path, enc_path, passphrase):
    """Encrypt in place-ish; returns the manifest's `enc` block."""
    _openssl(["enc", "-aes-256-ctr", "-pbkdf2", "-iter", str(_KDF_ITER),
              "-md", "sha512", "-salt", "-pass", "stdin",
              "-in", plain_path, "-out", enc_path], passphrase)
    salt = os.urandom(16)
    mac = _file_hmac(enc_path, _hmac_key(passphrase, salt))
    return {"cipher": "aes-256-ctr", "kdf": f"pbkdf2-sha512-{_KDF_ITER}",
            "mac": "hmac-sha256-scrypt", "salt": salt.hex(), "hmac": mac}


def decrypt_archive(enc_path, plain_path, passphrase, enc_meta):
    """Verify the MAC first, then decrypt. Raises BackupError on either."""
    salt = bytes.fromhex(enc_meta.get("salt") or "")
    expected = enc_meta.get("hmac") or ""
    actual = _file_hmac(enc_path, _hmac_key(passphrase, salt))
    if not hmac.compare_digest(actual, expected):
        raise BackupError("Passphrase errata o archivio manomesso")
    _openssl(["enc", "-d", "-aes-256-ctr", "-pbkdf2", "-iter", str(_KDF_ITER),
              "-md", "sha512", "-pass", "stdin",
              "-in", enc_path, "-out", plain_path], passphrase)


# ── the downloadable file ────────────────────────────────────────────
# Unencrypted backups are the flat archive itself: config files at their normal
# paths plus the manifest member. That format is readable by the restore code
# that shipped before this feature (it just ignores the manifest member), so a
# plain backup keeps working across the upgrade in both directions.
#
# Encrypted backups cannot be flat — the whole point is that the paths and
# contents are unreadable — so they are wrapped: an outer tar carrying the
# manifest (which holds the KDF salt and the MAC) next to the ciphertext. The
# wrapper is what makes an encrypted download restorable anywhere, instead of
# only from the generation directory it was produced in.
def wrap_encrypted(dest_path, manifest, enc_path):
    with tarfile.open(dest_path, "w:gz") as tar:
        _add_member(tar, MANIFEST_NAME,
                    json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        tar.add(enc_path, arcname=ENC_NAME)


def open_backup(path, workdir, passphrase=""):
    """Open a backup file of either shape.

    Returns (tarfile, manifest). The caller closes the tarfile and removes
    `workdir`. Raises BackupError for anything the user needs to be told about
    (wrong passphrase, tampering, unreadable archive).
    """
    try:
        outer = tarfile.open(path, "r:gz")
    except Exception:
        raise BackupError("Archivio non valido o corrotto")

    names = set(outer.getnames())
    if ENC_NAME not in names:
        return outer, read_embedded_manifest(outer)

    # Encrypted wrapper.
    try:
        with outer:
            manifest = json.loads(
                outer.extractfile(MANIFEST_NAME).read().decode("utf-8"))
            enc_meta = manifest.get("enc") or {}
            enc_path = os.path.join(workdir, ENC_NAME)
            with open(enc_path, "wb") as out, outer.extractfile(ENC_NAME) as src:
                shutil.copyfileobj(src, out)
    except BackupError:
        raise
    except Exception:
        raise BackupError("Archivio cifrato non valido")

    if not passphrase:
        raise BackupError("Questo backup è cifrato: serve la passphrase")

    plain_path = os.path.join(workdir, ARCHIVE_NAME)
    decrypt_archive(enc_path, plain_path, passphrase, enc_meta)
    try:
        inner = tarfile.open(plain_path, "r:gz")
    except Exception:
        raise BackupError("Archivio cifrato non valido")
    return inner, (read_embedded_manifest(inner) or manifest)


# ── restore mapping ──────────────────────────────────────────────────
def restore_dest_for_member(name, categories, root="/"):
    """Map a tar member name to the absolute path it may be written to, or None.

    Never trusts the member's own path: the name is normalised and then matched
    against the allow-list built from `categories`. Anything that does not match
    exactly (or sit under an allowed directory) is silently ignored, so path
    traversal, absolute paths and symlink tricks in a crafted archive have
    nothing to aim at.
    """
    logical = os.path.normpath("/" + name.replace("\\", "/").lstrip("/"))
    logical = logical.replace(os.sep, "/")
    if is_denied(logical):
        return None
    for cat in categories:
        spec = CATEGORIES.get(cat)
        if not spec:
            continue
        for entry in spec["entries"]:
            if entry[0] == "file":
                if logical == entry[1]:
                    return _abs(root, logical)
            else:
                prefix = entry[1].rstrip("/") + "/"
                if logical.startswith(prefix) and logical != entry[1]:
                    return _abs(root, logical)
    return None


def categories_in_manifest(manifest):
    """Categories a manifest claims to hold; legacy archives (no manifest, or
    one without the field) are treated as the pre-categories config backup,
    which is exactly what "core" + "sources" cover."""
    if not manifest:
        return ("core", "sources")
    cats = manifest.get("categories")
    if not cats:
        return ("core", "sources")
    return tuple(c for c in cats if c in CATEGORIES)


def merge_sources_state(restored_raw, current_raw):
    """Reinstate SMB passwords the archive had redacted.

    An unencrypted backup blanks credentials (see _transform_sources). When such
    a backup is restored onto the device it came from, the passwords are still
    sitting in the live file, so match on server+share and keep them — the user
    gets their sources back working instead of getting a list of shares that all
    fail to mount.
    """
    try:
        restored = json.loads(restored_raw.decode("utf-8"))
        current = json.loads(current_raw.decode("utf-8"))
    except Exception:
        return restored_raw
    have = {}
    for entry in current.get("sources", []):
        key = (entry.get("server"), entry.get("share"))
        if entry.get("password"):
            have[key] = entry["password"]
    changed = False
    for entry in restored.get("sources", []):
        key = (entry.get("server"), entry.get("share"))
        if not entry.get("password") and key in have:
            entry["password"] = have[key]
            changed = True
    if not changed:
        return restored_raw
    return json.dumps(restored, indent=2).encode("utf-8")


# ── generations on disk ──────────────────────────────────────────────
def _gen_dir(store, gen_id):
    return os.path.join(store, gen_id)


def read_manifest(store, gen_id):
    try:
        with open(os.path.join(_gen_dir(store, gen_id), MANIFEST_NAME)) as f:
            return json.load(f)
    except Exception:
        return None


def archive_path(store, gen_id, manifest=None):
    manifest = manifest if manifest is not None else read_manifest(store, gen_id)
    name = ENC_NAME if (manifest or {}).get("enc") else ARCHIVE_NAME
    return os.path.join(_gen_dir(store, gen_id), name)


def valid_gen_id(gen_id):
    """Generation ids are our own timestamps; anything else is a caller trying
    to reach outside the store."""
    return bool(gen_id) and len(gen_id) <= 32 and all(
        c.isdigit() or c == "-" for c in gen_id)


def list_generations(store=STORE_DIR):
    """Complete generations, newest first. A directory without a manifest is
    an interrupted build and is not listed."""
    out = []
    try:
        names = os.listdir(store)
    except OSError:
        return out
    for name in names:
        if not valid_gen_id(name) or not os.path.isdir(_gen_dir(store, name)):
            continue
        manifest = read_manifest(store, name)
        if not manifest:
            continue
        path = archive_path(store, name, manifest)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        out.append({
            "id": name,
            "created": manifest.get("created"),
            "size": size,
            "categories": manifest.get("categories", []),
            "encrypted": bool(manifest.get("enc")),
            "trigger": manifest.get("trigger", "manual"),
            "versions": manifest.get("versions", {}),
            "notes": manifest.get("notes", []),
        })
    out.sort(key=lambda g: g["id"], reverse=True)
    return out


def prune_incomplete(store=STORE_DIR):
    """Remove directories with no manifest — either a build that died partway
    or one we ourselves abandoned. Returns how many were removed."""
    removed = 0
    try:
        names = os.listdir(store)
    except OSError:
        return 0
    for name in names:
        path = _gen_dir(store, name)
        if not os.path.isdir(path) or not valid_gen_id(name):
            continue
        if read_manifest(store, name) is None:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def rotate(store=STORE_DIR, keep=DEFAULT_KEEP):
    """Keep the newest `keep` complete generations, drop the rest."""
    keep = max(1, int(keep or DEFAULT_KEEP))
    gens = list_generations(store)
    dropped = []
    for gen in gens[keep:]:
        shutil.rmtree(_gen_dir(store, gen["id"]), ignore_errors=True)
        dropped.append(gen["id"])
    return dropped


def new_gen_id(now=None):
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S")


def free_space_ok(path, need_bytes):
    """True if `path`'s filesystem can hold need_bytes plus headroom."""
    try:
        return shutil.disk_usage(path).free >= need_bytes + FREE_SPACE_MARGIN
    except OSError:
        return True         # cannot tell — do not block the backup on this


def record_history(store, line):
    """Append-only log of what happened, in the same spirit as the OS-migration
    ledger: the per-run log can be lost or overwritten, this cannot."""
    try:
        os.makedirs(store, exist_ok=True)
        with open(os.path.join(store, HISTORY_NAME), "a") as f:
            f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\t{line}\n")
    except OSError:
        pass


def read_settings(path=SETTINGS_FILE):
    """Scheduling preferences. Absent file = the shipped default (off)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception:
        data = {}
    return {
        "scheduled": bool(data.get("scheduled")),
        "keep": max(1, min(20, int(data.get("keep") or DEFAULT_KEEP))),
    }


def device_versions(root="/"):
    """Versions recorded at backup time. Informational only — they are never
    restored (they are on the deny-list), but they let a restore warn when an
    archive comes from a newer build than the one running."""
    out = {}
    for key, logical in (("os", "/etc/hifi-player/OS_VERSION"),
                         ("system", "/etc/hifi-player/SYSTEM_VERSION"),
                         ("ui", "/etc/hifi-player/UI_VERSION")):
        try:
            with open(_abs(root, logical)) as f:
                out[key] = f.read().strip()
        except OSError:
            pass
    return out
