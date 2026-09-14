# shellcheck shell=sh
# 0060 — Collapse the duplicated squeezelite -m flags left by 0042.
#
# 0042 assigns the persistent player MAC by PREPENDING "-m <mac>" to ARGS, so
# the flag ends up right after the opening quote: ARGS='-m 02:.. -o ..'. Its
# "already assigned, skip" guard used to be (^|[[:space:]])-m[[:space:]], which
# a quote does not satisfy — so the guard never fired on its own output. Since
# apply.sh re-runs every migration on every OS update, each update prepended
# another copy of the very same MAC:
#
#   ARGS='-m 02:43:eb:f5:0f:4e -m 02:43:eb:f5:0f:4e -o hw:CARD=DAC,DEV=0 -D ...'
#
# (reported by an owner reading their own /etc/default/squeezelite). Harmless
# to playback — every copy carries the identical machine-id-derived MAC, and
# squeezelite's option loop simply assigns the same value again — but the line
# grew by one flag per update and made the config unreadable. 0042 now uses a
# guard that accepts the quote, which stops the growth; this migration removes
# the copies already accumulated.
#
# Deliberately conservative: it collapses the run ONLY when every -m in ARGS
# carries the same value, which is always the case for this bug (both writers,
# hifi-disk-install.sh and 0042, derive the MAC from the same /etc/machine-id).
# If the values ever differ, the playerid actually in use depends on
# squeezelite's own last-one-wins parsing, and LMS keys a player's saved
# settings and playback history off that id — so the file is left untouched and
# the situation is only logged, never guessed at.
#
# Unlike 0042 this does NOT restart squeezelite: dropping repeats of a flag that
# already carried the identical value leaves the effective arguments unchanged,
# so the running player is already correct and a restart would only cost every
# unit in the fleet a needless gap in playback during the update.

SQ_DEFAULT=/etc/default/squeezelite

if [ -f "$SQ_DEFAULT" ] && grep -q '^ARGS=' "$SQ_DEFAULT" 2>/dev/null; then
    _args="$(sed -n "s/^ARGS=\(['\"]\)\(.*\)\1\$/\2/p" "$SQ_DEFAULT" | head -n 1)"

    # awk prints "OK <deduped args>", "SKIP" (0 or 1 -m) or "DIFFER" (conflict).
    _res="$(printf '%s\n' "$_args" | awk '
        {
            n = 0; rest = ""
            for (i = 1; i <= NF; i++) {
                if ($i == "-m" && i < NF) { n++; mac[n] = $(i + 1); i++; continue }
                rest = (rest == "" ? $i : rest " " $i)
            }
            if (n < 2) { print "SKIP"; exit }
            for (j = 2; j <= n; j++) if (mac[j] != mac[1]) { print "DIFFER"; exit }
            print "OK -m " mac[1] (rest == "" ? "" : " " rest)
        }')"

    case "$_res" in
        OK\ *)
            _new="${_res#OK }"
            _bak="$SQ_DEFAULT.hifi-bak.$$"
            cp -a "$SQ_DEFAULT" "$_bak"
            # Rewrite the ARGS= line with awk rather than sed: the value carries
            # ':' ',' and '=' from the -o device name, none of which need
            # escaping when passed as an awk variable.
            _tmp="$SQ_DEFAULT.hifi-new.$$"
            if awk -v newargs="$_new" '
                    /^ARGS=/ && !done { printf "ARGS=\047%s\047\n", newargs; done = 1; next }
                    { print }
                ' "$SQ_DEFAULT" > "$_tmp" 2>/dev/null \
               && grep -q '^ARGS=' "$_tmp"; then
                # cat, not mv: keeps the original inode, owner and mode.
                cat "$_tmp" > "$SQ_DEFAULT"
                rm -f "$_tmp" "$_bak"
                mark_changed "removed duplicate squeezelite -m flags from ARGS"
            else
                rm -f "$_tmp"
                mv -f "$_bak" "$SQ_DEFAULT"
                log_warn "failed to rewrite $SQ_DEFAULT ARGS, left untouched"
            fi
            ;;
        DIFFER)
            log_warn "$SQ_DEFAULT ARGS carries several different -m values, left untouched"
            ;;
    esac
fi
