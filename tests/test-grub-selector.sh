#!/bin/bash
# Osmium Sound — the A/B boot selector on the ESP, run by GRUB itself.
#
# grub-selector.cfg.tmpl is executed by the real GRUB script engine
# (grub-emu, the userspace build of GRUB) against a disk image with the
# appliance's layout: p2 the ESP with the selector and its grubenv, p3 and p4
# the two slots. Each slot's grub.cfg only says it was reached and "reboots";
# what the operating system would then do (mark the boot good, or not) is
# done here on the grubenv between one boot and the next.
#
# What must hold:
#  - a newly installed image that never comes up falls back after ONE boot
#    (the protection against a broken image);
#  - an image already proven good is NOT abandoned over one bad boot (a power
#    cut half-way, a slow disk check): it gets its attempts first;
#  - a stale proof (the slot holds a different image now) counts for nothing.
#
# Needs grub-emu, grub-editenv, grub-script-check, mke2fs, debugfs and
# python3; skipped when they are not there (CI runners do not have grub-emu).
# GRUB_EMU / GRUB_EDITENV / GRUB_SCRIPT_CHECK point at them if they are not on
# PATH.
set -u
TMPL="$PWD/distro/config/includes.chroot/usr/local/share/hifi-ab/grub-selector.cfg.tmpl"
pass=0; fail=0
ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
expect() { if [ "$2" = "$3" ]; then ok; else bad "$1: expected '$3', got '$2'"; fi; }

EMU=${GRUB_EMU:-$(command -v grub-emu 2>/dev/null)}
EDITENV=${GRUB_EDITENV:-$(command -v grub-editenv 2>/dev/null)}
CHECK=${GRUB_SCRIPT_CHECK:-$(command -v grub-script-check 2>/dev/null)}
for t in "$EMU" "$EDITENV" "$CHECK"; do
    if [ -z "$t" ] || [ ! -x "$t" ]; then
        echo "SKIP: grub-emu/grub-editenv/grub-script-check not available"; exit 0
    fi
done
for t in mke2fs debugfs python3; do
    command -v "$t" >/dev/null 2>&1 || { echo "SKIP: $t missing"; exit 0; }
done

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
SEL="$T/selector.cfg"
sed 's/@LEGACY_UUID@/00000000-0000-0000-0000-000000000000/' "$TMPL" > "$SEL"
"$CHECK" "$SEL" || { bad "the selector does not pass grub-script-check"; echo "test-grub-selector: $pass passed, $fail failed"; exit 1; }
ok

# A GPT disk image out of partition images. Prints "<offset> <size>" for each.
cat > "$T/mkgpt.py" <<'PY'
import sys, struct, zlib, uuid, os
out, parts = sys.argv[1], sys.argv[2:]
SEC = 512
lbas, cur = [], 2048
for p in parts:
    n = (os.path.getsize(p) + SEC - 1) // SEC
    lbas.append((cur, cur + n - 1))
    cur = (cur + n + 2047) // 2048 * 2048
total = cur + 2048
entries = bytearray(128 * 128)
linux = uuid.UUID('0fc63daf-8483-4772-8e79-3d69d8477de4').bytes_le
for i, (s, e) in enumerate(lbas):
    entries[i * 128:(i + 1) * 128] = struct.pack('<16s16sQQQ72s', linux, uuid.uuid4().bytes_le, s, e, 0,
                                                 ('p%d' % (i + 1)).encode('utf-16-le'))
ecrc = zlib.crc32(entries) & 0xffffffff
def header(me, alt, ent):
    h = struct.pack('<8sIIIIQQQQ16sQIII', b'EFI PART', 0x10000, 92, 0, 0, me, alt, 34, total - 34,
                    uuid.uuid4().bytes_le, ent, 128, 128, ecrc)
    h = h[:16] + struct.pack('<I', zlib.crc32(h) & 0xffffffff) + h[20:]
    return h + b'\0' * (SEC - len(h))
