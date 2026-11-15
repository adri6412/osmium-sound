#!/bin/sh
# Osmium Sound — developer-supplied driver packs on a read-only image.
#
#   hifi-driverpack.sh verify  <pack.osmpack>     check the Ed25519 signature only
#   hifi-driverpack.sh scan-usb                   list signed packs found on USB sticks
#   hifi-driverpack.sh install <pack.osmpack>     verify, then install firmware + modules
#   hifi-driverpack.sh list                       what is installed and its state
#   hifi-driverpack.sh remove  <name>             drop a driver pack
#   hifi-driverpack.sh refresh                    re-pin packs to the image running now
#
# WHY THIS EXISTS. The appliance ships on wildly different laptops, and some need
# a firmware blob or an out-of-tree kernel module the image does not carry — a
# per-model Wi-Fi/touch firmware we may not redistribute, or a driver we only
# learn is missing after a user reports it. There is often NO network on that
# machine (it is the Wi-Fi that is dead), so the fix has to arrive on a USB stick
# (or a web upload once any link is up) AFTER installation, and survive OTA.
#
# WHAT A DRIVER PACK IS. A `.osmpack` is a tar.gz the DEVELOPER builds and signs
# (see tools/make-driverpack.sh):
#     manifest.json                         name, description, type, target_kernel
#     firmware/...                 -> usr/lib/firmware/...
#     modules/<kver>/*.ko          -> loaded by absolute path, in manifest order
# It is distributed with two sidecars, `<pack>.osmpack.sha256` and
# `<pack>.osmpack.sha256.sig`. The signature is Ed25519 over the sha256 sidecar
# text, the SAME scheme and the SAME key as the OS updates (hifi-os-update.sh).
#
# 🚨 TRUST = SIGNATURE. Installing a kernel module is arbitrary code as root.
# The ONLY thing that makes a pack safe is that it was signed with the Osmium OTA
# key, i.e. it really came from the developer. verify() is run before anything is
# unpacked, and a pack that does not verify is refused outright. The HTTP layer
# never bypasses this — it only hands a path to this script.
#
# HOW IT LANDS. Firmware goes into a systemd-sysext extension under
# /var/lib/extensions (that is /data: it survives OTA), layered read-only over
# /usr exactly like the add-on mechanism (hifi-ext.sh). The extension is PINNED
# to the image version (SYSEXT_LEVEL); after an OTA systemd drops the stale
# extension and `refresh` re-pins it. Kernel modules cannot use depmod/modprobe
# here (/usr/lib/modules is a read-only squashfs), so each .ko is loaded by
# absolute path with insmod, in the order the manifest lists, both now and at
# every boot (hifi-driverpack-modules.service).
#
# 🚨 SECURE BOOT. Unsigned out-of-tree modules are refused by the kernel when
# UEFI Secure Boot is on (same as ipts.ko / wl.ko). Firmware is unaffected.
set -eu

PUBKEY=/etc/hifi-player/ota-pubkey.pem
IMAGE_VERSION_FILE=/usr/lib/osmium/IMAGE_VERSION
OS_RELEASE=/usr/lib/os-release
EXT_DIR=/var/lib/extensions
META_DIR=/var/lib/hifi-player/driverpack
RUN_DIR=/run/hifi-driverpack
STATUS="$RUN_DIR/status.json"
LOCK="$RUN_DIR/lock"
# Extensions this tool owns are prefixed so they never collide with hifi-ext's.
EXT_PREFIX=drv-
KVER=$(uname -r)
# Cap an uploaded/!copied pack so a garbage file cannot fill /data.
MAX_PACK_BYTES=536870912   # 512 MiB

