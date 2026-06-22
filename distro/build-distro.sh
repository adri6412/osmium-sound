#!/usr/bin/env bash
#
# build-distro.sh — Build the HiFi Player Debian appliance ISO with live-build.
#
# Run this AS ROOT on a Debian machine (bookworm recommended):
#     sudo ./build-distro.sh --app-dir /path/to/linux-unpacked
#
# The Electron app must already be compiled into an unpacked directory
# (the `linux-unpacked` folder produced by electron-builder). This script
# does NOT need Node/npm — it only assembles and builds the ISO.
#
# ── Incremental / staged builds ──────────────────────────────────────
# live-build runs three stages: bootstrap → chroot → binary. They are slow to
# the left, fast to the right. Pass --stage to rebuild only what you need and
# reuse the rest (+ the package cache):
#
#   --stage all      (default) full build: bootstrap + chroot + binary
#   --stage chroot   rebuild chroot + binary (keep bootstrap & pkg cache)
#   --stage binary   rebuild ONLY the binary/ISO (reuse existing chroot)
#
# Typical loop while iterating on boot menus / splash / ISO layout:
#   sudo ./build-distro.sh --app-dir … --stage all      # once
#   sudo ./build-distro.sh --app-dir … --stage binary   # fast re-spins
#
# The Debian package cache (config/../cache/) is preserved across runs unless
# you pass --clean-cache.
#
set -euo pipefail

# ─────────────────────────── Configurable ───────────────────────────
DEBIAN_SUITE="${DEBIAN_SUITE:-bookworm}"
ARCH="${ARCH:-amd64}"
ISO_NAME="${ISO_NAME:-hifi-player-installer.iso}"
LYRION_DEB_URL="${LYRION_DEB_URL:-https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/lyrionmusicserver_9.1.0_all.deb}"
BRAND_NAME="${BRAND_NAME:-HiFi Player}"

# ─────────────────────────── Paths ──────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG="$SCRIPT_DIR/config"
APP_DIR=""
APP_VERSION=""
STAGE="all"          # all | chroot | binary
CLEAN_CACHE=0        # 1 → also wipe the Debian package cache

log()  { printf '\033[1;33m[hifi-build]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[hifi-build ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# ─────────────────────────── Args ───────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --app-dir) APP_DIR="$2"; shift 2 ;;
        --app-version) APP_VERSION="$2"; shift 2 ;;
        --lyrion-url) LYRION_DEB_URL="$2"; shift 2 ;;
        --suite) DEBIAN_SUITE="$2"; shift 2 ;;
        --stage) STAGE="$2"; shift 2 ;;
        --clean-cache) CLEAN_CACHE=1; shift ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

case "$STAGE" in
    all|chroot|binary) ;;
    *) die "Invalid --stage '$STAGE' (use: all | chroot | binary)." ;;
esac

# ─────────────────────────── Pre-flight ─────────────────────────────
[ "$(id -u)" -eq 0 ] || die "Please run as root (sudo)."

# A binary-only re-spin needs an already-built chroot to reuse.
if [ "$STAGE" = "binary" ] && [ ! -d "$SCRIPT_DIR/chroot" ]; then
    die "--stage binary needs an existing chroot. Run '--stage all' (or '--stage chroot') first."
fi

log "Installing build prerequisites (live-build, imagemagick, curl, xorriso)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends live-build imagemagick curl xorriso ca-certificates

# The Electron app + python daemons are only needed when we (re)build the
# chroot. A binary-only re-spin reuses the existing chroot, so skip these.
if [ "$STAGE" != "binary" ]; then
    # Locate the Electron unpacked app dir if not given
    if [ -z "$APP_DIR" ]; then
        for c in \
            "$REPO_ROOT/dist/linux-unpacked" \
            "$REPO_ROOT/linux-unpacked" \
            "$HOME/hifi-build/dist/linux-unpacked" \
            /root/hifi-build/dist/linux-unpacked ; do
            [ -x "$c/hifi-media-player" ] && APP_DIR="$c" && break
        done
    fi
    [ -n "$APP_DIR" ] && [ -x "$APP_DIR/hifi-media-player" ] \
        || die "Electron app not found. Pass --app-dir /path/to/linux-unpacked (must contain ./hifi-media-player)."
    log "Using Electron app from: $APP_DIR"

    [ -f "$REPO_ROOT/api_server.py" ]      || die "Missing $REPO_ROOT/api_server.py"
    [ -f "$REPO_ROOT/vu_meter_daemon.py" ] || die "Missing $REPO_ROOT/vu_meter_daemon.py"
    [ -f "$REPO_ROOT/sources_server.py" ]  || die "Missing $REPO_ROOT/sources_server.py"
