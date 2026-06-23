# shellcheck shell=sh
# 0005 — Silent / hidden GRUB on already-installed devices.
#
# Fresh images get a fully hidden, silent GRUB from hifi-finalize-boot.sh at
# build time. Devices installed from an OLDER image and brought forward via OS
# updates never ran that, so their GRUB menu is still visible and shows the
# distributor title ("Osmium Sound GNU/Linux") for a few seconds at boot. The
# 0003 rebrand even sets that distributor + runs update-grub, which only makes
# the name MORE prominent. This migration applies the same hidden/silent GRUB
# settings on the running system so nothing GRUB-related is shown at boot.
#
# No reboot is requested: the regenerated grub.cfg simply takes effect at the
# next boot. Idempotent — each edit is compared before writing, so a second run
# is a clean no-op (changed=0).

GRUB_DEFS=/etc/default/grub
GRUB_10=/etc/grub.d/10_linux
_did=0

# ── 1. /etc/default/grub: hide the menu, use a graphical (blank) terminal ────
if [ -f "$GRUB_DEFS" ]; then
    _work="$(mktemp "${GRUB_DEFS}.hifi.XXXXXX")" || _work=""
    if [ -n "$_work" ]; then
        cp -a "$GRUB_DEFS" "$_work"
        # set_kv <key> <value>  — replace in-place if present, else append.
        set_kv() {
            if grep -q "^$1=" "$_work"; then
                sed -i "s|^$1=.*|$1=$2|" "$_work"
            else
                printf '%s=%s\n' "$1" "$2" >> "$_work"
            fi
        }
        set_kv GRUB_TIMEOUT 0
        set_kv GRUB_TIMEOUT_STYLE hidden
        set_kv GRUB_TERMINAL_OUTPUT '"gfxterm"'
        set_kv GRUB_RECORDFAIL_TIMEOUT 0
        if ! cmp -s "$_work" "$GRUB_DEFS"; then
            cat "$_work" > "$GRUB_DEFS"
            mark_changed "hid GRUB menu in $GRUB_DEFS"
            _did=1
        fi
        rm -f "$_work"
    fi
fi

# ── 2. /etc/grub.d/10_linux: blank the "Loading Linux/initrd…" echoes ────────
# These are the only text a hidden GRUB still emits into grub.cfg. Compare the
# transformed file to the original so we only write (and only mark changed) on
# a real diff — robust to the strings already being blank.
if [ -f "$GRUB_10" ]; then
    _w2="$(mktemp "${GRUB_10}.hifi.XXXXXX")" || _w2=""
    if [ -n "$_w2" ]; then
        sed -e 's/Loading Linux %s \.\.\./ /g' \
            -e 's/Loading Linux \.\.\./ /g' \
            -e 's/Loading initial ramdisk \.\.\./ /g' \
            "$GRUB_10" > "$_w2"
        if ! cmp -s "$_w2" "$GRUB_10"; then
            cat "$_w2" > "$GRUB_10"
            mark_changed "blanked GRUB loading messages in $GRUB_10"
            _did=1
        fi
        rm -f "$_w2"
    fi
fi

# ── 3. Regenerate grub.cfg only if we changed something ─────────────────────
if [ "$_did" = 1 ]; then
    update-grub 2>/dev/null || update-grub2 2>/dev/null || true
fi