# Test hook mirrors hifi-ext.sh: everything is redirected into a sandbox so the
# signature gate and the guardian can be exercised without a Debian system.
if [ -n "${HIFI_DRIVERPACK_TEST_ROOT:-}" ]; then
    _R=$HIFI_DRIVERPACK_TEST_ROOT
    PUBKEY="$_R/etc/hifi-player/ota-pubkey.pem"
    IMAGE_VERSION_FILE="$_R/usr/lib/osmium/IMAGE_VERSION"
    OS_RELEASE="$_R/usr/lib/os-release"
    EXT_DIR="$_R/var/lib/extensions"
    META_DIR="$_R/var/lib/hifi-player/driverpack"
    RUN_DIR="$_R/run/hifi-driverpack"
    STATUS="$RUN_DIR/status.json"
    LOCK="$RUN_DIR/lock"
    SYSROOT="$_R"
    KVER="${HIFI_DRIVERPACK_TEST_KVER:-$(uname -r)}"
else
    SYSROOT=""
fi

log()  { printf 'I: [driverpack] %s\n' "$*"; }
warn() { printf 'W: [driverpack] %s\n' "$*" >&2; }
die()  { printf 'E: [driverpack] %s\n' "$*" >&2; exit 1; }

need_root() { [ -n "${HIFI_DRIVERPACK_TEST_ROOT:-}" ] || [ "$(id -u)" = 0 ] || die "run as root"; }
image_version() { head -n 1 "$IMAGE_VERSION_FILE" 2>/dev/null | tr -d ' \t\r\n'; }

# Pack names become a directory name, an extension name and a JSON value: keep
# them to a package-name shape.
sane_name() {
    case "$1" in
        ''|*[!a-z0-9.+_-]*) return 1 ;;
        *) printf '%s\n' "$1" ;;
    esac
}

# A one-line JSON status file, the shape /run/hifi-*.json uses elsewhere so the
# web UI reads it the same way (sources_server.py FORMAT_STATUS).
# DP_SB is flipped to true by load_modules when the kernel refuses a module
# because UEFI Secure Boot is on, so the UI can tell the user to turn it off.
DP_SB=false
write_status() {  # <state> <pct> <message>
    mkdir -p "$RUN_DIR"
    printf '{"state":"%s","pct":%s,"message":"%s","secure_boot":%s,"ts":"%s"}\n' \
        "$1" "$2" "$(printf '%s' "$3" | sed 's/[\\"]/ /g')" "${DP_SB:-false}" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STATUS"
}

json_get() {  # <file> <key> — one-line JSON values only
    sed -n "s/.*\"$2\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p" "$1" 2>/dev/null | head -n 1
}

lock() {
    mkdir -p "$RUN_DIR"
    if [ -f "$LOCK" ]; then
        _owner=$(head -n 1 "$LOCK" 2>/dev/null | tr -dc '0-9')
        if [ -n "$_owner" ] && kill -0 "$_owner" 2>/dev/null; then
            die "another driverpack run is in progress (pid $_owner)"
        fi
        rm -f "$LOCK"
    fi
    echo $$ > "$LOCK"
    trap 'rm -f "$LOCK"' EXIT INT TERM
}