fi

# ─────────────────────────── Normalise text files ──────────────────
# Config files were authored on Windows → strip CR so chroot shebangs work.
log "Normalising line endings of config text files…"
find "$CONFIG" -type f \
    ! -path "*/includes.chroot/opt/*" \
    ! -path "*/packages.chroot/*" \
    ! -name "*.png" \
    -exec sed -i 's/\r$//' {} +

# ─────────────────────────── Inject payloads ───────────────────────
# All of these land in includes.chroot/ and are baked into the chroot during
# the CHROOT stage. For a binary-only re-spin (--stage binary) the chroot is
# reused as-is, so we SKIP these (notably the slow Lyrion download).
if [ "$STAGE" = "binary" ]; then
    log "Skipping chroot payload injection (binary-only re-spin)."
else

log "Injecting Electron app → includes.chroot/opt/hifi-media-player"
APP_DEST="$CONFIG/includes.chroot/opt/hifi-media-player"
rm -rf "$APP_DEST"; mkdir -p "$APP_DEST"
cp -a "$APP_DIR/." "$APP_DEST/"

# Seed the installed UI version (baseline for OTA update comparison). Default to
# the version in package.json unless overridden with --app-version.
if [ -z "$APP_VERSION" ] && [ -f "$REPO_ROOT/package.json" ]; then
    APP_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$REPO_ROOT/package.json" | head -n1)"
fi
[ -n "$APP_VERSION" ] || APP_VERSION="unknown"
printf '%s\n' "$APP_VERSION" > "$APP_DEST/UI_VERSION"
log "Seeded UI_VERSION = $APP_VERSION"

log "Injecting canonical kiosk X session → includes.chroot/home/hifi/.xsession"
# Single source of truth: the SAME file the OS-update OTA installs
# (distro/os-update/files/xsession) is baked into the image here, so the live
# session and the OTA can never drift (a one-byte drift used to force a reboot
# on every OS update). Ownership/exec bit are finalised by hook 0100 after the
# 'hifi' user is created.
XSESSION_SRC="$SCRIPT_DIR/os-update/files/xsession"
[ -f "$XSESSION_SRC" ] || die "Missing canonical X session at $XSESSION_SRC"
XSESSION_DEST_DIR="$CONFIG/includes.chroot/home/hifi"
mkdir -p "$XSESSION_DEST_DIR"
cp -f "$XSESSION_SRC" "$XSESSION_DEST_DIR/.xsession"
sed -i 's/\r$//' "$XSESSION_DEST_DIR/.xsession"
chmod +x "$XSESSION_DEST_DIR/.xsession"

log "Injecting python daemons → includes.chroot/usr/local/bin"
BIN_DEST="$CONFIG/includes.chroot/usr/local/bin"
mkdir -p "$BIN_DEST"
cp -f "$REPO_ROOT/api_server.py"      "$BIN_DEST/"
cp -f "$REPO_ROOT/vu_meter_daemon.py" "$BIN_DEST/"
cp -f "$REPO_ROOT/sources_server.py"  "$BIN_DEST/"
sed -i 's/\r$//' "$BIN_DEST/api_server.py" "$BIN_DEST/vu_meter_daemon.py" "$BIN_DEST/sources_server.py"
chmod +x "$BIN_DEST/api_server.py" "$BIN_DEST/vu_meter_daemon.py" "$BIN_DEST/sources_server.py"

# Seed the installed system-components version (baseline for OTA comparison),
# matching the UI version so a fresh image reports a real baseline.
SYS_VERSION_DEST="$CONFIG/includes.chroot/etc/hifi-player"
mkdir -p "$SYS_VERSION_DEST"
printf '%s\n' "$APP_VERSION" > "$SYS_VERSION_DEST/SYSTEM_VERSION"
log "Seeded SYSTEM_VERSION = $APP_VERSION"

# Seed the OS OTA baseline version (so hifi-os-* comparisons have a baseline).
printf '%s\n' "$APP_VERSION" > "$SYS_VERSION_DEST/OS_VERSION"
log "Seeded OS_VERSION = $APP_VERSION"

