#!/bin/sh
# Osmium Sound — aggiornamento IMMAGINE (schema A/B con RAUC).
#
#   hifi-image-update.sh stage <url|file> <versione>
#       installa il bundle nello slot inattivo con `rauc install` (in streaming
#       se è un URL: RAUC scarica solo i blocchi che scrive, niente file locale),
#       sulla root legacy appena convertita semina prima /data e dopo scrive il
#       selettore sulla ESP. Il sistema in uso non cambia: è il riavvio a far
#       partire il nuovo slot (la fase "apply" del sequencer è vuota).
#   hifi-image-update.sh apply <staged_dir> <versione>
#       no-op (compatibilità col sequencer a due fasi).
set -eu

CMD="${1:-}"
STATUS=/run/hifi-image-status.json
STAGE_ROOT=/var/lib/hifi-player/update/staged/image
VERSION=unknown
if [ -r /usr/local/sbin/hifi-log.sh ]; then
    # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-log.sh
    # shellcheck disable=SC1091
    . /usr/local/sbin/hifi-log.sh
    hifi_log_init hifi-image-update
fi

# write_status <state> <progress> <message-en> [key] [params-json]
# Il testo è inglese e serve da ripiego/log; `key` + `params` sono la chiave
# di hifi_i18n.py che l'API traduce nella lingua di chi interroga
# /update/status (kiosk, web admin), così i messaggi escono in en+it.
write_status() {
    state="$1"; progress="$2"; msg="$3"; key="${4:-}"; params="${5:-}"
    [ -n "$params" ] || params='{}'
    esc=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '{"state":"%s","progress":%s,"version":"%s","message":"%s","key":"%s","params":%s}\n' \
        "$state" "$progress" "$VERSION" "$esc" "$key" "$params" > "$STATUS"
}
fail() {  # <message-en> [key] [params-json]
    write_status error 0 "$1" "${2:-}" "${3:-}"
    echo "E: [hifi-image] $1" >&2
    exit 1
}

case "$CMD" in
stage)
    SRC="${2:-}"
    VERSION="${3:-unknown}"
    [ -n "$SRC" ] || fail "Bundle URL or file missing" update.image.badSource
    case "$VERSION" in ''|*[!0-9A-Za-z._-]*) fail "Invalid version" ;; esac
    case "$SRC" in
        https://*) modprobe nbd 2>/dev/null || true ;;
        http://*)  modprobe nbd 2>/dev/null || true ;;
        /*) [ -f "$SRC" ] || fail "Bundle not found: $SRC" update.image.badSource ;;
        *) fail "Invalid source: $SRC" update.image.badSource ;;
    esac
    [ -f /etc/rauc/system.conf ] || fail "RAUC is not configured: device not yet converted to the A/B layout" update.image.notConverted
    legacy=0
    [ -f /usr/lib/osmium/IMAGE_VERSION ] || legacy=1

    WORKDIR="$STAGE_ROOT/$VERSION"
    rm -rf "$WORKDIR"; mkdir -p "$WORKDIR"

    if [ "$legacy" = 1 ]; then
        write_status applying 5 "Copying your settings to the data partition…" update.image.seed
        /usr/local/sbin/hifi-ab-seed.sh || fail "Copying the settings to the data partition failed" update.image.seedFailed
    fi

    VJ="{\"version\":\"$VERSION\"}"
    write_status downloading 10 "Installing system image $VERSION into the standby slot…" update.image.install "$VJ"
    rcfile="$WORKDIR/rauc.rc"
    { rauc install "$SRC" 2>&1; echo "$?" > "$rcfile"; } | while IFS= read -r line; do
        printf '%s\n' "$line"
        case "$line" in
            *%*)
                pct=$(printf '%s' "$line" | sed -n 's/^[[:space:]]*\([0-9]\{1,3\}\)%.*/\1/p')
                [ -n "$pct" ] && write_status downloading $(( 10 + pct * 80 / 100 )) "Writing system image $VERSION… ${pct}%" \
                    update.image.write "{\"version\":\"$VERSION\",\"pct\":$pct}"
                ;;
        esac
    done
    rc=$(cat "$rcfile" 2>/dev/null || echo 1)
    case "$rc" in ''|*[!0-9]*) rc=1 ;; esac
    [ "$rc" = 0 ] || fail "rauc install failed (rc=$rc): see /var/log/hifi/hifi-image-update.log" update.image.installFailed "{\"rc\":$rc}"

    if [ "$legacy" = 1 ]; then
        write_status applying 92 "Enabling the A/B boot selector…" update.image.selector
        /usr/local/sbin/hifi-ab-convert.sh select || fail "Writing the A/B boot selector to the ESP failed" update.image.selectorFailed
        /usr/local/sbin/hifi-ab-seed.sh >/dev/null 2>&1 || true
        # shellcheck source=distro/config/includes.chroot/usr/local/sbin/hifi-ab-lib.sh
        # shellcheck disable=SC1091
        . /usr/local/sbin/hifi-ab-lib.sh
        ab_mount_esp 2>/dev/null || true
        ab_state_set installed
    fi
    printf '%s\n' "$VERSION" > "$WORKDIR/STAGED"
    write_status staged 100 "System image $VERSION installed: the new system starts at the next restart" update.image.staged "$VJ"
    ;;
apply)
    # Niente da fare: RAUC ha già scritto lo slot e impostato il primario; il
    # sequencer riavvia e il selettore GRUB fa il resto.
    VERSION="${3:-unknown}"
    write_status 'done' 100 "System image $VERSION ready" update.image.ready "{\"version\":\"$VERSION\"}"
    ;;
*)
    echo "Uso: $0 stage <url|file> <versione> | apply <staged_dir> <versione>" >&2
    exit 64
    ;;
esac