# ── signature gate ───────────────────────────────────────────────────────────
# Reconstruct the signed sidecar from the pack's ACTUAL sha256 and its basename,
# then check the detached Ed25519 signature against it. We never trust the
# shipped .sha256 file: we recompute. Any change to the pack changes the sha,
# changes the sidecar, and the signature no longer verifies. The distinct
# ".osmpack" filename is the domain separator from the OS bundles
# (hifi-os-*.tar.gz), so an OTA signature cannot pass as a driver pack.
verify_pack() {  # <pack.osmpack> [signed-basename] -> 0 ok, else die
    _pack=$1
    # make-driverpack signs "<sha>  <name>.osmpack" where <name> is the manifest
    # name. A pack kept for refresh is stored as pack.osmpack, so its on-disk
    # basename no longer matches the signed name — the caller passes the original
    # "<name>.osmpack" then. Default to the file's own basename otherwise.
    _signed=${2:-$(basename "$_pack")}
    [ -s "$_pack" ] || die "pack not found or empty: $_pack"
    _sig="$_pack.sha256.sig"
    [ -s "$_sig" ] || die "missing signature next to the pack: $(basename "$_sig")"
    [ -s "$PUBKEY" ] || die "OTA public key absent ($PUBKEY): cannot verify"
    command -v openssl >/dev/null 2>&1 || die "openssl missing: cannot verify the signature"
    # Same guard as the OTA updater: make sure the baked key really is Ed25519 so
    # a swapped-in weaker key cannot silently change the trust model.
    openssl pkey -pubin -in "$PUBKEY" -text -noout 2>/dev/null | grep -qi 'ED25519' \
        || die "OTA public key is not Ed25519: verification refused"

    _bytes=$(wc -c < "$_pack" | tr -d ' ')
    [ "${_bytes:-0}" -le "$MAX_PACK_BYTES" ] || die "pack is larger than the ${MAX_PACK_BYTES} byte limit"

    _sha=$(sha256sum "$_pack" | awk '{print $1}')
    _tmp=$(mktemp)
    # EXACTLY the sidecar make-driverpack.sh signs: "<sha>  <name>.osmpack\n".
    printf '%s  %s\n' "$_sha" "$_signed" > "$_tmp"
    if openssl pkeyutl -verify -pubin -inkey "$PUBKEY" \
            -rawin -in "$_tmp" -sigfile "$_sig" >/dev/null 2>&1; then
        rm -f "$_tmp"
        return 0
    fi
    rm -f "$_tmp"
    die "signature invalid: this driver pack was not signed by Osmium (rejected)"
}

# ── reading the manifest without a JSON parser ───────────────────────────────
# The manifest is small, flat JSON written by make-driverpack.sh. We only need a
# few string scalars; keep it to sed so the device needs no python/jq.
manifest_field() {  # <manifest.json> <key>
    json_get "$1" "$2"
}