# Bake the OTA public key so the device can verify signed OS bundles. Without
# it, the OS updater safely refuses every update. Generate it once with
# distro/ota-keys/gen-ota-key.sh (see distro/ota-keys/README.md).
OTA_PUBKEY_SRC="$SCRIPT_DIR/ota-keys/ota-pubkey.pem"
if [ -f "$OTA_PUBKEY_SRC" ]; then
    cp -f "$OTA_PUBKEY_SRC" "$SYS_VERSION_DEST/ota-pubkey.pem"
    chmod 644 "$SYS_VERSION_DEST/ota-pubkey.pem"
    log "Baked OTA public key → /etc/hifi-player/ota-pubkey.pem"
else
    log "WARNING: $OTA_PUBKEY_SRC missing — OS OTA updates will be refused on this image."
fi

log "Lyrion Music Server will be downloaded on-demand by hook 0050 (during chroot build)"
# Not staged in includes.chroot — downloaded during the chroot build by hook 0050,
# installed, and the .deb file is removed. The installed package (dpkg metadata)
# survives the installer; hifi-firstboot.sh will re-ensure it on first boot.

log "Generating Plymouth boot logo (ImageMagick)"
THEME_DIR="$CONFIG/includes.chroot/usr/share/plymouth/themes/hifi"
mkdir -p "$THEME_DIR"
convert -size 720x200 xc:black \
    -gravity center \
    -fill '#d4af37' -font DejaVu-Sans-Bold -pointsize 72 -annotate +0-10 'HiFi Player' \
    -fill '#888888' -font DejaVu-Sans -pointsize 22 -annotate +0+55 'network audio streamer' \
    "$THEME_DIR/logo.png" \
    || convert -size 720x200 xc:black -gravity center -fill white -pointsize 60 -annotate 0 'HiFi Player' "$THEME_DIR/logo.png"

# Solid-black GRUB background for the installed system, so the (hidden) GRUB
# graphical terminal shows nothing — no menu, no "Loading Linux…" text.
# Bake it into the image here (ImageMagick is not installed on the target).
log "Generating black GRUB background → includes.chroot/boot/grub/hifi-bg.png"
GRUB_BG_DIR="$CONFIG/includes.chroot/boot/grub"
mkdir -p "$GRUB_BG_DIR"
convert -size 1920x1080 xc:black "$GRUB_BG_DIR/hifi-bg.png" 2>/dev/null \
    || die "Failed to generate GRUB background image."

fi  # end: chroot payload injection (skipped for --stage binary)

# ─────────────────────────── Installer boot splash ─────────────────
# Brand the ISO boot menu (isolinux/BIOS + grub/UEFI) with the SAME logo
# look as the Plymouth splash: gold "HiFi Player" + grey subtitle on black.
# isolinux wants a 640x480 splash.png; grub a 640x480 background too.
#
# IMPORTANT: we do NOT overwrite the menu .cfg files (they contain the
# correct kernel/initrd paths, which differ between live-build/d-i versions
# — hardcoding them caused "vmlinuz not found"). Instead we only drop our
# splash images here, and a *binary* hook (0500-brand-boot.hook.binary)
# rewrites colours/title/timeout in the live-build-generated menus in place.
log "Generating installer boot splash (same branding as Plymouth)"
BINARY="$CONFIG/includes.binary"
ISOLINUX_DIR="$BINARY/isolinux"
GRUB_DIR="$BINARY/boot/grub"
mkdir -p "$ISOLINUX_DIR" "$GRUB_DIR"

# isolinux/BIOS splash — 640x480, logo centred on black.
convert -size 640x480 xc:black \
    -gravity center \
    -fill '#d4af37' -font DejaVu-Sans-Bold -pointsize 56 -annotate +0-30 'HiFi Player' \
    -fill '#888888' -font DejaVu-Sans -pointsize 18 -annotate +0+20 'network audio streamer' \
    "$ISOLINUX_DIR/splash.png" \
    || convert -size 640x480 xc:black -gravity center -fill white -pointsize 48 -annotate 0 'HiFi Player' "$ISOLINUX_DIR/splash.png"

# grub/UEFI background — 640x480 (works on gfxterm), same look.
convert -size 640x480 xc:black \
    -gravity center \
    -fill '#d4af37' -font DejaVu-Sans-Bold -pointsize 56 -annotate +0-30 'HiFi Player' \
    -fill '#888888' -font DejaVu-Sans -pointsize 18 -annotate +0+20 'network audio streamer' \
    "$GRUB_DIR/splash.png" \
    || convert -size 640x480 xc:black -gravity center -fill white -pointsize 48 -annotate 0 'HiFi Player' "$GRUB_DIR/splash.png"