with open(out, 'wb') as f:
    f.truncate(total * SEC)
    mbr = bytearray(SEC)
    mbr[446:462] = struct.pack('<BBBBBBBBII', 0, 0, 2, 0, 0xee, 0xff, 0xff, 0xff, 1, total - 1)
    mbr[510:512] = b'\x55\xaa'
    f.seek(0); f.write(mbr)
    f.seek(SEC); f.write(header(1, total - 1, 2))
    f.seek(2 * SEC); f.write(entries)
    f.seek((total - 33) * SEC); f.write(entries)
    f.seek((total - 1) * SEC); f.write(header(total - 1, 1, total - 33))
    for p, (s, e) in zip(parts, lbas):
        f.seek(s * SEC); f.write(open(p, 'rb').read())
for s, e in lbas:
    print(s * SEC, (e - s + 1) * SEC)
PY

id_block() {  # <id>: /boot/grub/osmium-id.env as build-image.sh writes it
    { printf '# GRUB Environment Block\nOSMIUM_ID=%s\n' "$1"; head -c 1024 /dev/zero | tr '\0' '#'; } | head -c 1024
}

# make_disk <id of the image in A> <id of the image in B>; "" = no id file
make_disk() {
    rm -rf "$T/d"; mkdir -p "$T/d/esp/EFI/debian" "$T/d/a/boot/grub" "$T/d/b/boot/grub"
    cp "$SEL" "$T/d/esp/EFI/debian/grub.cfg"
    : > "$T/d/esp/EFI/debian/ab-enabled"
    "$EDITENV" "$T/d/esp/EFI/debian/grubenv" create
    for s in a b; do
        S=$(printf '%s' "$s" | tr ab AB)
        printf 'echo "SLOT-BOOTED %s"\nreboot\n' "$S" > "$T/d/$s/boot/grub/grub.cfg"
    done
    [ -z "$1" ] || id_block "$1" > "$T/d/a/boot/grub/osmium-id.env"
    [ -z "$2" ] || id_block "$2" > "$T/d/b/boot/grub/osmium-id.env"
    head -c 1048576 /dev/zero > "$T/d/bios.img"
    mke2fs -q -t ext2 -d "$T/d/esp" "$T/d/esp.img" 4M >/dev/null 2>&1
    mke2fs -q -t ext2 -d "$T/d/a" "$T/d/a.img" 2M >/dev/null 2>&1
    mke2fs -q -t ext2 -d "$T/d/b" "$T/d/b.img" 2M >/dev/null 2>&1
    python3 "$T/mkgpt.py" "$T/d/disk.img" "$T/d/bios.img" "$T/d/esp.img" "$T/d/a.img" "$T/d/b.img" > "$T/d/layout"
    ESP_OFF=$(sed -n 2p "$T/d/layout" | cut -d' ' -f1)
    ESP_SIZE=$(sed -n 2p "$T/d/layout" | cut -d' ' -f2)
    echo "(hd0) $T/d/disk.img" > "$T/d/device.map"
}

esp_out() { dd if="$T/d/disk.img" of="$T/d/esp.cur" bs=512 skip=$((ESP_OFF / 512)) count=$((ESP_SIZE / 512)) status=none; }
esp_in()  { dd if="$T/d/esp.cur" of="$T/d/disk.img" bs=512 seek=$((ESP_OFF / 512)) conv=notrunc status=none; }

env_set() {  # NAME=value... on the grubenv inside the disk image
    esp_out
    debugfs -R "dump /EFI/debian/grubenv $T/d/env" "$T/d/esp.cur" >/dev/null 2>&1
    "$EDITENV" "$T/d/env" set "$@"
    debugfs -w -R "rm /EFI/debian/grubenv" "$T/d/esp.cur" >/dev/null 2>&1
    debugfs -w -R "write $T/d/env /EFI/debian/grubenv" "$T/d/esp.cur" >/dev/null 2>&1
    esp_in
}
env_get() {  # NAME
    esp_out
    debugfs -R "dump /EFI/debian/grubenv $T/d/env" "$T/d/esp.cur" >/dev/null 2>&1
    "$EDITENV" "$T/d/env" list | sed -n "s/^$1=//p"
}

