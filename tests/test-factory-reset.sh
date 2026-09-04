#!/bin/bash
# Osmium Sound — the factory reset that erases the data partition.
#
# The wipe itself lives in the initramfs (scripts/local-bottom/hifi-state),
# because it cannot run under a system that is standing on /data. That makes it
# hard to reach code: it runs once, before PID 1, on a machine nobody is
# watching. So the block is lifted out of the script verbatim and exercised
# against a fake data partition here -- what it keeps, what it removes, and
# whether the box comes back with its setup wizard armed.
set -u

STATE_SCRIPT="distro/config/includes.chroot/etc/initramfs-tools/scripts/local-bottom/hifi-state"
RESET_SCRIPT="distro/config/includes.chroot/usr/local/sbin/hifi-factory-reset.sh"
pass=0; fail=0
ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); echo "FAIL: $1"; }
check(){ if [ "$2" = "$3" ]; then ok; else bad "$1: atteso '$3', ottenuto '$2'"; fi; }
exists()  { if [ -e "$2" ]; then ok; else bad "$1: manca $2"; fi; }
absent()  { if [ ! -e "$2" ]; then ok; else bad "$1: $2 doveva sparire"; fi; }

# The wipe block, lifted from the real script so the test cannot drift from it.
extract_wipe() {
    awk '/^if \[ "\$mounted" = 1 \] && \[ -e "\$D\/\.factory-reset" \]; then/,/^fi$/' "$STATE_SCRIPT"
}

run_wipe() {  # <data dir>
    D="$1" mounted=1 bash -c "
        log_begin_msg() { :; }; log_end_msg() { :; }
        D=\"\$D\"; mounted=\"\$mounted\"
        $(extract_wipe)
    "
}

seed_data() {  # <dir>  — una partizione dati vissuta
    d="$1"; rm -rf "$d"
    mkdir -p "$d/etc/upper/hifi-player" "$d/etc/upper/NetworkManager/system-connections" \
             "$d/etc/work" "$d/var/lib/hifi-player" "$d/home/hifi" \
             "$d/lyrion/current/usr/sbin" "$d/rauc"
    echo deadbeefdeadbeefdeadbeefdeadbeef > "$d/etc/upper/machine-id"
    echo db          > "$d/etc/upper/hifi-player/webui.db"
    echo it          > "$d/etc/upper/hifi-player/ui-language"
    echo casa        > "$d/etc/upper/hostname"
    echo psk         > "$d/etc/upper/NetworkManager/system-connections/wifi.nmconnection"
    echo cache       > "$d/var/lib/hifi-player/state.json"
    echo musica      > "$d/home/hifi/.bash_history"
    echo binario     > "$d/lyrion/current/usr/sbin/squeezeboxserver"
    echo slotstatus  > "$d/rauc/slot.status"
    echo v1          > "$d/var/.hifi-image-version"
}

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
[ -f "$STATE_SCRIPT" ] || { echo "manca $STATE_SCRIPT"; exit 1; }
[ -n "$(extract_wipe)" ] || { echo "il blocco di cancellazione non è più riconoscibile in $STATE_SCRIPT"; exit 1; }

# ── senza marcatore non si cancella niente ───────────────────────────
seed_data "$T/a"
run_wipe "$T/a"
exists "senza marcatore: i dati restano"        "$T/a/etc/upper/hifi-player/webui.db"
exists "senza marcatore: /home resta"           "$T/a/home/hifi/.bash_history"

# ── col marcatore ────────────────────────────────────────────────────
seed_data "$T/b"; : > "$T/b/.factory-reset"
run_wipe "$T/b"
absent "lo stato del web admin se ne va"        "$T/b/etc/upper/hifi-player/webui.db"
absent "la lingua del chiosco se ne va"         "$T/b/etc/upper/hifi-player/ui-language"
absent "il nome scelto se ne va"                "$T/b/etc/upper/hostname"
absent "le reti Wi-Fi salvate se ne vanno"      "$T/b/etc/upper/NetworkManager/system-connections/wifi.nmconnection"
absent "lo stato in /var se ne va"              "$T/b/var/lib/hifi-player/state.json"
absent "la cartella personale se ne va"         "$T/b/home/hifi/.bash_history"
absent "il marcatore stesso se ne va"           "$T/b/.factory-reset"
exists "Lyrion resta installato"                "$T/b/lyrion/current/usr/sbin/squeezeboxserver"
exists "la contabilità di RAUC resta"           "$T/b/rauc/slot.status"
exists "l'identità del player resta"            "$T/b/etc/upper/machine-id"
check  "…ed è la stessa di prima" \
       "$(cat "$T/b/etc/upper/machine-id")" "deadbeefdeadbeefdeadbeefdeadbeef"
exists "il wizard di configurazione riparte"    "$T/b/etc/upper/hifi-player/provisioning-pending"
check  "…col contenuto giusto" \
       "$(cat "$T/b/etc/upper/hifi-player/provisioning-pending")" "pending"
# La versione dell'immagine se ne va con /var: al riavvio l'initramfs ricopia
# /var e /home dall'immagine, che è ciò che rende la partizione "come nuova".
absent "il segno della versione se ne va"       "$T/b/var/.hifi-image-version"

# ── una partizione senza machine-id non deve inventarne uno vuoto ────
seed_data "$T/c"; : > "$T/c/.factory-reset"; rm -f "$T/c/etc/upper/machine-id"
run_wipe "$T/c"
absent "nessun machine-id vuoto lasciato in giro" "$T/c/etc/upper/machine-id"
exists "il wizard riparte lo stesso"              "$T/c/etc/upper/hifi-player/provisioning-pending"

# ── il ripristino a caldo instrada verso l'initramfs ─────────────────
if grep -q 'printf .requested by hifi-factory-reset' "$RESET_SCRIPT" \
   && grep -q 'IMAGE_VERSION' "$RESET_SCRIPT"; then ok; else
   bad "hifi-factory-reset.sh non lascia più il marcatore in modalità immagine"; fi
# Il ripiego conta: senza partizione dati montata il marcatore sparirebbe col
# riavvio e il ripristino non avverrebbe mai in silenzio.
if grep -q 'data-mounted' "$RESET_SCRIPT"; then ok; else
   bad "hifi-factory-reset.sh non controlla che la partizione dati sia montata"; fi
# Le preferenze del chiosco erano rimaste fuori dalla lista legacy.
for f in ui-language nowplaying-view ota-autocheck vu-meter-enabled; do
    if grep -q "$f" "$RESET_SCRIPT"; then ok; else bad "la lista legacy dimentica $f"; fi
done

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
