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

log()  { printf '\033[1;33m[hifi-build]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[hifi-build ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

# ─────────────────────────── Args ───────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --app-dir) APP_DIR="$2"; shift 2 ;;
        --app-version) APP_VERSION="$2"; shift 2 ;;
        --lyrion-url) LYRION_DEB_URL="$2"; shift 2 ;;
        --suite) DEBIAN_SUITE="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

# ─────────────────────────── Pre-flight ─────────────────────────────
[ "$(id -u)" -eq 0 ] || die "Please run as root (sudo)."

log "Installing build prerequisites (live-build, imagemagick, curl, xorriso)…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends live-build imagemagick curl xorriso ca-certificates

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

# ─────────────────────────── Normalise text files ──────────────────
# Config files were authored on Windows → strip CR so chroot shebangs work.
log "Normalising line endings of config text files…"
find "$CONFIG" -type f \
    ! -path "*/includes.chroot/opt/*" \
    ! -path "*/packages.chroot/*" \
    ! -name "*.png" \
    -exec sed -i 's/\r$//' {} +

# ─────────────────────────── Inject payloads ───────────────────────
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

log "Downloading Lyrion Music Server .deb → includes.chroot/opt/hifi-lyrion"
# Staged inside the chroot filesystem and installed by hook 0050 (apt-get),
# NOT in packages.chroot which current apt/live-build rejects.
LYRION_DEST="$CONFIG/includes.chroot/opt/hifi-lyrion"
rm -rf "$LYRION_DEST"; mkdir -p "$LYRION_DEST"
curl -fL --retry 3 -o "$LYRION_DEST/lyrionmusicserver.deb" "$LYRION_DEB_URL" \
    || die "Failed to download Lyrion .deb from $LYRION_DEB_URL"
# sanity-check it is really a .deb (download errors often yield HTML)
head -c2 "$LYRION_DEST/lyrionmusicserver.deb" | grep -q '!<' \
    || die "Downloaded Lyrion file is not a valid .deb (got HTML/redirect?). Check LYRION_DEB_URL."

log "Generating Plymouth boot logo (ImageMagick)"
THEME_DIR="$CONFIG/includes.chroot/usr/share/plymouth/themes/hifi"
mkdir -p "$THEME_DIR"
convert -size 720x200 xc:black \
    -gravity center \
    -fill '#d4af37' -font DejaVu-Sans-Bold -pointsize 72 -annotate +0-10 'HiFi Player' \
    -fill '#888888' -font DejaVu-Sans -pointsize 22 -annotate +0+55 'network audio streamer' \
    "$THEME_DIR/logo.png" \
    || convert -size 720x200 xc:black -gravity center -fill white -pointsize 60 -annotate 0 'HiFi Player' "$THEME_DIR/logo.png"

# ─────────────────────────── Installer boot splash ─────────────────
# Brand the ISO boot menu (isolinux/BIOS + grub/UEFI) with the SAME logo
# look as the Plymouth splash: gold "HiFi Player" + grey subtitle on black.
# isolinux wants a 640x480 splash.png; grub a 800x600+ background.
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

# grub/UEFI background — 800x600, same look.
convert -size 800x600 xc:black \
    -gravity center \
    -fill '#d4af37' -font DejaVu-Sans-Bold -pointsize 64 -annotate +0-30 'HiFi Player' \
    -fill '#888888' -font DejaVu-Sans -pointsize 22 -annotate +0+25 'network audio streamer' \
    "$GRUB_DIR/splash.png" \
    || convert -size 800x600 xc:black -gravity center -fill white -pointsize 56 -annotate 0 'HiFi Player' "$GRUB_DIR/splash.png"

# ─────────────────────────── Branded boot menus ────────────────────
# Replace live-build's stock boot menus with a single, branded "Install"
# entry on both BIOS (isolinux) and UEFI (grub) so the only thing the user
# sees is the HiFi Player splash and an automatic install.
log "Writing branded installer boot menus (isolinux + grub)"

# Debian-installer kernel/initrd live under /install.<arch>/ on the ISO.
case "$ARCH" in
    amd64) DI_DIR="install.amd" ;;
    i386)  DI_DIR="install.386" ;;
    *)     DI_DIR="install.$ARCH" ;;
