# shellcheck shell=sh
# 0048 — Install the Osmium LMS (Material Skin) assets under /usr/local/share.
#
# Field bug: the assets were packaged into the SYSTEM bundle from the start, but
# hifi-system-update.sh's apply only ever installed /usr/local/bin,
# /usr/local/sbin, /etc/systemd/system and /opt/hifi-webui — /usr/local/share was
# never in that list. live-build copies includes.chroot wholesale, so a device
# installed from an ISO had the files and a device updated over the air never
# did. Symptom: /etc/hifi-player/lms-skin says "osmium", the theme is missing
# from Material's picker, no custom css is served, and sources_server reported
# "Skin applied." anyway because _install_skin_theme_files returned silently when
# the asset dir was absent. Both of those are fixed at the source, but the
# system-updater fix cannot heal an existing box on the release that carries it:
# hifi-system-update.sh re-execs itself from /var/tmp and applies the bundle with
# the OLD code, so the new copy rule only takes effect one release later.
#
# This migration is the bridge. The OS payload runner executes apply.d/ FROM THE
# BUNDLE, so a new migration runs on the very first update that carries it — no
# chicken-and-egg. It also covers boxes that jump several versions at once, which
# the cumulative OS contract requires anyway.
#
# Single source of truth: files/hifi-lms-skin/ is not committed. CI copies it
# into the payload from distro/config/includes.chroot/usr/local/share/hifi-lms-skin
# (the same tree live-build bakes and the system bundle ships), so image, system
# bundle and OS bundle cannot drift — the reason 0001 does the same for xsession.
# When the copy is absent (a local payload dir, a bundle built before this step)
# the migration is a clean no-op rather than an error.

SRC="$HIFI_PAYLOAD_DIR/files/hifi-lms-skin"
DEST=/usr/local/share/hifi-lms-skin

if [ ! -d "$SRC" ]; then
    log_info "no LMS skin assets in this payload — nothing to install"
else
    # Mirror the tree file by file with ensure_file_content: it only writes (and
    # only calls mark_changed) on a real byte difference, which keeps this a
    # clean no-op on the second run as the OS contract requires. A plain `cp -a`
    # would rewrite every file every release and mark the migration as changed
    # forever.
    find "$SRC" -type f | while read -r src_file; do
        rel=${src_file#"$SRC"/}
        dest_file="$DEST/$rel"
        mkdir -p "$(dirname "$dest_file")"
        ensure_file_content "$dest_file" 644 < "$src_file"
    done
    # find|while runs in a subshell, so mark_changed's flag file is what carries
    # the result out — not a shell variable, which would be lost here.
    if migration_changed; then
        log_info "LMS skin assets installed under $DEST"
    fi
fi

# No reboot: sources_server's startup convergence thread retries on a backoff
# and picks the assets up on its own, and a skin change needs no reboot anyway.
