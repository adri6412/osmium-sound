#!/bin/sh
# Osmium Sound — user add-ons on a read-only image, via systemd-sysext.
#
#   hifi-ext.sh add [--dry-run] <package>...   resolve, download, install
#   hifi-ext.sh list                           what is installed and its state
#   hifi-ext.sh remove <name>                  drop an add-on
#   hifi-ext.sh upgrade [<name>...]            rebuild against today's archive,
#                                              i.e. pull newer versions
#   hifi-ext.sh refresh                        re-resolve everything against the
#                                              image that is running now
#
# WHY THIS EXISTS. /usr is a read-only squashfs that every image update replaces
# whole, so `apt install` cannot work here: the files would vanish at the next
# update while dpkg's database (which lives on /data) would keep claiming them —
# a package manager lying to itself. So apt is used only as a RESOLVER and
# DOWNLOADER: it computes what the running image does not already provide, the
# missing .debs are unpacked into ONE system extension under /var/lib/extensions
# (that is /data: it survives updates) and systemd-sysext layers it over /usr as
# a read-only LOWER layer at boot. Downloads stay signature-checked: the Debian
# keyring and sources of the image are used as they are.
#
# Two rules are what keep image updates working, and both are enforced below:
#
#   1. an add-on may only ADD files, never cover one the image ships. Covering
#      would mean the next image's version of that file stays hidden forever —
#      the exact failure that made a writable overlay on /usr unacceptable.
#   2. the extension is pinned to the image version it was resolved against
#      (SYSEXT_LEVEL in extension-release). systemd then REFUSES a stale
#      extension at boot instead of merging something built for another system,
#      and `refresh` re-resolves the stored request against the new image and
#      rebuilds it. What is kept on disk is the request, not just the result.
#
# What this is not: apt. Maintainer scripts are never executed (the safe parts —
# ldconfig, sysusers, tmpfiles, /etc defaults — are done here), and a package
# needing a library newer than the image's is refused with the reason, which is
# the honest answer: that one arrives with the next image.
set -eu

IMAGE_VERSION_FILE=/usr/lib/osmium/IMAGE_VERSION
IMAGE_STATUS=/usr/lib/osmium/dpkg-status
OS_RELEASE=/usr/lib/os-release
EXT_DIR=/var/lib/extensions
META_DIR=/var/lib/hifi-player/ext
LOCK=/run/hifi-ext.lock
# Prefix for the "does the system already ship this file" test. Empty in
# production (real absolute paths); the tests point it at their sandbox.
SYSROOT=""
# 🚨 The REAL apt-get, by absolute path: /usr/local/bin/apt-get is the shim that
# routes installs back here, so a PATH lookup would loop forever.
APT_GET=/usr/bin/apt-get

# Test hook: same shape as the update runners. Everything the script touches is
# redirected into a sandbox, so the guardian can be exercised for real —
# including the refusals — without a Debian system underneath.
if [ -n "${HIFI_EXT_TEST_ROOT:-}" ]; then
    _R=$HIFI_EXT_TEST_ROOT
    IMAGE_VERSION_FILE="$_R/usr/lib/osmium/IMAGE_VERSION"
    IMAGE_STATUS="$_R/usr/lib/osmium/dpkg-status"
    OS_RELEASE="$_R/usr/lib/os-release"
    EXT_DIR="$_R/var/lib/extensions"
    META_DIR="$_R/var/lib/hifi-player/ext"
    LOCK="$_R/hifi-ext.lock"
    SYSROOT="$_R"
    APT_GET=apt-get          # the tests put their stub first in PATH
fi

# 🚨 Only the refresh service logs to file. hifi_log_init sends stdout and
# stderr to /var/log/hifi, which is right for something systemd runs and wrong
# for anything a person types: the first run on the appliance printed absolutely
# nothing, looked hung, and interrupting it left the lock behind — after which
# every later run refused, silently. Keying it on "is stdout a terminal" was not
# enough either: `hifi-ext.sh list` over ssh without a tty, or through a pipe,
# went silent again. So the rule is the verb, not the terminal.
if [ "${1:-}" = refresh ] && [ -r /usr/local/sbin/hifi-log.sh ]; then
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
    # shellcheck disable=SC1091
    . /usr/local/sbin/hifi-log.sh
    hifi_log_init hifi-ext
