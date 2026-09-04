#!/bin/bash
# Osmium Sound — chi installa Lyrion, e soprattutto chi NON deve.
#
# Il server musicale non fa parte dell'immagine (licenza) e non deve nemmeno
# comparire da solo al primo avvio: lo installa il wizard, dopo aver chiesto
# se il server lo fa questo apparecchio o se ne segue uno già in rete. Questa
# unità resta solo come rete di sicurezza. Qui si verifica ogni caso in cui
# deve stare ferma.
set -u
S="distro/config/includes.chroot/usr/local/sbin/hifi-lyrion-ensure.sh"
U="distro/config/includes.chroot/usr/local/share/hifi-ab/hifi-lyrion-ensure.service"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/usr/lib/osmium" "$T/etc/hifi-player" "$T/etc/default" "$T/lyrion/current/usr/sbin"
echo v1 > "$T/usr/lib/osmium/IMAGE_VERSION"
echo "ARGS='-o default -D -v -C 5 -s 127.0.0.1 -n OsmiumSound -M Osmium'" > "$T/etc/default/squeezelite"
printf 'boot=live components quiet\n' > "$T/cmdline-live"
printf 'rauc.slot=A ro quiet\n'       > "$T/cmdline-installed"
cat > "$T/fake-update" <<'FAKE'
#!/bin/sh
echo "$@" > "$HIFI_TEST_MARK"
FAKE
chmod +x "$T/fake-update"

run() {  # <cmdline file>  -> "installed" | "skipped"
    rm -f "$T/mark"
    HIFI_IMAGE_VERSION_FILE="$T/usr/lib/osmium/IMAGE_VERSION" \
    HIFI_LYRION_CURRENT="$T/lyrion/current" \
    HIFI_CMDLINE="$1" \
    HIFI_CONFIG_DIR="$T/etc/hifi-player" \
    HIFI_SQ_DEFAULT="$T/etc/default/squeezelite" \
    HIFI_LYRION_UPDATE="$T/fake-update" \
    HIFI_TEST_MARK="$T/mark" \
        sh "$S" >/dev/null 2>&1
    [ -f "$T/mark" ] && echo installed || echo skipped
}
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: atteso $3, ottenuto $2"; fi; }

[ -f "$S" ] || { echo "manca $S"; exit 1; }

# ── configurazione ancora da fare: tocca al wizard ───────────────────
: > "$T/etc/hifi-player/provisioning-pending"
expect "durante la configurazione non scarica niente" "$(run "$T/cmdline-installed")" skipped
# ...ed è lo stesso caso di un apparecchio appena installato dalla ISO.

# ── sessione live: niente da conservare, niente da scaricare ─────────
expect "in sessione live sta fermo (config da fare)" "$(run "$T/cmdline-live")" skipped
rm -f "$T/etc/hifi-player/provisioning-pending"
expect "in sessione live sta fermo comunque"         "$(run "$T/cmdline-live")" skipped

# ── configurato, modalità locale, server mancante: rete di sicurezza ─
expect "apparecchio configurato senza server: lo installa" "$(run "$T/cmdline-installed")" installed

# ── segue il server di un'altra stanza: non gliene serve uno ─────────
echo "ARGS='-o default -v -s 192.168.0.50 -n OsmiumSound'" > "$T/etc/default/squeezelite"
expect "in modalità segui non scarica niente" "$(run "$T/cmdline-installed")" skipped
echo "ARGS='-o default -v -s 127.0.0.1 -n OsmiumSound'" > "$T/etc/default/squeezelite"

# ── già installato: no-op ────────────────────────────────────────────
touch "$T/lyrion/current/usr/sbin/squeezeboxserver"; chmod +x "$T/lyrion/current/usr/sbin/squeezeboxserver"
expect "se il server c'è già non fa niente" "$(run "$T/cmdline-installed")" skipped
rm -f "$T/lyrion/current/usr/sbin/squeezeboxserver"

# ── fuori dagli slot immagine non è affar suo ────────────────────────
rm -f "$T/usr/lib/osmium/IMAGE_VERSION"
expect "su un sistema legacy non interviene" "$(run "$T/cmdline-installed")" skipped
echo v1 > "$T/usr/lib/osmium/IMAGE_VERSION"

# ── la versione scaricata è quella dichiarata ────────────────────────
run "$T/cmdline-installed" >/dev/null
if grep -q "lyrionmusicserver_9.1.0_all.deb 9.1.0" "$T/mark" 2>/dev/null; then ok; else
   bad "l'URL o la versione passata all'aggiornatore non corrispondono: $(cat "$T/mark" 2>/dev/null)"; fi

# ── le stesse condizioni devono stare anche nell'unità ───────────────
if grep -q 'ConditionKernelCommandLine=!boot=live' "$U"; then ok; else
   bad "l'unità non salta le sessioni live"; fi
if grep -q 'ConditionPathExists=!/etc/hifi-player/provisioning-pending' "$U"; then ok; else
   bad "l'unità non aspetta la fine della configurazione"; fi

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
