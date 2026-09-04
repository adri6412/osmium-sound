#!/bin/bash
# Osmium Sound — the read-ahead tuning for RAUC's HTTP streaming.
#
# RAUC makes one HTTP range request per NBD read, so the request size decides
# how long a 1 GiB image takes to arrive. hifi-stream-tune.sh raises it on the
# devices RAUC creates while it installs. It runs *inside* an update, so the
# rules it must obey are: never fail the update, apply what the kernel accepts
# and skip what it does not, and always leave the measurement behind.
#
# Hermetic: everything runs against a fake /sys, no NBD, no appliance.
set -u
S="distro/config/includes.chroot/usr/local/sbin/hifi-stream-tune.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export HIFI_SYSFS="$T/sys"
export HIFI_STREAM_SUMMARY="$T/summary"
export HIFI_STREAM_POLL=1

# fake_dev <name> <size_sectors> [max_hw_sectors_kb]
fake_dev() {
    d="$HIFI_SYSFS/block/$1"
    mkdir -p "$d/queue"
    printf '%s\n' "$2" > "$d/size"
    printf '0 0 0 0 0 0 0 0 0 0 0\n' > "$d/stat"
    printf '128\n' > "$d/queue/read_ahead_kb"
    printf '128\n' > "$d/queue/max_sectors_kb"
    [ -n "${3:-}" ] && printf '%s\n' "$3" > "$d/queue/max_hw_sectors_kb"
    return 0
}

# ── 1. tune: read-ahead up, request size up ─────────────────────────────
fake_dev nbd0 2097152 32767
"$S" tune nbd0 >/dev/null 2>&1
got=$(cat "$HIFI_SYSFS/block/nbd0/queue/read_ahead_kb")
if [ "$got" = 8192 ]; then ok; else bad "read_ahead_kb non alzato ($got)"; fi
got=$(cat "$HIFI_SYSFS/block/nbd0/queue/max_sectors_kb")
if [ "$got" = 2048 ]; then ok; else bad "max_sectors_kb non alzato ($got)"; fi

# ── 2. il tetto del driver vince sul valore richiesto ────────────────────
rm -rf "${HIFI_SYSFS:?}/block"
fake_dev nbd0 2097152 512
"$S" tune nbd0 >/dev/null 2>&1
got=$(cat "$HIFI_SYSFS/block/nbd0/queue/max_sectors_kb")
if [ "$got" = 512 ]; then ok; else bad "max_sectors_kb non limitato a max_hw ($got)"; fi

# ── 2b. un valore già più alto non va abbassato ──────────────────────────
# Il kernel parte da 1280 KiB per richiesta sui device NBD: scrivere il valore
# "buono" senza guardare farebbe richieste più PICCOLE, cioè l'opposto.
rm -rf "${HIFI_SYSFS:?}/block"
fake_dev nbd0 2097152 32767
printf '4096\n' > "$HIFI_SYSFS/block/nbd0/queue/max_sectors_kb"
"$S" tune nbd0 >/dev/null 2>&1
got=$(cat "$HIFI_SYSFS/block/nbd0/queue/max_sectors_kb")
if [ "$got" = 4096 ]; then ok; else bad "ha abbassato max_sectors_kb a $got"; fi

# ── 3. un attributo assente non deve fermare gli altri ───────────────────
rm -rf "${HIFI_SYSFS:?}/block"
fake_dev nbd0 2097152
rm -f "$HIFI_SYSFS/block/nbd0/queue/max_sectors_kb"
"$S" tune nbd0 >/dev/null 2>&1
got=$(cat "$HIFI_SYSFS/block/nbd0/queue/read_ahead_kb")
if [ "$got" = 8192 ]; then ok; else bad "un attributo mancante ha impedito il resto ($got)"; fi

# ── 4. watch: sceglie il device collegato, tocca anche il dm-verity ──────
rm -rf "${HIFI_SYSFS:?}/block"
fake_dev nbd0 0 32767          # libero: da ignorare
fake_dev nbd1 2097152 32767    # quello che RAUC sta usando
fake_dev dm-3 2097152 32767
mkdir -p "$HIFI_SYSFS/block/dm-3/slaves/nbd1"   # dm-verity impilato su nbd1
(   # l'apparecchio finisce di scaricare e RAUC stacca il device
    sleep 2
    printf '100 0 204800 0 0 0 0 0 0 0 0\n' > "$HIFI_SYSFS/block/nbd1/stat"
    sleep 1
    printf '0\n' > "$HIFI_SYSFS/block/nbd1/size"
) &
out=$("$S" watch 30 2>&1)
wait
got=$(cat "$HIFI_SYSFS/block/nbd1/queue/read_ahead_kb")
if [ "$got" = 8192 ]; then ok; else bad "watch non ha alzato il read-ahead del device collegato ($got)"; fi
got=$(cat "$HIFI_SYSFS/block/nbd0/queue/read_ahead_kb")
if [ "$got" = 128 ]; then ok; else bad "watch ha toccato un device nbd libero ($got)"; fi
got=$(cat "$HIFI_SYSFS/block/dm-3/queue/read_ahead_kb")
if [ "$got" = 8192 ]; then ok; else bad "watch non ha alzato il read-ahead del dm-verity ($got)"; fi

# ── 5. la misura resta scritta ──────────────────────────────────────────
summary=$(cat "$HIFI_STREAM_SUMMARY" 2>/dev/null)
case "$summary" in *"100 read requests"*) ok ;; *) bad "riassunto senza il numero di richieste: $summary" ;; esac
case "$summary" in *"avg 1024 KiB"*)      ok ;; *) bad "dimensione media sbagliata: $summary" ;; esac
case "$summary" in *"100 MiB"*)           ok ;; *) bad "byte trasferiti sbagliati: $summary" ;; esac

# ── 5b. misura senza toccare niente (il "prima" di un confronto) ─────────
rm -rf "${HIFI_SYSFS:?}/block"
fake_dev nbd1 2097152 32767
(   sleep 2
    printf '50 0 12800 0 0 0 0 0 0 0 0\n' > "$HIFI_SYSFS/block/nbd1/stat"
    sleep 1
    printf '0\n' > "$HIFI_SYSFS/block/nbd1/size"
) &
HIFI_STREAM_TUNE=0 "$S" watch 30 >/dev/null 2>&1
wait
got=$(cat "$HIFI_SYSFS/block/nbd1/queue/read_ahead_kb")
if [ "$got" = 128 ]; then ok; else bad "con TUNE=0 ha comunque toccato le code ($got)"; fi
summary=$(cat "$HIFI_STREAM_SUMMARY" 2>/dev/null)
case "$summary" in *"avg 128 KiB"*) ok ;; *) bad "con TUNE=0 manca la misura: $summary" ;; esac

# ── 6. nessun device: esce bene, l'aggiornamento non si ferma ────────────
rm -rf "${HIFI_SYSFS:?}/block"; mkdir -p "$HIFI_SYSFS/block"
out=$("$S" watch 2 2>&1); rc=$?
if [ "$rc" = 0 ]; then ok; else bad "senza device esce con $rc invece di 0"; fi
case "$out" in *"nothing to tune"*) ok ;; *) bad "senza device non lo dice: $out" ;; esac

echo "test-stream-tune: $pass ok, $fail falliti"
[ "$fail" = 0 ]