# ─────────────────────────── Make hooks executable ─────────────────
chmod +x "$CONFIG"/hooks/normal/*.hook.chroot
chmod +x "$CONFIG"/hooks/normal/*.hook.binary 2>/dev/null || true

# ─────────────────────────── live-build clean (stage-aware) ────────
cd "$SCRIPT_DIR"
log "Build stage: $STAGE"

# Clean only what the requested stage needs to rebuild. The Debian package
# cache (cache/) is preserved unless --clean-cache is given, so re-spins don't
# re-download packages.
case "$STAGE" in
    all)
        log "Cleaning chroot + binary artefacts (keeping package cache)…"
        lb clean --chroot --binary >/dev/null 2>&1 || true
        ;;
    chroot)
        log "Cleaning chroot + binary artefacts (keeping bootstrap + cache)…"
        lb clean --chroot --binary >/dev/null 2>&1 || true
        ;;
    binary)
        log "Cleaning ONLY binary artefacts (reusing existing chroot)…"
        lb clean --binary >/dev/null 2>&1 || true
        ;;
esac
if [ "$CLEAN_CACHE" -eq 1 ]; then
    log "Wiping package cache (--clean-cache)…"
    lb clean --cache >/dev/null 2>&1 || true
fi

# ─────────────────────────── live-build config ─────────────────────
# (Re)generate the live-build config for full/chroot builds. For a binary-only
# re-spin we keep the existing config/ (generated by a previous run) so we
# don't disturb the chroot we're about to reuse.
if [ "$STAGE" != "binary" ]; then
    log "Configuring live-build (suite=$DEBIAN_SUITE arch=$ARCH)…"
    # IMPORTANT: keep --debian-installer LIVE. The whole appliance (Electron
    # app, python daemons, Lyrion, helper scripts, the hifi user/services) is
    # assembled in the live filesystem (squashfs), and the install works by
    # CLONING that filesystem onto the target (preseed: live-installer/enable=
    # true). With --debian-installer=true there is NO live squashfs to clone,
    # so the target gets a plain Debian without our files → the preseed
    # late_command (hifi-finalize-install.sh) then fails with "file not found".
    #
    # The ISO still behaves as "installer only" because the binary hook
    # 0500-brand-boot.hook.binary rewrites the boot menus to a SINGLE branded
    # "Install HiFi Player" entry (no live entry is shown to the user).
    lb config \
        --distribution "$DEBIAN_SUITE" \
        --architectures "$ARCH" \
        --archive-areas "main contrib non-free non-free-firmware" \
        --debian-installer live \
        --debian-installer-gui false \
        --bootloaders "syslinux,grub-efi" \
        --bootappend-live "boot=live components quiet splash loglevel=0 vt.global_cursor_default=0 hostname=hifiplayer" \
        --bootappend-install "auto=true priority=critical preseed/file=/preseed.cfg ---" \
        --iso-application "$BRAND_NAME" \
        --iso-publisher "$BRAND_NAME" \
        --iso-volume "HIFI_PLAYER" \
        --memtest none \
        --apt-recommends false
else
    [ -d config/bootstrap ] \
        || die "--stage binary but no live-build config found. Run '--stage all' first."
    log "Reusing existing live-build config (binary-only re-spin)."
fi

# ─────────────────────────── Build (stage-aware) ───────────────────
case "$STAGE" in
    all)
        log "Building full ISO (bootstrap → chroot → binary) — 20-40 min…"
        lb build
        ;;
    chroot)
        log "Building bootstrap + chroot + binary…"
        lb bootstrap
        lb chroot
        lb binary
        ;;
    binary)
        log "Building ONLY the binary stage (fast re-spin)…"
        lb binary
        ;;
esac

ISO_SRC="$(ls -1 *.iso 2>/dev/null | head -n1 || true)"
[ -n "$ISO_SRC" ] || die "Build finished but no .iso was produced."
mv -f "$ISO_SRC" "$REPO_ROOT/$ISO_NAME"

log "DONE ✓  ISO ready at: $REPO_ROOT/$ISO_NAME"
ls -lh "$REPO_ROOT/$ISO_NAME"