fi

log()  { printf 'I: [hifi-ext] %s\n' "$*"; }
warn() { printf 'W: [hifi-ext] %s\n' "$*" >&2; }
die()  { printf 'E: [hifi-ext] %s\n' "$*" >&2; exit 1; }

need_root() { [ -n "${HIFI_EXT_TEST_ROOT:-}" ] || [ "$(id -u)" = 0 ] || die "run as root"; }

image_version() { head -n 1 "$IMAGE_VERSION_FILE" 2>/dev/null | tr -d ' \t\r\n'; }

# Add-on names end up as a directory name and inside extension-release, so keep
# them to the same shape a Debian package name has.
sane_name() {
    case "$1" in
        ''|*[!a-z0-9.+-]*) return 1 ;;
        *) printf '%s\n' "$1" ;;
    esac
}

json_get() {  # <file> <key> — the metadata is one-line JSON, like /run/hifi-*.json
    sed -n "s/.*\"$2\":\"\([^\"]*\)\".*/\1/p" "$1" 2>/dev/null | head -n 1
}

# The lock carries the pid of its owner: a run killed outright (or a terminal
# closed mid-download) used to leave a file behind that locked the command out
# for good, with no way to tell a live run from a dead one.
lock() {
    if [ -f "$LOCK" ]; then
        _owner=$(head -n 1 "$LOCK" 2>/dev/null | tr -dc '0-9')
        if [ -n "$_owner" ] && kill -0 "$_owner" 2>/dev/null; then
            die "another hifi-ext run is in progress (pid $_owner)"
        fi
        warn "stale lock from pid ${_owner:-?} — taking over"
        rm -f "$LOCK"
    fi
    echo $$ > "$LOCK"
    trap 'rm -f "$LOCK"' EXIT INT TERM
}

require_image() {
    [ -f "$IMAGE_VERSION_FILE" ] \
        || die "this is not an image system: install packages with apt as usual"
    command -v systemd-sysext >/dev/null 2>&1 || die "systemd-sysext is missing"
    [ -r "$IMAGE_STATUS" ] \
        || die "$IMAGE_STATUS is missing: this image is older than the add-on support"
}

# ── resolving: apt tells us what the image does NOT already provide ──────────
# The package database it reads is the IMAGE's own (/usr/lib/osmium/dpkg-status,
# written at build time), never the one under /var: that one lives on /data and
# still describes the first image ever installed here, so resolving against it
# would download half the system.
apt_resolve() {  # <workdir> <package>... -> .debs in <workdir>/cache/archives
    _w=$1; shift
    mkdir -p "$_w/state/lists/partial" "$_w/cache/archives/partial"
    cp "$IMAGE_STATUS" "$_w/state/status"
    # /data has to hold the downloads and then the unpacked tree: refuse early
    # rather than fill the partition the appliance stores its music library on.
    mkdir -p "$META_DIR"
    _free=$(df -Pm "$META_DIR" | awk 'NR==2{print $4}')
    [ "${_free:-0}" -ge 512 ] || die "only ${_free:-0} MiB free on the data partition: free some space first"
    _opts="-o Dir::State=$_w/state -o Dir::State::status=$_w/state/status"
    _opts="$_opts -o Dir::Cache=$_w/cache -o Dir::Cache::archives=$_w/cache/archives"
    _opts="$_opts -o APT::Install-Recommends=false -o APT::Get::Assume-Yes=true -o Acquire::Retries=3"
    # shellcheck disable=SC2086  # $_opts is a deliberate word list, no spaces in the paths
    "$APT_GET" -qq $_opts update >>"$_w/apt.log" 2>&1 \
        || die "package lists could not be refreshed (no network?) — see $_w/apt.log"
    # shellcheck disable=SC2086
    "$APT_GET" -qq $_opts install --download-only "$@" >>"$_w/apt.log" 2>&1 \
        || die "cannot be installed on this image: $(sed -n 's/^E: //p' "$_w/apt.log" | head -n 3 | tr '\n' ' ')"
    # a .deb given by path is used by apt where it lies, not copied into the
    # archive: bring it along or the add-on would miss the very package asked for
    for _a in "$@"; do
        case "$_a" in *.deb) [ -f "$_a" ] && cp -f "$_a" "$_w/cache/archives/" ;; esac
    done
}

