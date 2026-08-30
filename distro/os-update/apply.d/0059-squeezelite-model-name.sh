# shellcheck shell=sh
# 0059 — Declare the model name "OsmiumSound" to Lyrion (squeezelite -M).
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
# -M OsmiumSound fixes that. It is cosmetic/diagnostic only: no audio path,
# no playerid (that is -m, see 0042), and Model=squeezelite still goes out
# unchanged, so plugins and skins that key off the machine-readable field
# behave exactly as before.
#
# Deliberately NOT tied to the -n player name, which an owner can rename per
# device (api_server.py set_player_name rewrites only -n): the model stays
# the product, whatever the owner calls this particular unit.
#
# Idempotent: skips if ARGS already carries a -M (set here, by hand, or by a
# future release — an owner's own choice is never overwritten). Guarded on
# the installed binary actually knowing -M: squeezelite exits on an unknown
# option and systemd's Restart=always would then loop it forever, i.e. a
# silent appliance. Only restarts when ARGS really changed and the service
# is running (brief audio interruption, same tradeoff as 0042).

SQ_DEFAULT=/etc/default/squeezelite

if [ -f "$SQ_DEFAULT" ] && grep -q '^ARGS=' "$SQ_DEFAULT" \
   && ! grep '^ARGS=' "$SQ_DEFAULT" | grep -qE '(^|[[:space:]])-M[[:space:]]'; then
    if squeezelite -? 2>&1 | grep -q -- '-M <modelname>'; then
        _bak="$SQ_DEFAULT.hifi-bak.$$"
        cp -a "$SQ_DEFAULT" "$_bak"
        sed -i "s/^ARGS=\(['\"]\)\(.*\)\1\$/ARGS=\1\2 -M OsmiumSound\1/" "$SQ_DEFAULT"

        if grep '^ARGS=' "$SQ_DEFAULT" | grep -qF -- '-M OsmiumSound'; then
            rm -f "$_bak"
            mark_changed "set squeezelite model name to OsmiumSound (-M)"
        else
            mv -f "$_bak" "$SQ_DEFAULT"
            log_warn "failed to insert -M into $SQ_DEFAULT ARGS, left untouched"
        fi
    else
        log_warn "installed squeezelite does not support -M, model name left as default"
    fi
fi

if migration_changed; then
    if [ "$(systemctl is-active squeezelite.service 2>/dev/null)" = "active" ]; then
        systemctl restart squeezelite.service 2>/dev/null || true
    fi
fi
