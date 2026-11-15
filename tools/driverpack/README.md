# Osmium driver packs

A **driver pack** (`.osmpack`) lets you ship a firmware blob or an out-of-tree
kernel module to a user whose laptop needs something the image does not carry —
a per-model Wi-Fi/touch firmware we may not redistribute, or a driver we only
learn is missing after a report. The user installs it **after** installation,
from a **USB stick** (offline — it is often the Wi-Fi that is dead) or a **web
upload**, and it **survives OTA updates**.

The whole trust model is one signature: the device verifies the pack with the
**same Ed25519 OTA key** it uses for OS updates, so only packs **you** signed
install. See [`distro/config/includes.chroot/usr/local/sbin/hifi-driverpack.sh`](../../distro/config/includes.chroot/usr/local/sbin/hifi-driverpack.sh).

## Build and sign

```sh
tools/make-driverpack.sh <source-dir> [out-dir]
```

Source layout:

```
<source-dir>/
  manifest.json
  firmware/<path-under-/lib/firmware>/<blob>      # firmware/mediatek/mt7650e.bin
  modules/<kernel-version>/<name>.ko              # modules/6.12.113+deb13-amd64/foo.ko
```

`manifest.json` is flat JSON (the device reads it with `sed`, so keep it flat):

```json
{
  "name": "mediatek-wifi",
  "description": "MediaTek MT76x0 Wi-Fi firmware",
  "type": "firmware",
  "target_kernel": "6.12.113+deb13-amd64",
  "modules": ["foo.ko"]
}
```

- `name` — lowercase `[a-z0-9._+-]`; the install name and the output basename.
- `type` — `firmware`, `modules`, or `both`.
- `target_kernel` — **required when `modules/` is present**. If the device runs a
  different kernel (e.g. after an OTA that bumped it), the firmware is still
  installed but the modules are skipped and the device asks for an updated pack.
- `modules` — the `.ko` load order (dependencies first). Omit for firmware-only.

Output: three files you ship to the user — `<name>.osmpack`,
`<name>.osmpack.sha256`, `<name>.osmpack.sha256.sig`.

Signing key: `distro/ota-keys/ota-signing-key.pem` by default (gitignored, never
committed). In CI, set `OTA_SIGNING_KEY` to the PEM contents (same secret as
`build-ui-ota.yml`).

## Firmware

No build step — just place the blob at the path the kernel asks for, under
`firmware/`. The failing `dmesg` line names it exactly, e.g.
`Direct firmware load for mediatek/mt7650e.bin failed with error -2` →
`firmware/mediatek/mt7650e.bin`. On the device it lands in a read-only sysext
layered over `/usr/lib/firmware`, found by the kernel with no further config.
Firmware works **with Secure Boot on**.

## Kernel modules (.ko)

🚨 Build against the **exact pinned kernel** or the device refuses to load the
module. The image pins `6.12.113+deb13-amd64`. Same out-of-tree pattern as
[`0440-surface-ipts.hook.chroot`](../../distro/config/hooks/normal/0440-surface-ipts.hook.chroot):

```sh
KVER=6.12.113+deb13-amd64
apt-get install -y linux-headers-$KVER build-essential
# in the module's source tree:
make -C /lib/modules/$KVER/build M="$PWD" modules
strip --strip-debug -o foo.ko foo.ko
mkdir -p modules/$KVER && cp foo.ko modules/$KVER/
```

🚨 **Secure Boot.** Unsigned out-of-tree modules are refused by the kernel when
UEFI Secure Boot is on (the same limit as `ipts.ko` / `wl.ko`). The user turns
Secure Boot off in the BIOS. Signing modules with our own key via MOK so they
load with Secure Boot on is a future (v2) track.

Loading: the device cannot `depmod`/`modprobe` (`/usr/lib/modules` is a
read-only squashfs), so each `.ko` is loaded by absolute path with `insmod`, in
the `modules` order from the manifest, at install time and again at every boot.
List dependencies before the modules that need them.