# ── the guardian: only ADD, never shadow ─────────────────────────────────────
# Rule from hifi-ext.sh: an extension may only add files, never cover one the
# image ships, or the next image's copy stays hidden forever. Firmware here is
# almost always a MISSING blob, so add-only is both safe and what we want.
#
# A file the base image ALREADY ships is always a shadow — there is no self-copy
# exemption. The caller drops our own overlay before this runs (build_from_pack),
# so $SYSROOT/$_p reflects the real base image, not our merged extension. When a
# pack's firmware is FULLY covered by the image, the caller retires it before we
# get here (image_provides_all); reaching a shadow die therefore means a PARTIAL
# overlap — the pack would cover a file the image ships (possibly a newer one) —
# which is the regression we refuse.
check_tree() {  # <unpacked firmware root under usr/> <extension dir>
    _root=$1; _self=$2
    _bad=""; _shadow=""
    [ -d "$_root/usr" ] || return 0
    for _p in $(cd "$_root" && find usr -type f -o -type l | sort); do
        case "$_p" in
            usr/lib/firmware/*|usr/lib/modules/"$KVER"/updates/*) ;;
            *) _bad="$_bad $_p"; continue ;;
        esac
        if [ -e "$SYSROOT/$_p" ]; then
            _shadow="$_shadow $_p"
        fi
    done
    [ -z "$_bad" ] || die "pack writes outside usr/lib/firmware and usr/lib/modules/$KVER/updates:$_bad"
    [ -z "$_shadow" ] || die "pack would cover files the system already ships:$_shadow"
}

# ── has the base image caught up? ────────────────────────────────────────────
# True (0) when EVERY firmware file this pack carries already exists in the base
# image (usr/lib/firmware/...): the image now ships this driver and the pack has
# nothing left to add. A modules-only pack never matches — its files live under
# .../updates/osmium-driverpack, a path the image never uses — so it is never
# auto-retired. Reads only the payload LIST from the tar; the pack must have
# passed verify_pack first. 🚨 The caller MUST ensure our own extension is NOT
# merged, or the overlay would masquerade as the base image — cmd_refresh and
# cmd_install only ask after an OTA (stale extension unmerged) or before a first
# install (no overlay yet).
image_provides_all() {  # <pack.osmpack>
    _ip_files=$(tar tzf "$1" 2>/dev/null | sed -n 's#^firmware/\(.*[^/]\)$#\1#p')
    [ -n "$_ip_files" ] || return 1
    for _ip_rel in $_ip_files; do
        [ -e "$SYSROOT/usr/lib/firmware/$_ip_rel" ] || return 1
    done
    return 0
}

# Drop a pack whose firmware the image now ships: unmerge+remove the extension
# and mark it superseded so `list` can say where the driver went. Any modules
# are left to a reboot (we do not reload them); apply_sysext re-merges whatever
# extensions remain.
retire_pack() {  # <name>
    _rp_n=$1
    [ -n "${HIFI_DRIVERPACK_TEST_ROOT:-}" ] || systemd-sysext unmerge >/dev/null 2>&1 || true
    rm -rf "${EXT_DIR:?}/$EXT_PREFIX$_rp_n"
    mkdir -p "$META_DIR/$_rp_n"
    printf '{"name":"%s","state":"superseded","image":"%s","updated":"%s"}\n' \
        "$_rp_n" "$(image_version)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        > "$META_DIR/$_rp_n/state.json"
}

write_release() {  # <extension dir> <name> — identical pin scheme to hifi-ext.sh
    _e=$1; _n=$2
    mkdir -p "$_e/usr/lib/extension-release.d"
    {
        sed -n 's/^ID=/ID=/p' "$OS_RELEASE" | head -n 1
        printf 'SYSEXT_LEVEL=%s\n' "$(image_version)"
        printf 'SYSEXT_SCOPE=system\n'
        # 🚨 /usr only — merging a hierarchy with no content mounts an empty
        # tmpfs over it (this is what once hid /opt/hifi-qt). See hifi-ext.sh.
        printf 'EXTENSION_HIERARCHIES=/usr\n'
    } > "$_e/usr/lib/extension-release.d/extension-release.$_n"
}

apply_sysext() {
    [ -n "${HIFI_DRIVERPACK_TEST_ROOT:-}" ] && return 0
    ldconfig 2>/dev/null || true
    # Unmerge with the DEFAULT hierarchies first (an older add-on may have left
    # the empty /opt tmpfs), then merge /usr only. This re-merges ALL extensions
    # in EXT_DIR, ours and hifi-ext's alike.
    systemd-sysext unmerge >/dev/null 2>&1 || true
    SYSEXT_HIERARCHIES=/usr systemd-sysext merge >/dev/null 2>&1 \
        || warn "systemd-sysext merge failed"
    systemctl daemon-reload >/dev/null 2>&1 || true
}

# ── module loading (no depmod: /usr/lib/modules is read-only here) ───────────
# Each .ko is loaded by absolute path with insmod, in the order the manifest
# gives (the developer lists dependencies first). A boot unit re-runs this after
# every reboot, since nothing autoloads an out-of-tree module placed this way.
module_dir_for() {  # <extension dir> -> the updates dir holding the .ko, or empty
    printf '%s/usr/lib/modules/%s/updates/osmium-driverpack' "$1" "$KVER"
}

load_modules() {  # <extension dir> <manifest.json>
    _e=$1; _man=$2
    _md=$(module_dir_for "$_e")
    [ -d "$_md" ] || return 0
    # The manifest lists modules in load order under "modules":["a.ko","b.ko"].
    _order=$(sed -n 's/.*"modules"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' "$_man" \
                 | tr ',' '\n' | sed 's/[^A-Za-z0-9._-]//g' | grep -v '^$' || true)
    [ -n "$_order" ] || _order=$(cd "$_md" && ls -1 *.ko 2>/dev/null || true)
    _sb_warned=0
    for _ko in $_order; do
        _f="$_md/$_ko"
        [ -f "$_f" ] || { warn "module $_ko not in pack — skipped"; continue; }
        _base=${_ko%.ko}
        if [ -d "/sys/module/$(printf '%s' "$_base" | tr '-' '_')" ]; then
            log "module $_base already loaded"
            continue
        fi
        if insmod "$_f" 2>/dev/null; then
            log "loaded module $_base"
        else
            if [ "$_sb_warned" = 0 ] && grep -qs '\[integrity\]\|\[confidentiality\]' \
                    /sys/kernel/security/lockdown 2>/dev/null; then
                warn "the kernel refused $_base because UEFI Secure Boot is on;" \
                     "turn Secure Boot off in the BIOS for driver modules to load"
                _sb_warned=1
                DP_SB=true   # surfaced in the status JSON for the UI
            else
                warn "could not load module $_base (insmod failed)"
            fi
        fi
    done
}

# ── build the extension from an already-verified, unpacked pack ───────────────
build_from_pack() {  # <name> <pack.osmpack> <scratch workdir>
    _name=$1; _pack=$2; _w=$3
    _src="$_w/src"; rm -rf "$_src"; mkdir -p "$_src"
    # -I keeps tar from honouring ownership/setuid of an untrusted archive.
    tar xzf "$_pack" -C "$_src" --no-same-owner --no-same-permissions \
        || die "could not unpack the driver pack"
    _man="$_src/manifest.json"
    [ -f "$_man" ] || die "pack has no manifest.json"
    _type=$(manifest_field "$_man" type); _type=${_type:-both}
    _tgt=$(manifest_field "$_man" target_kernel)

    _tree="$_w/tree"; rm -rf "$_tree"; mkdir -p "$_tree/usr/lib"
    # firmware/ -> usr/lib/firmware/
    if [ -d "$_src/firmware" ]; then
        mkdir -p "$_tree/usr/lib/firmware"
        cp -a "$_src/firmware/." "$_tree/usr/lib/firmware/" \
            || die "could not stage firmware"
    fi
    # modules/<kver>/ -> usr/lib/modules/<kver>/updates/osmium-driverpack/
    _modules_present=0
    if [ -d "$_src/modules/$KVER" ]; then
        _md="$_tree/usr/lib/modules/$KVER/updates/osmium-driverpack"
        mkdir -p "$_md"
        cp -a "$_src/modules/$KVER/." "$_md/" || die "could not stage modules"
        _modules_present=1
    elif [ -d "$_src/modules" ] && [ -n "$_tgt" ] && [ "$_tgt" != "$KVER" ]; then
        warn "pack carries modules for kernel $_tgt but this device runs $KVER:" \
             "the firmware is installed, the modules are skipped"
    fi

    # If an earlier copy of THIS extension is still merged, its files show
    # through /usr and check_tree would mistake them for base-image shadows.
    # Drop every overlay first (apply_sysext re-merges them afterwards) so the
    # guardian — and image_provides_all callers — see the real base image only.
    if [ -d "$EXT_DIR/$EXT_PREFIX$_name" ] && [ -z "${HIFI_DRIVERPACK_TEST_ROOT:-}" ]; then
        systemd-sysext unmerge >/dev/null 2>&1 || true
    fi
    check_tree "$_tree" "$EXT_DIR/$EXT_PREFIX$_name"
    write_release "$_tree" "$EXT_PREFIX$_name"

    # Swap the extension atomically; unmerge first if it is already a live
    # overlay lowerdir (undefined behaviour to replace it in place).
    if [ -d "$EXT_DIR/$EXT_PREFIX$_name" ]; then
        [ -n "${HIFI_DRIVERPACK_TEST_ROOT:-}" ] || systemd-sysext unmerge >/dev/null 2>&1 || true
    fi
    rm -rf "${EXT_DIR:?}/$EXT_PREFIX$_name"
    mkdir -p "$EXT_DIR"
    mv "$_tree" "$EXT_DIR/$EXT_PREFIX$_name"

    # Keep the verified, SIGNED pack for refresh after an OTA (no network needed).
    mkdir -p "$META_DIR/$_name"
    cp -f "$_pack" "$META_DIR/$_name/pack.osmpack"
    cp -f "$_pack.sha256.sig" "$META_DIR/$_name/pack.osmpack.sha256.sig"
    cp -f "$_man" "$META_DIR/$_name/manifest.json"
    printf '{"name":"%s","type":"%s","target_kernel":"%s","image":"%s","modules":%s,"updated":"%s"}\n' \
        "$_name" "$_type" "${_tgt:-}" "$(image_version)" "$_modules_present" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$META_DIR/$_name/state.json"

    printf '%s' "$EXT_DIR/$EXT_PREFIX$_name"
}

# ── commands ─────────────────────────────────────────────────────────────────
cmd_verify() {
    [ $# -ge 1 ] || die "usage: $0 verify <pack.osmpack>"
    verify_pack "$1"
    log "signature OK: $(basename "$1")"
}

cmd_install() {
    need_root; lock
    [ $# -ge 1 ] || die "usage: $0 install <pack.osmpack>"
    # Any early exit (a failed verify, a bad tree, insmod errors that die) must
    # leave the UI an error status, not a stale "installing". The success path
    # sets _dp_ok=1 just before returning. This trap also drops the lock, so it
    # replaces the one lock() installed.
    _dp_ok=0
    trap '[ "$_dp_ok" = 1 ] || write_status error 100 "Installazione non riuscita."; rm -f "$LOCK"' EXIT INT TERM
    _pack=$1
    _name=$(manifest_name_of "$_pack") || _name=""
    write_status verifying 15 "Verifica firma del pacchetto driver…"
    verify_pack "$_pack"
    # The name comes from the manifest INSIDE the (now verified) pack, not from
    # the attacker-controlled filename.
    _name=$(manifest_name_of "$_pack")
    _name=$(sane_name "$_name") || die "pack manifest has no valid name"
    # If the image already ships this firmware there is nothing to overlay. Trust
    # this only for a pack not already installed — otherwise our own merged
    # extension would read back as the base image.
    if [ ! -d "$EXT_DIR/$EXT_PREFIX$_name" ] && image_provides_all "$_pack"; then
        write_status done 100 "Il driver '$_name' è già incluso nell'immagine di sistema."
        _dp_ok=1
        log "driver pack '$_name' already provided by the image — nothing to install"
        return 0
    fi
    write_status installing 55 "Installazione driver '$_name'…"
    _w=$META_DIR/.work/$_name; rm -rf "$_w"; mkdir -p "$_w"
    _ext=$(build_from_pack "$_name" "$_pack" "$_w")
    _man="$META_DIR/$_name/manifest.json"
    apply_sysext
    load_modules "$_ext" "$_man"
    rm -rf "$_w"
    write_status done 100 "Driver '$_name' installati."
    _dp_ok=1
    log "driver pack '$_name' installed and active"
}

# Pull the manifest name out of a pack without fully installing (used to label
# the run). Reads only manifest.json from the tar; does NOT imply trust.
manifest_name_of() {  # <pack.osmpack>
    tar xzf "$1" -O manifest.json 2>/dev/null \
        | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1
}

cmd_scan_usb() {
    need_root
    # Enumerate USB block partitions (same filter as sources_server.py: tran=usb),
    # mount each read-only, look for *.osmpack at the root or under osmium-drivers/,
    # report each with its signature verdict, then unmount.
    #
    # The mount is dropped at the end of the scan, so a VALID pack is first copied
    # to a staging dir on /data (not RAM — a pack can be large): install() is then
    # handed that stable path and re-verifies the signature before trusting it.
    _base="$RUN_DIR/usb"; mkdir -p "$_base"
    _stage="$META_DIR/.incoming"; rm -rf "$_stage"; mkdir -p "$_stage"
    printf '{"packs":['
    _first=1
    # lsblk gives us every partition that has a filesystem; the per-device TRAN
    # check below narrows it to USB. We must NOT ask lsblk for TRAN here: on a
    # partition TRAN is empty (it is reported on the parent disk, see below), and
    # with `-r` the empty column collapses, so NAME/TYPE/FSTYPE shift and the
    # filter would reject every stick. Keep three populated columns only.
    for _dev in $(lsblk -rno NAME,TYPE,FSTYPE 2>/dev/null \
                    | awk '$2=="part" && $3!="" {print $1}'); do
        _tran=$(lsblk -rno TRAN "/dev/$_dev" 2>/dev/null | head -n1)
        # TRAN is reported on the disk, not the partition: check the parent.
        _pk=$(lsblk -rno PKNAME "/dev/$_dev" 2>/dev/null | head -n1)
        [ -n "$_pk" ] && _tran=$(lsblk -rno TRAN "/dev/$_pk" 2>/dev/null | head -n1)
        [ "$_tran" = usb ] || continue
        _mp="$_base/$_dev"; mkdir -p "$_mp"
        mount -o ro,nosuid,nodev,noexec "/dev/$_dev" "$_mp" 2>/dev/null || { rmdir "$_mp" 2>/dev/null; continue; }
        for _pack in "$_mp"/*.osmpack "$_mp"/osmium-drivers/*.osmpack; do
            [ -f "$_pack" ] || continue
            _verdict=invalid; _staged=""
            if verify_pack "$_pack" >/dev/null 2>&1; then
                _verdict=valid
                _nm0=$(manifest_name_of "$_pack" 2>/dev/null)
                if _nm0=$(sane_name "$_nm0" 2>/dev/null); then
                    _staged="$_stage/$_nm0.osmpack"
                    cp -f "$_pack" "$_staged" 2>/dev/null \
                        && cp -f "$_pack.sha256.sig" "$_staged.sha256.sig" 2>/dev/null \
                        || _staged=""
                fi
            fi
            _nm=$(manifest_name_of "$_pack" 2>/dev/null); _nm=${_nm:-?}
            _desc=$(tar xzf "$_pack" -O manifest.json 2>/dev/null \
                      | sed -n 's/.*"description"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
            [ "$_first" = 1 ] || printf ','
            _first=0
            # "path" is the stable staged copy on /data (empty if the signature
            # did not verify — such a pack cannot be installed).
            printf '{"path":"%s","name":"%s","description":"%s","signature":"%s"}' \
                "$_staged" "$(printf '%s' "$_nm" | sed 's/[\\"]/ /g')" \
                "$(printf '%s' "$_desc" | sed 's/[\\"]/ /g')" "$_verdict"
        done
        umount "$_mp" 2>/dev/null || true
        rmdir "$_mp" 2>/dev/null || true
    done
    printf ']}\n'
}

cmd_list() {
    _cur=$(image_version)
    [ -d "$META_DIR" ] || { echo "no driver packs installed"; return 0; }
    for _s in "$META_DIR"/*/state.json; do
        [ -f "$_s" ] || continue
        _n=$(json_get "$_s" name); _i=$(json_get "$_s" image); _t=$(json_get "$_s" type)
        _tgt=$(json_get "$_s" target_kernel); _st=$(json_get "$_s" state)
        if [ "$_st" = superseded ]; then
            _state="superseded (now in image $_i)"
        elif [ ! -d "$EXT_DIR/$EXT_PREFIX$_n" ]; then
            _state="missing"
        elif [ "$_i" = "$_cur" ]; then
            _state="active"
        else
            _state="stale (built for $_i, waiting for a refresh)"
        fi
        if [ -n "$_tgt" ] && [ "$_tgt" != "$KVER" ]; then
            _state="$_state; modules for $_tgt not $KVER"
        fi
        printf '%-24s %-10s %s\n' "$_n" "$_state" "$_t"
    done
}