boot() {  # -> the slot GRUB handed over to, or "none"
    timeout 20 "$EMU" -m "$T/d/device.map" -r hd0,gpt2 -d /EFI/debian < /dev/null > "$T/d/out" 2>&1
    s=$(tr -d '\r' < "$T/d/out" | sed -n 's/.*SLOT-BOOTED \([AB]\).*/\1/p' | head -n 1)
    echo "${s:-none}"
}

good() {  # <slot> <id>: what hifi-boot-health.sh does once the boot is good
    if [ -n "$2" ]; then env_set "$1_OK=1" "$1_TRY=0" "$1_GOOD=$2" "$1_LEFT=2"
    else env_set "$1_OK=1" "$1_TRY=0"; fi
}

# ── 1. a new image that never comes up falls back after one boot ────────
# B just installed by RAUC (first in ORDER, OK=1 TRY=0); A is the image that
# was running and was marked good.
make_disk "img-1" "img-2"
env_set ORDER="B A" A_OK=1 A_TRY=0 A_GOOD=img-1 A_LEFT=2 B_OK=1 B_TRY=0
expect "a new image is tried"                     "$(boot)" B
expect "...as a trial"                            "$(env_get B_TRY)" 1
expect "it never came up: back to A at once"      "$(boot)" A
good A img-1
expect "A is where it stays"                      "$(boot)" A
expect "...B is left as RAUC's failed trial"      "$(env_get B_TRY)" 1

# ── 2. the same, with a proof left over from the image B held before ────
make_disk "img-1" "img-2"
env_set ORDER="B A" A_OK=1 A_TRY=0 A_GOOD=img-1 A_LEFT=2 B_OK=1 B_TRY=0 B_GOOD=img-0 B_LEFT=2
expect "a stale proof: the new image is tried"    "$(boot)" B
expect "...and still falls back after one boot"   "$(boot)" A

# ── 3. a proven image is not abandoned over one bad boot ───────────────
make_disk "img-1" "img-2"
env_set ORDER="B A" A_OK=1 A_TRY=0 A_GOOD=img-1 A_LEFT=2 B_OK=1 B_TRY=0
expect "first boot of B"                          "$(boot)" B
good B img-2
expect "B came up and is marked good"             "$(env_get B_GOOD)" img-2
expect "an ordinary boot of B"                    "$(boot)" B
# ...and this one is cut short (power cut, slow disk check): not marked good
expect "after one bad boot B is tried again"      "$(boot)" B
expect "...using one attempt"                     "$(env_get B_LEFT)" 1
good B img-2
expect "a good boot gives the attempts back"      "$(env_get B_LEFT)" 2

# ── 4. ...but a proven image that keeps failing does fall back ──────────
expect "B"                                        "$(boot)" B
expect "bad boot 1: B again"                      "$(boot)" B
expect "bad boot 2: B again"                      "$(boot)" B
expect "bad boot 3: out of attempts, A"           "$(boot)" A
expect "and B stays out"                          "$(boot)" A

# ── 5. a slot with no id (converted legacy root, older image) ───────────
make_disk "" "img-2"
env_set ORDER="A B" A_OK=1 A_TRY=0 A_GOOD=whatever A_LEFT=2 B_OK=1 B_TRY=0
expect "legacy A boots"                           "$(boot)" A
expect "legacy A without the file: one-shot trial" "$(boot)" B

# ── 6. both slots used up: both get another chance, nothing hangs ───────
make_disk "img-1" "img-2"
env_set ORDER="B A" A_OK=1 A_TRY=1 B_OK=1 B_TRY=1
expect "both tried and failed: B first again"     "$(boot)" B

# ── 7. a selector env written by the version-1 selector still works ────
make_disk "img-1" "img-2"
env_set ORDER="A B" A_OK=1 A_TRY=0 B_OK=0 B_TRY=0
expect "no GOOD/LEFT variables at all"            "$(boot)" A
expect "...a bad boot falls back as in version 1" "$(boot)" A
expect "...B is not bootable (OK=0)"              "$(env_get B_OK)" 0

echo "test-grub-selector: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