# ── the guardian: an add-on may only ADD ────────────────────────────────────
# Rule 1 lives here. A file that already exists is refused rather than layered
# on top of, because sysext would let it win over the image's own copy and the
# next update would silently keep serving the old one. Paths outside /usr and
# /opt are handled separately (see place_side_files): sysext merges only those.
check_deb() {  # <deb> <extension name> <workdir>
    _deb=$1; _self=$2; _cw=$3
    _bad_path=""; _shadow=""
    for _p in $(dpkg-deb -c "$_deb" | awk '$1 !~ /^d/ {print $6}' | sed 's|^\./||'); do
        case "$_p" in
            usr/*|opt/*|etc/*|var/*) ;;
            *) _bad_path="$_bad_path $_p"; continue ;;
        esac
        case "$_p" in usr/*|opt/*) ;; *) continue ;; esac
        # already provided by the image (or by another add-on): refuse
        if [ -e "$SYSROOT/$_p" ] && [ ! -e "$EXT_DIR/$_self/$_p" ]; then
            _shadow="$_shadow $_p"
        fi
    done
    [ -z "$_bad_path" ] || die "$(basename "$_deb") writes outside /usr, /opt, /etc and /var:$_bad_path"
    [ -z "$_shadow" ] || die "$(basename "$_deb") would cover files the system already ships, which would freeze them at this version:$_shadow"
    # Gli script di manutenzione si conservano: servono dopo, quando i file
    # sono al loro posto (vedi run_maintscripts). Uno per pacchetto.
    _pkg=$(dpkg-deb -f "$_deb" Package 2>/dev/null || basename "$_deb")
    if dpkg-deb -e "$_deb" "$_cw/ctl/$_pkg" 2>/dev/null; then
        for _s in preinst postinst prerm postrm; do
            [ -f "$_cw/ctl/$_pkg/$_s" ] && log "  $_pkg ships a $_s: it will run once the files are in place"
        done
    fi
}

# ── script di manutenzione ──────────────────────────────────────────────────
# 🚨 Prima non venivano eseguiti affatto, e per un pacchetto qualsiasi va bene:
# le librerie le sistema ldconfig, utenti e cartelle li fanno sysusers/tmpfiles.
# Ma un postinst fa anche cose che nient'altro fa — registra la shell in
# /etc/shells, abilita un'unità systemd, sceglie un'alternativa, genera una
# configurazione da modello — e senza quelle il pacchetto è installato ma non
# funziona, in modi che l'utente scopre più tardi.
#
# Quindi si eseguono, con tre accortezze: DOPO il montaggio dell'estensione
# (altrimenti lo script non trova i file di cui parla), in modo NON fatale (un
# fallimento è un avviso, non fa saltare l'add-on: /usr è in sola lettura e
# qualche script prova a scriverci), e con l'ambiente che dpkg garantisce.
run_maintscripts() {  # <cartella script> <fase: install|configure|remove>
    _sd=$1; _phase=$2
    [ -d "$_sd" ] || return 0
    for _pd in "$_sd"/*; do
        [ -d "$_pd" ] || continue
        _pkg=$(basename "$_pd")
        case "$_phase" in
            install)   _scripts="preinst" ;;
            configure) _scripts="postinst" ;;
            remove)    _scripts="prerm postrm" ;;
            *) return 0 ;;
        esac
        for _s in $_scripts; do
            [ -f "$_pd/$_s" ] || continue
            chmod +x "$_pd/$_s" 2>/dev/null || true
            _arg=$_phase
            [ "$_s" = postinst ] && _arg=configure
            [ "$_s" = preinst ] && _arg=install
            [ "$_s" = prerm ] || [ "$_s" = postrm ] && _arg=remove
            if DEBIAN_FRONTEND=noninteractive DPKG_MAINTSCRIPT_PACKAGE="$_pkg" \
               DPKG_MAINTSCRIPT_NAME="$_s" DPKG_MAINTSCRIPT_ARCH=amd64 \
               PATH=/usr/sbin:/usr/bin:/sbin:/bin \
               "$_pd/$_s" "$_arg" >>"${LOGF:-/dev/null}" 2>&1; then
                log "  $_pkg: $_s $_arg ran"
            else
                warn "$_pkg: $_s $_arg failed — the add-on stays installed, but something that script was meant to set up may be missing"
            fi
        done
    done
}

# Files a .deb puts outside /usr and /opt: sysext does not merge those, and /etc
# and /var are persistent here anyway. They are copied in without overwriting
# anything the owner may have edited.
place_side_files() {  # <extension dir>
    _e=$1
    for _d in etc var; do
        [ -d "$_e/$_d" ] || continue
        mkdir -p "$SYSROOT/$_d"
        cp -a -n "$_e/$_d/." "$SYSROOT/$_d/" 2>/dev/null || true
        rm -rf "${_e:?}/$_d"
    done
}

write_release() {  # <extension dir> <name>
    _e=$1; _n=$2
    mkdir -p "$_e/usr/lib/extension-release.d"
    {
        # ID must match the running system; SYSEXT_LEVEL carries OUR image
        # version, which is what makes systemd drop the extension after an
        # update instead of merging something resolved for another image.
        sed -n 's/^ID=/ID=/p' "$OS_RELEASE" | head -n 1
        printf 'SYSEXT_LEVEL=%s\n' "$(image_version)"
        printf 'SYSEXT_SCOPE=system\n'
    } > "$_e/usr/lib/extension-release.d/extension-release.$_n"
}

apply_now() {
    ldconfig 2>/dev/null || true
    systemd-sysext refresh >/dev/null 2>&1 || warn "systemd-sysext refresh failed"
    systemctl daemon-reload >/dev/null 2>&1 || true
    # sysusers/tmpfiles the add-on may ship: the safe half of a postinst
    systemd-sysusers >/dev/null 2>&1 || true
    systemd-tmpfiles --create >/dev/null 2>&1 || true
}

# ── build one extension from a request ──────────────────────────────────────
build_ext() {  # <name> <dry-run 0|1> <package>...
    _name=$1; _dry=$2; shift 2
    _w=$META_DIR/.work/$_name
    rm -rf "$_w"; mkdir -p "$_w"
    log "resolving $* against image $(image_version)"
    apt_resolve "$_w" "$@"
    _debs=$(find "$_w/cache/archives" -maxdepth 1 -name '*.deb' | sort)
    if [ -z "$_debs" ]; then
        rm -rf "$_w"
        log "nothing to do: the system already provides $*"
        return 2
    fi
    log "to add: $(printf '%s\n' "$_debs" | wc -l) package(s)"
    for _d in $_debs; do
        log "  $(dpkg-deb -f "$_d" Package) $(dpkg-deb -f "$_d" Version)"
    done
    for _d in $_debs; do check_deb "$_d" "$_name" "$_w"; done
    if [ "$_dry" = 1 ]; then
        rm -rf "$_w"
        log "dry run: nothing installed"
        return 0
    fi
    # 🚨 Se l'estensione è già montata, il suo albero è un lowerdir vivo di
    # overlayfs: sostituirglielo sotto i piedi è comportamento indefinito.
    # Si smonta prima, si ricostruisce, e apply_now rimonta.
    if [ -d "$EXT_DIR/$_name" ]; then
        systemd-sysext unmerge >/dev/null 2>&1 || true
    fi
    _new="$_w/root"
    mkdir -p "$_new"
    for _d in $_debs; do
        dpkg-deb -x "$_d" "$_new" || die "could not unpack $(basename "$_d")"
    done
    # preinst prima che i file siano visibili, come fa dpkg
    run_maintscripts "$_w/ctl" install
    place_side_files "$_new"
    write_release "$_new" "$_name"
    rm -rf "${EXT_DIR:?}/$_name"
    mkdir -p "$EXT_DIR"
    mv "$_new" "$EXT_DIR/$_name"
    mkdir -p "$META_DIR/$_name"
    printf '{"name":"%s","packages":"%s","image":"%s","updated":"%s"}\n' \
        "$_name" "$*" "$(image_version)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        > "$META_DIR/$_name/request.json"
    # the downloaded .debs stay: after an image update most of them are still
    # the right ones and the rebuild needs no network
    mkdir -p "$META_DIR/$_name/debs"
    cp -f "$_w"/cache/archives/*.deb "$META_DIR/$_name/debs/" 2>/dev/null || true
    # gli script restano accanto all'add-on: servono alla rimozione e a ogni
    # ricostruzione (dopo un aggiornamento dell'immagine vanno rieseguiti)
    rm -rf "$META_DIR/$_name/scripts"
    if [ -d "$_w/ctl" ]; then
        cp -a "$_w/ctl" "$META_DIR/$_name/scripts" 2>/dev/null || true
    fi
    rm -rf "$_w"
    return 0
}

# Montare e poi far girare i postinst: i file devono essere al loro posto prima
# che uno script vada a cercarli.
apply_and_configure() {  # <nome add-on>
    apply_now
    run_maintscripts "$META_DIR/$1/scripts" configure
    # un postinst può aver messo un'unità: ricaricare e basta, non si avvia
    # niente di propria iniziativa
    systemctl daemon-reload >/dev/null 2>&1 || true
}

cmd_add() {
    need_root; require_image; lock
    _dry=0
    [ "${1:-}" = "--dry-run" ] && { _dry=1; shift; }
    [ $# -gt 0 ] || die "usage: $0 add [--dry-run] <package>..."
    _name=$(sane_name "$1") || die "invalid add-on name: $1"
    rc=0
    build_ext "$_name" "$_dry" "$@" || rc=$?
    [ "$rc" = 2 ] && return 0
    [ "$_dry" = 1 ] && return 0
    apply_and_configure "$_name"
    log "add-on '$_name' installed and active"
}

# Takes an add-on name or, because that is what `apt remove` passes, the name of
# a package inside one. Removing one package out of several rebuilds the add-on
# from the remaining request — which is possible only because the request is
# what gets stored, not just the result.
cmd_remove() {
    need_root; lock
    _name=$(sane_name "${1:-}") || die "usage: $0 remove <name>"
    if [ ! -d "$META_DIR/$_name" ] && [ ! -d "$EXT_DIR/$_name" ]; then
        for _m in "$META_DIR"/*/request.json; do
            [ -f "$_m" ] || continue
            _p=$(json_get "$_m" packages)
            for _one in $_p; do
                [ "$_one" = "$_name" ] || continue
                _owner=$(json_get "$_m" name)
                # shellcheck disable=SC2086  # the split is what turns the list into lines
                _rest=$(printf '%s\n' $_p | grep -vx "$_name" | tr '\n' ' ')
                if [ -z "$(printf '%s' "$_rest" | tr -d ' ')" ]; then
                    _name=$_owner
                else
                    log "'$_name' is part of add-on '$_owner': rebuilding it without that package"
                    # shellcheck disable=SC2086
                    build_ext "$_owner" 0 $_rest && apply_now
                    log "add-on '$_owner' rebuilt without '$_name'"
                    return 0
                fi
                break
            done
        done
    fi
    [ -d "$EXT_DIR/$_name" ] || [ -d "$META_DIR/$_name" ] || die "no add-on or add-on package named '$_name'"
    run_maintscripts "$META_DIR/$_name/scripts" remove
    rm -rf "${EXT_DIR:?}/$_name" "${META_DIR:?}/$_name"
    apply_now
    log "add-on '$_name' removed (its files under /etc and /var are left alone)"
}