cmd_remove() {
    need_root; lock
    _name=$(sane_name "${1:-}") || die "usage: $0 remove <name>"
    [ -d "$EXT_DIR/$EXT_PREFIX$_name" ] || [ -d "$META_DIR/$_name" ] \
        || die "no driver pack named '$_name'"
    rm -rf "${EXT_DIR:?}/$EXT_PREFIX$_name" "${META_DIR:?}/$_name"
    apply_sysext
    log "driver pack '$_name' removed (a reboot clears any loaded modules)"
}

# Re-pin every stored pack to the image running now. Called after an OTA by
# hifi-driverpack-refresh.service, and at boot to (re)load modules. The pack is
# re-verified before it is trusted again.
cmd_refresh() {
    need_root; lock
    _cur=$(image_version); _changed=0
    [ -d "$META_DIR" ] || { log "no driver packs"; return 0; }
    for _d in "$META_DIR"/*/; do
        [ -f "$_d/pack.osmpack" ] || continue
        _n=$(basename "$_d")
        _i=$(json_get "$_d/state.json" image)
        _pack="$_d/pack.osmpack"
        # re-verify: the stored pack must still carry a valid signature. It was
        # saved as pack.osmpack, so pass the ORIGINAL signed name "<name>.osmpack".
        if ! verify_pack "$_pack" "$_n.osmpack" >/dev/null 2>&1; then
            warn "stored pack '$_n' no longer verifies — left disabled"
            rm -rf "${EXT_DIR:?}/$EXT_PREFIX$_n"
            continue
        fi
        _man="$_d/manifest.json"
        # Has the image caught up? Only ask when something changed (an OTA, or
        # the pack not currently applied): on a same-image reboot our overlay is
        # merged and /usr would reflect it, not the base. After an OTA the stale
        # extension is unmerged, so /usr is the true base image here.
        if { [ "$_i" != "$_cur" ] || [ ! -d "$EXT_DIR/$EXT_PREFIX$_n" ]; } \
             && image_provides_all "$_pack"; then
            log "driver '$_n' is now carried by the system image — retiring the pack"
            retire_pack "$_n"
            _changed=1
            continue
        fi
        if [ "$_i" != "$_cur" ] || [ ! -d "$EXT_DIR/$EXT_PREFIX$_n" ]; then
            log "re-pinning driver pack '$_n' to image $_cur"
            _w=$META_DIR/.work/$_n; rm -rf "$_w"; mkdir -p "$_w"
            rc=0
            ( build_from_pack "$_n" "$_pack" "$_w" >/dev/null ) || rc=$?
            rm -rf "$_w"
            [ "$rc" = 0 ] && _changed=1 || warn "pack '$_n' could not be re-pinned"
        fi
    done
    [ "$_changed" = 1 ] && apply_sysext
    # Always (re)load modules for the active packs — nothing autoloads them.
    for _d in "$META_DIR"/*/; do
        [ -d "$EXT_DIR/$EXT_PREFIX$(basename "$_d")" ] || continue
        load_modules "$EXT_DIR/$EXT_PREFIX$(basename "$_d")" "$_d/manifest.json"
    done
    return 0
}

case "${1:-}" in
    verify)   shift; cmd_verify "$@" ;;
    scan-usb) cmd_scan_usb ;;
    install)  shift; cmd_install "$@" ;;
    list)     cmd_list ;;
    remove)   shift; cmd_remove "$@" ;;
    refresh)  cmd_refresh ;;
    *) echo "usage: $0 verify <pack> | scan-usb | install <pack> | list | remove <name> | refresh" >&2; exit 64 ;;
esac
