#!/bin/bash
# Osmium Sound — la seconda occasione per passare allo schema A/B.
#
# Le pre-verifiche possono dire di no per qualcosa che il proprietario può
# sistemare: liberare spazio, o togliere la musica dal disco di sistema (è la
# richiesta esplicita di uno dei motivi di rifiuto). Il rilancio
# dell'aggiornamento invece avviene una volta sola, quindi senza un secondo
# tentativo a ogni avvio l'apparecchio resterebbe legacy fino alla prossima
# release — "ho fatto quello che mi ha chiesto e non è cambiato niente".
# Qui si verifica che quel tentativo ci sia, e che non si ripeta quando non
# serve (conversione già armata, o già convertita).
#
# Ermetico: apparecchio finto in una cartella temporanea, nessuna API.
set -u
S="distro/config/includes.chroot/usr/local/sbin/hifi-ab-image.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: atteso '$3', ottenuto '$2'"; fi; }

[ -f "$S" ] || { echo "manca $S"; exit 1; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/sbin" "$T/local" "$T/etc"

# Il convertitore finto registra le chiamate; la pre-verifica risponde secondo
# PRECHECK_RC e lascia il suo verdetto come quella vera.
cat > "$T/sbin/hifi-ab-convert.sh" <<'FAKE'
#!/bin/sh
printf 'convert %s\n' "$*" >> "$HIFI_TEST_CALLS"
exit 0
FAKE
cat > "$T/sbin/hifi-ab-precheck.sh" <<'FAKE'
#!/bin/sh
printf 'precheck\n' >> "$HIFI_TEST_CALLS"
printf '{"convertible":false,"reasons":"the music does not fit","media_needed_mib":8256}\n' \
    > "$HIFI_TEST_PRECHECK_JSON"
exit "${PRECHECK_RC:-1}"
FAKE
chmod +x "$T/sbin/hifi-ab-convert.sh" "$T/sbin/hifi-ab-precheck.sh"

run() {  # -> le chiamate fatte, su una riga
    : > "$T/calls"
    PRECHECK_RC="${1:-1}" \
    HIFI_AB_LOCAL="$T/local" \
    HIFI_AB_CONVERT="$T/sbin/hifi-ab-convert.sh" \
    HIFI_AB_PRECHECK="$T/sbin/hifi-ab-precheck.sh" \
    HIFI_AB_PRECHECK_JSON="$T/precheck.json" \
    HIFI_RAUC_CONF="$T/etc/rauc-system.conf" \
    HIFI_IMAGE_VERSION_FILE="$T/etc/IMAGE_VERSION" \
    HIFI_AB_GRUBD="$T/etc/45_hifi_abconvert" \
    HIFI_UPDATE_DIR="$T/update" \
    HIFI_API_BASE="http://127.0.0.1:9/api" \
    HIFI_TEST_CALLS="$T/calls" \
    HIFI_TEST_PRECHECK_JSON="$T/precheck.json" \
        timeout 20 sh "$S" >/dev/null 2>&1
    tr '\n' ' ' < "$T/calls" | sed 's/ *$//'
}

# ── il rilancio dell'aggiornamento è già stato fatto (caso di ogni
#    apparecchio che ha appena preso un aggiornamento e si è visto rifiutare
#    la conversione) ────────────────────────────────────────────────────
: > "$T/local/kickoff-done"
expect "rifiuto: ci riprova al prossimo avvio"        "$(run 1)" "precheck"
expect "…e non arma niente"                           "$([ -f "$T/etc/45_hifi_abconvert" ] && echo si || echo no)" no

# ── il proprietario ha tolto la musica dal disco di sistema ───────────
expect "ora passa: arma la conversione"               "$(run 0)" "precheck convert prepare"
# e lo dice: senza riavvio di sorpresa, questa riga è l'unico modo che ha di
# sapere che la sua mossa è servita
expect "…e lo scrive dove l'interfaccia lo legge"     "$(sed -n 's/^key=//p' "$T/update/state" 2>/dev/null)" update.ab.armed

# ── conversione già armata: non si rifà l'initrd a ogni avvio ─────────
: > "$T/etc/45_hifi_abconvert"
expect "già armata: non fa niente"                    "$(run 0)" ""
rm -f "$T/etc/45_hifi_abconvert"

# ── già convertito (RAUC configurato): non è più affar suo ────────────
: > "$T/etc/rauc-system.conf"
expect "già convertito: non fa niente"                "$(run 0)" ""
rm -f "$T/etc/rauc-system.conf"

# ── slot immagine: esce subito, qualunque cosa ci sia ─────────────────
mkdir -p "$T/etc"; : > "$T/etc/IMAGE_VERSION"
expect "sull'immagine non tocca niente"               "$(run 0)" ""
rm -f "$T/etc/IMAGE_VERSION"

echo "test-ab-image: $pass ok, $fail failed"
[ "$fail" = 0 ]