cmd_list() {
    _cur=$(image_version)
    [ -d "$META_DIR" ] || { echo "no add-ons installed"; return 0; }
    for _m in "$META_DIR"/*/request.json; do
        [ -f "$_m" ] || continue
        _n=$(json_get "$_m" name); _p=$(json_get "$_m" packages); _i=$(json_get "$_m" image)
        if [ ! -d "$EXT_DIR/$_n" ]; then
            _state="missing"
        elif [ "$_i" = "$_cur" ]; then
            _state="active"
        else
            _state="stale (built for $_i, waiting for a refresh)"
        fi
        printf '%-24s %-10s %s\n' "$_n" "$_state" "$_p"
    done
}

# "apt install <pacchetto>" di nuovo aggiorna quel pacchetto, perché la
# risoluzione parte sempre dall'archivio di oggi. Questo fa lo stesso per gli
# add-on già installati, senza doverne ricordare i nomi: ricostruisce ognuno
# dalla propria richiesta e si ritrova le versioni nuove. È ciò che una persona
# intende con "apt upgrade" su questo apparecchio — il sistema operativo, che
# non si aggiorna a pacchetti, resta fuori.
cmd_upgrade() {
    need_root; require_image; lock
    _any=0; _changed=0
    [ -d "$META_DIR" ] || { log "no add-ons"; return 0; }
    for _m in "$META_DIR"/*/request.json; do
        [ -f "$_m" ] || continue
        _n=$(json_get "$_m" name); _p=$(json_get "$_m" packages)
        [ -n "$_n" ] || continue
        if [ $# -gt 0 ]; then
            _want=0
            for _a in "$@"; do [ "$_a" = "$_n" ] && _want=1; done
            [ "$_want" = 1 ] || continue
        fi
        _any=1
        log "add-on '$_n': rebuilding from today's archive"
        rc=0
        # shellcheck disable=SC2086
        build_ext "$_n" 0 $_p || rc=$?
        case "$rc" in
            0) _changed=1 ;;
            2) log "add-on '$_n': the image now provides it — removed"
               rm -rf "${EXT_DIR:?}/$_n" "${META_DIR:?}/$_n"; _changed=1 ;;
            *) warn "add-on '$_n' could not be rebuilt: it stays as it was" ;;
        esac
    done
    [ "$_any" = 1 ] || log "nothing to upgrade"
    if [ "$_changed" = 1 ]; then
        apply_now
        for _m in "$META_DIR"/*/request.json; do
            [ -f "$_m" ] || continue
            run_maintscripts "$(dirname "$_m")/scripts" configure
        done
        systemctl daemon-reload >/dev/null 2>&1 || true
    fi
    return 0
}

# Called at boot by hifi-ext-refresh.service after an image update: every add-on
# whose pin no longer matches is resolved again against the image that is now
# running. What could not be rebuilt stays out — systemd refuses it anyway, so a
# failure here costs an add-on, never the boot.
cmd_refresh() {
    need_root; require_image; lock
    _cur=$(image_version); _changed=0
    [ -d "$META_DIR" ] || { log "no add-ons"; return 0; }
    for _m in "$META_DIR"/*/request.json; do
        [ -f "$_m" ] || continue
        _n=$(json_get "$_m" name); _p=$(json_get "$_m" packages); _i=$(json_get "$_m" image)
        [ -n "$_n" ] || continue
        if [ "$_i" = "$_cur" ] && [ -d "$EXT_DIR/$_n" ]; then
            continue
        fi
        log "add-on '$_n' was built for image ${_i:-?}, rebuilding for $_cur"
        rc=0
        # shellcheck disable=SC2086  # the package list is a plain word list
        build_ext "$_n" 0 $_p || rc=$?
        case "$rc" in
            0) _changed=1 ;;
            2) log "add-on '$_n': the new image already provides it — removed"
               rm -rf "${EXT_DIR:?}/$_n" "${META_DIR:?}/$_n"; _changed=1 ;;
            *) warn "add-on '$_n' could not be rebuilt: it stays disabled"
               rm -rf "${EXT_DIR:?}/$_n"
               printf '{"name":"%s","packages":"%s","image":"%s","error":"rebuild failed"}\n' \
                   "$_n" "$_p" "$_i" > "$META_DIR/$_n/request.json" ;;
        esac
    done
    if [ "$_changed" = 1 ]; then
        apply_now
        for _m in "$META_DIR"/*/request.json; do
            [ -f "$_m" ] || continue
            run_maintscripts "$(dirname "$_m")/scripts" configure
        done
        systemctl daemon-reload >/dev/null 2>&1 || true
    fi
    return 0
}

case "${1:-}" in
    add)     shift; cmd_add "$@" ;;
    upgrade) shift; cmd_upgrade "$@" ;;
    remove)  shift; cmd_remove "$@" ;;
    list)    cmd_list ;;
    refresh) cmd_refresh ;;
    *) echo "usage: $0 add [--dry-run] <package>... | list | remove <name> | upgrade [<name>...] | refresh" >&2; exit 64 ;;
esac