esac

# isolinux (BIOS): vesamenu with our splash, one auto-install entry.
cat > "$ISOLINUX_DIR/menu.cfg" <<'EOF'
menu hshift 0
menu width 82
menu title HiFi Player
include stdmenu.cfg
include install.cfg
default install
EOF

cat > "$ISOLINUX_DIR/install.cfg" <<EOF
label install
    menu label ^Install HiFi Player
    menu default
    kernel /$DI_DIR/vmlinuz
    append vga=788 initrd=/$DI_DIR/initrd.gz auto=true priority=critical preseed/file=/preseed.cfg --- quiet
EOF

cat > "$ISOLINUX_DIR/isolinux.cfg" <<'EOF'
include menu.cfg
prompt 0
timeout 30
ui vesamenu.c32
EOF

cat > "$ISOLINUX_DIR/stdmenu.cfg" <<'EOF'
menu background splash.png
menu color title        1;37;40   #c0d4af37 #00000000 std
menu color sel          7;37;40   #ff000000 #d4af37 all
menu color unsel        37;40     #d4af37 #00000000 std
menu color hotkey       1;37;40   #ffffffff #00000000 std
menu color hotsel       1;7;37;40 #ff000000 #d4af37 all
menu color border       30;44     #00000000 #00000000 std
menu color scrollbar    30;44     #d4af37 #00000000 std
menu color tabmsg       31;40     #888888 #00000000 std
menu color timeout_msg  37;40     #888888 #00000000 std
menu color timeout      1;37;40   #d4af37 #00000000 std
menu vshift 12
menu rows 4
menu timeoutrow 14
EOF

# grub (UEFI): branded background, single auto-install entry, short timeout.
cat > "$GRUB_DIR/grub.cfg" <<EOF
if loadfont /boot/grub/font.pf2 ; then
    set gfxmode=800x600
    insmod efi_gop
    insmod efi_uga
    insmod video_bochs
    insmod video_cirrus
    insmod gfxterm
    insmod png
    terminal_output gfxterm
fi

background_image /boot/grub/splash.png
set menu_color_normal=light-gray/black
set menu_color_highlight=black/yellow
set timeout=3
set default=0

menuentry "Install HiFi Player" {
    linux  /$DI_DIR/vmlinuz vga=788 auto=true priority=critical preseed/file=/preseed.cfg --- quiet
    initrd /$DI_DIR/initrd.gz
}
EOF

# ─────────────────────────── Make hooks executable ─────────────────
chmod +x "$CONFIG"/hooks/normal/*.hook.chroot

# ─────────────────────────── live-build config ─────────────────────
cd "$SCRIPT_DIR"
log "Cleaning previous build artefacts…"
lb clean >/dev/null 2>&1 || true

log "Configuring live-build (suite=$DEBIAN_SUITE arch=$ARCH) — INSTALLER ONLY…"
# --debian-installer true  → installer-only ISO (no bootable live system).
# The installer still clones the chroot filesystem, so the appliance is
# assembled exactly as before; we just drop the "live" boot path entirely.
lb config \
    --distribution "$DEBIAN_SUITE" \
    --architectures "$ARCH" \
    --archive-areas "main contrib non-free non-free-firmware" \
    --debian-installer true \
    --debian-installer-gui false \
    --bootloaders "syslinux,grub-efi" \
    --bootappend-install "auto=true priority=critical preseed/file=/preseed.cfg ---" \
    --iso-application "$BRAND_NAME" \
    --iso-publisher "$BRAND_NAME" \
    --iso-volume "HIFI_PLAYER" \
    --memtest none \
    --apt-recommends false

# ─────────────────────────── Build ──────────────────────────────────
log "Building ISO — this can take 20-40 minutes…"
lb build

ISO_SRC="$(ls -1 *.iso 2>/dev/null | head -n1 || true)"
[ -n "$ISO_SRC" ] || die "Build finished but no .iso was produced."
mv -f "$ISO_SRC" "$REPO_ROOT/$ISO_NAME"

log "DONE ✓  ISO ready at: $REPO_ROOT/$ISO_NAME"
ls -lh "$REPO_ROOT/$ISO_NAME"
