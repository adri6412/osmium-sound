# shellcheck shell=sh
# 0059 — Declare the model name "Osmium" to Lyrion (squeezelite -M).
#
# squeezelite tells the server two separate things about what it is: the
# machine-readable Model=squeezelite (hardcoded in the binary, untouched by
# any option) and the human-readable ModelName=, which defaults to the
# generic "SqueezeLite". ModelName= is what Lyrion prints under Settings >
# Player > Information and in its logs, so until now every Osmium unit
# showed up there as an anonymous SqueezeLite — indistinguishable from any
# other squeezelite (or third-party bridge) on the same LAN when reading a
# support log or a multiroom player list.
#
# -M Osmium fixes that. It is cosmetic/diagnostic only: no audio path, no
# playerid (that is -m, see 0042), and Model=squeezelite still goes out
# unchanged, so plugins and skins that key off the machine-readable field
# behave exactly as before.
#
# Just "Osmium": the product, not the full "Osmium Sound" wordmark and not
# the per-device name an owner sets with -n (api_server.py set_player_name
# rewrites only -n). It is also the string Material Skin keys its player
# icon off — playerIcons["squeezelite"]["Osmium"], an exact match — so it is
# a name other software is expected to hardcode, and it should stay short
# and stable.
#
# Two cases, because an earlier revision of this migration declared
# "OsmiumSound" before any release carried it: ARGS with no -M at all gets
# one appended, and ARGS carrying exactly our own old "-M OsmiumSound" is
# corrected in place. Any other -M is left alone — that is an owner's own
# choice and is never overwritten. Guarded on the installed binary actually
# knowing -M: squeezelite exits on an unknown option and systemd's
# Restart=always would then loop it forever, i.e. a silent appliance. Only
# restarts when ARGS really changed and the service is running (brief audio
# interruption, same tradeoff as 0042).

SQ_DEFAULT=/etc/default/squeezelite
SQ_MODEL=Osmium

_sq_has_model() {
    # The opening quote counts as a word boundary: -M can be the first flag
    # in ARGS='...'. See 0042 for the duplicate-flag bug the naive form caused.
    grep '^ARGS=' "$SQ_DEFAULT" | grep -qE "(^ARGS=['\"]|[[:space:]])-M[[:space:]]"
}

_sq_apply() {  # $1 = sed expression, $2 = log message
    if ! squeezelite -? 2>&1 | grep -q -- '-M <modelname>'; then
        log_warn "installed squeezelite does not support -M, model name left as default"
        return
    fi
    _bak="$SQ_DEFAULT.hifi-bak.$$"
    cp -a "$SQ_DEFAULT" "$_bak"
    sed -i "$1" "$SQ_DEFAULT"

    if grep '^ARGS=' "$SQ_DEFAULT" | grep -qF -- "-M $SQ_MODEL"; then
        rm -f "$_bak"
        mark_changed "$2"
    else
        mv -f "$_bak" "$SQ_DEFAULT"
        log_warn "failed to set -M in $SQ_DEFAULT ARGS, left untouched"
    fi
}

if [ -f "$SQ_DEFAULT" ] && grep -q '^ARGS=' "$SQ_DEFAULT" 2>/dev/null; then
    if ! _sq_has_model; then
        _sq_apply "s/^ARGS=\(['\"]\)\(.*\)\1\$/ARGS=\1\2 -M $SQ_MODEL\1/" \
                  "set squeezelite model name to $SQ_MODEL (-M)"
    elif grep '^ARGS=' "$SQ_DEFAULT" | grep -qE "(^ARGS=['\"]|[[:space:]])-M[[:space:]]+OsmiumSound([[:space:]]|['\"]|\$)"; then
        _sq_apply "s/\(-M[[:space:]]\{1,\}\)OsmiumSound/\1$SQ_MODEL/" \
                  "corrected squeezelite model name OsmiumSound -> $SQ_MODEL (-M)"
    fi
fi

if migration_changed; then
    if [ "$(systemctl is-active squeezelite.service 2>/dev/null)" = "active" ]; then
        systemctl restart squeezelite.service 2>/dev/null || true
    fi
fi
