# Osmium Sound — Debian Appliance Distro

Builds a self-contained, **installable Debian ISO** that turns any x86-64 PC into
a network streamer running the Osmium Sound kiosk on top of Lyrion Music
Server. The boot menu shows two branded entries — **Install Osmium Sound**
(default) and **Try Osmium Sound (no install)** — both booting the same live
system; after install the machine has a **completely hidden boot** (no GRUB
menu, no kernel text, branded Plymouth splash) that goes straight into the
fullscreen player — or into headless operation, if that's what was chosen at
setup.

> **No Debian Installer.** The installer is the appliance itself, in a
> different mode. The "Install" boot entry passes an extra kernel parameter
> (`hifi.installer=1`) that tells the Electron app (`src/App.jsx` →
> `InstallWizard`) to show a QR code instead of the kiosk UI, and tells
> `webui_server.py` to raise the open `Osmium-Setup-XXXX` hotspot + captive
> portal. The phone drives the install (pick a target disk, confirm, start);
> the screen only mirrors progress. The actual disk work
> (partition/format/copy/bootloader) is done by
> `config/includes.chroot/usr/local/sbin/hifi-disk-install.sh`, launched by
> `api_server.py`'s `/install/*` endpoints (same `systemd-run` + `/run`
> status-file pattern as every other long-running job in this codebase). It
> `unsquashfs`'s the live filesystem's own `filesystem.squashfs` straight onto
> the target disk (GPT: 1MiB bios_grub + 512MiB EFI + rest ext4), then chroots
> in and runs `hifi-grub-install.sh` + `hifi-finalize-boot.sh`. See
> [ARCHITECTURE.md → Provisioning & first boot](../ARCHITECTURE.md#provisioning--first-boot).

## Compliance Notice

**ISO versions v2.5.7 and earlier** included Lyrion Music Server 9.1.0 bundled
in the image, licensed under GPL-2.0+. Source code is available from the
[LMS-Community GitHub releases](https://github.com/LMS-Community/slimserver/releases/tag/v9.1.0).
See [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md) for full details.

**Later ISOs:** Lyrion is **not** bundled at all — it is absent from the live
squashfs and from every disk install, and is downloaded on the first boot of
the installed system (or by the setup wizard).

> **Why a live filesystem still exists.** The whole appliance (Electron app,
> Python daemons, helper scripts, the `hifi` user/services) is assembled in the
> live squashfs. Booting "Try Osmium Sound" just runs that squashfs live, same
> as any live-build ISO. Booting "Install Osmium Sound" boots the *same*
> squashfs, then `hifi-disk-install.sh` `unsquashfs`'s the squashfs image
> straight onto the target disk — a real copy, not a live overlay clone, so the
> target ends up pristine regardless of anything written during the
> live/install session itself.

## What the image contains

Debian **13 "trixie"** base (`DEBIAN_SUITE` in `build-distro.sh`; the kiosk
needs `labwc`/`wlr-randr`/`xwayland`, which only exist from trixie on — the
script refuses `--suite bookworm`).

| Component | Role | Service / port |
|---|---|---|
| Osmium Sound kiosk (Electron) | Fullscreen touchscreen UI | LightDM autologin (`hifi`) → `hifi-kiosk` session; **Wayland (labwc) where there is a real GPU, X11 otherwise** — decided at every boot by `hifi-kiosk-session.service` (`hifi-kiosk-session.sh`, override via `/etc/hifi-player/kiosk-session`) |
| `api_server.py` | Root system API (network, audio, OTA, display mode, installer, …) | `hifi-api.service`, `127.0.0.1:8000` |
| `sources_server.py` | Music sources, internal/USB disks, SMB shares, CD rip, backup/restore, Lyrion skin + first-run setup; companion-app proxy | `hifi-sources.service`, `0.0.0.0:8080` (pairing-token gated) |
| `webui_server.py` | Web admin (Vue app in `/opt/hifi-webui/dist`) + first-boot setup portal / installer captive portal | `hifi-webui.service`, `:80` (plain HTTP) |
| `vu_meter_daemon.py` | Streams VU levels from `/dev/shm/squeezelite-*` to the kiosk | `hifi-vumeter.service`, WebSocket `127.0.0.1:9001` |
| squeezelite (Debian, `-v`) | Local player + VU visualizer export, DSD over DoP | `squeezelite.service` |
| Lyrion Music Server | Music server / library / streaming (**installed on first boot**, not in the image) | `lyrionmusicserver.service` (`:9000`) |
| `hifi-firstboot.sh` | One-shot: downloads + installs Lyrion on the installed system, then removes itself | `hifi-firstboot.service` (`ConditionKernelCommandLine=!boot=live`) |
| `hifi-update-stage-runner.sh` / `hifi-update-apply-runner.sh` | The two-phase "Update now" (stage live → reboot into `system-update.target` → apply in isolation) | transient `hifi-update-stage`, `hifi-update-stage-resume.service`, `hifi-update-apply.service` |
| `hifi-backup-run.py` | Backup generations (on demand / weekly timer) | `hifi-backup.service` + `hifi-backup.timer` (shipped by `apply.d/0033-backup-scheduler.sh`) |
| `hifi-mdns-keepalive.sh` | Periodic mDNS/ARP re-announce so idle units stay reachable | `hifi-mdns-keepalive.timer` |
| `hifi-quiesce-audio-shutdown.sh` | Stops audio cleanly before any shutdown/reboot (DesignWare DMA panic workaround) | `hifi-quiesce-audio-shutdown.service` |
| Samba (`smbd`), `wsdd2`, Avahi | SMB shares of adopted disks (units start only when a share exists), Windows network discovery, mDNS | disabled until needed / enabled at build |
| Plymouth theme `hifi` | Boot splash; also shows OTA apply progress | — |

OpenSSH ships **disabled**; `root` is locked and the `hifi` kiosk user has no
password. Tailscale is installed (hook `0410-tailscale.hook.chroot`) but
off until the owner enables it from the web admin.

## First boot & setup

The image is seeded with `/etc/hifi-player/provisioning-pending` (only
`build-distro.sh` and `hifi-factory-reset.sh` ever create it). While it exists:

- the kiosk shows `SetupWizard` — a Wi-Fi picker on the touchscreen (nothing to
  do if wired), then the box's own address in plain text;
- `webui_server.py` serves the **setup portal** on `http://<ip>` for the rest
  of the configuration from a phone/laptop (language, restore, update gate,
  name, device mode, pointer, audio, Lyrion local/external, web-player look,
  music services, web-admin account, time zone, sources). `finalize` applies
  the chosen display mode live and removes the marker.

No hotspot is raised at setup (only the installer and the network-loss
recovery page use one). Lyrion is installed by `hifi-firstboot.service` on the
first boot with network, or synchronously by the wizard's Lyrion step if that
hasn't happened yet. The full flow is documented in
[ARCHITECTURE.md → Provisioning & first boot](../ARCHITECTURE.md#provisioning--first-boot).

The VU meter works because the Debian `squeezelite` package is built with
`VISEXPORT` and is launched with `-v` (`config/includes.chroot/etc/default/squeezelite`),
which exports `/dev/shm/squeezelite-*` for the VU daemon.

## Network audio receivers ("cast" from the phone)

The device can appear on the network as an audio target for phone apps. This
is done with **Lyrion plugins**, not system services — the audio goes through
Lyrion/squeezelite, so there is a single audio path and no ALSA contention.
Install them once from Lyrion's web UI → **Settings → Plugins** (the device
needs internet):

| Protocol | Lyrion plugin | Source app |
|---|---|---|
| **AirPlay** | ShairTunes2 | iPhone/iPad/Mac → AirPlay icon |
| **UPnP/DLNA** | UPnP/DLNA Media Interface | BubbleUPnP & co. (Android) |
| **Spotify Connect** | Spotty | Spotify app (Premium) → devices |

> A real **Google Cast/Chromecast** receiver is not available: the receiver
> side of the protocol is proprietary and there is no open implementation for
> audio.

## Prerequisites (on the build server)

A Debian machine (or container/VM) with internet access — CI uses a
`debian:bookworm` container to build the trixie image. The build script
installs `live-build`, `imagemagick`, `curl`, `xorriso` itself. You need
~15 GB free disk and root.

> The build server needs Node only to **pre-build** the two web apps: the
> Electron kiosk (`dist/linux-unpacked`) and the web admin
> (`admin-webui/dist`) are consumed pre-compiled.

## 1. Compile the kiosk and the web admin (once, anywhere with Node 20)

```bash
npm ci
npm run build
npx electron-builder --linux dir          # → dist/linux-unpacked/
(cd admin-webui && npm ci && npm run build)  # → admin-webui/dist/  (required: the build refuses to ship without it)
```

Copy `dist/linux-unpacked/` and `admin-webui/dist/` (or the whole repo) to the
build server.

## 2. Build the ISO (on the Debian server, as root)

```bash
cd distro
sudo ./build-distro.sh --app-dir /path/to/dist/linux-unpacked
```

If `--app-dir` is omitted the script looks in `../dist/linux-unpacked`,
`../linux-unpacked`, and `~/hifi-build/dist/linux-unpacked`.

Result: **`../hifi-player-installer.iso`** (next to the repo root; override the
name with the `ISO_NAME` env var — CI uses `hifi-player-<tag>.iso`).

Useful overrides:

```bash
sudo ./build-distro.sh \
  --app-dir ../dist/linux-unpacked \
  --app-version 2.5.22 \
  --lyrion-url https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/lyrionmusicserver_9.1.0_all.deb \
  --suite trixie
```

`--app-version` seeds `UI_VERSION`, `SYSTEM_VERSION` and `OS_VERSION` in the
image (the OTA system compares against them); the OTA public key
(`ota-keys/ota-pubkey.pem`) and the provisioning marker are seeded at the same
time.

### Incremental / staged builds (don't rebuild everything)

live-build runs three stages — **bootstrap → chroot → binary** — slow on the
left, fast on the right. Use `--stage` to rebuild only what changed and reuse
the rest (the Debian package cache in `distro/cache/` is kept across runs):

| `--stage` | Rebuilds | Reuses | When |
|---|---|---|---|
| `all` *(default)* | chroot + binary | package cache | first build, or chroot contents changed |
| `chroot` | bootstrap (if missing) + chroot + binary | package cache | changed packages / chroot hooks / app payload |
| `binary` | only the ISO image | the existing chroot | iterating on **boot menus / splash / ISO layout** |

```bash
# First time (full build)
sudo ./build-distro.sh --app-dir ../dist/linux-unpacked --stage all

# Then fast re-spins after tweaking the boot splash / 0500-brand-boot hook:
sudo ./build-distro.sh --stage binary       # seconds-to-minutes, reuses chroot
```

A `--stage binary` run skips the Electron/python/web-admin injection entirely
(those live in the chroot, which is reused), so `--app-dir` isn't required for
it. Add `--clean-cache` to also wipe the downloaded-package cache.

### Build the ISO on GitHub (manual, by tag)

You can also build the ISO in CI without a local Debian box: GitHub →
**Actions → "Build HiFi Player ISO (manual)" → Run workflow**, type the
**tag** (e.g. `v2.5.21`) and run it (from the CLI pass `--ref <tag>` explicitly,
otherwise it builds `main`). The workflow compiles the kiosk and the web
admin, runs `build-distro.sh` as root, produces `hifi-player-<tag>.iso` +
`.sha256` + an Ed25519 `.sha256.sig` + `latest.json`, uploads them as an
artifact and (if `make_release` is on, the default) attaches the ISO to the
tag's GitHub Release. The public download lives on **file.osmiumsound.it**
(where Osmium Flasher reads `latest.json`); `tools/publish-iso.sh` produces the
same file set by hand. Optional inputs: `lyrion_url`, `suite` (default
`trixie`). See `.github/workflows/build-iso.yml` and the
[workflows README](../.github/workflows/README.md).

## 3. Install on the target PC

Write the ISO to a USB stick (Osmium Flasher, balenaEtcher, Rufus, or `dd`)
and boot the target:

```bash
sudo dd if=hifi-player-installer.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

> The boot menu shows two branded entries (gold "Osmium Sound" on black,
> **same logo as the Plymouth splash**): **Install Osmium Sound** (default,
> auto-starts on timeout) and **Try Osmium Sound (no install)**.

Booting "Install Osmium Sound" starts the normal live session, but the kiosk
opens straight into `InstallWizard` — a QR code — and the box raises the open
`Osmium-Setup-XXXX` hotspot (or is reachable at its LAN IP when wired). From
the phone: pick the target disk (the disk backing the boot medium itself is
excluded) → confirm the clear "all data will be erased" warning → progress →
done; the screen reboots on its own.

- No username/password/language/keyboard/timezone questions at install time —
  the `hifi` user, services and app are already part of the squashfs being
  copied; everything personal is asked at first boot.
- The target disk is wiped and repartitioned (GPT: bios_grub + EFI + ext4),
  GRUB is installed for the machine's actual firmware mode (BIOS or UEFI,
  detected from the live session's own boot mode; the signed
  shim/grub-efi-amd64-signed chain is in the package list for Secure Boot
  machines, **at build time only** — the bootloader is never touched by OTA).

> ⚠️ **Confirming the install wipes the selected disk.** There's no "guided
> vs manual partitioning" choice — a device is picked, and it's wiped and
> replaced entirely (see `hifi-disk-install.sh`).

After reboot the machine boots **silently** into the first-boot setup, then
(on a unit with a screen) straight into the fullscreen player: no desktop, no
login screen, no visible GRUB.

**No default credentials ship in the image.** The kiosk user `hifi` has no
password at all and `root` is locked, so a freshly installed appliance carries
nothing guessable. The SSH/console login is created from the admin account you
set in the provisioning wizard: that same username/password becomes a Linux user
with full sudo (`api_server.py` `set_shell_account`), and SSH itself stays
disabled until you turn it on in Settings. On a device provisioned before this
change, Settings → SSH offers a "create SSH login" form.

Without such a login, recovery is physical: GRUB `init=/bin/bash`, or the
kiosk's own "reset web-admin password" button on the touchscreen.

### How the boot menu picks installer vs kiosk

The boot menus are written by the binary hook
`config/hooks/normal/0500-brand-boot.hook.binary`, which **autodetects** the
live kernel/initrd location on the ISO (the exact path varies by live-build
version/arch; hardcoding it previously broke booting with "vmlinuz not
found") and writes two entries, for both isolinux (BIOS) and grub (UEFI),
pointing at the **same** kernel/initrd/squashfs:

- **Install Osmium Sound** (default): `... hifi.installer=1`
- **Try Osmium Sound (no install)**: same append, without that parameter

Both append `boot=live quiet splash loglevel=0 vt.global_cursor_default=0
hostname=hifiplayer noautologin`. `api_server.py`'s `/boot_mode` endpoint
(and `webui_server.py`'s `_boot_mode()`) read `/proc/cmdline` for
`hifi.installer=1` and `src/App.jsx` uses it to decide which UI to show. The
gold-on-black splash comes from
`config/includes.binary/{isolinux,boot/grub}/splash.png`. To boot into the
kiosk UI instead of the installer for a one-off test, edit the kernel line at
the boot prompt (press `Tab` on BIOS / `e` on UEFI) and remove
`hifi.installer=1`, or just pick "Try Osmium Sound" from the menu.

## Audio output

The output device is chosen in Settings (or the setup wizard) and persisted by
`api_server.py`'s `set_audio_device` as a stable ALSA card name
(`hw:CARD=<id>,DEV=<n>`) in `/etc/default/squeezelite`, so the choice survives
reboots and USB re-enumeration. For a hand edit on the installed system: set
`-o hw:DAC` (find the name with `aplay -l`) in `/etc/default/squeezelite`, then
`systemctl restart squeezelite`. squeezelite runs with `-D` (DSD over DoP) and a
persistent per-device player MAC (`apply.d/0042`).

## Customisation map

| Want to change | Edit |
|---|---|
| Packages installed | `config/package-lists/hifi.list.chroot` |
| Plymouth splash logo/text | logo (repo-root `logo osmium.png`) copied / generated in `build-distro.sh`; theme in `config/includes.chroot/usr/share/plymouth/themes/hifi/` |
| ISO installer boot splash | generated in `build-distro.sh` → `config/includes.binary/{isolinux,boot/grub}/splash.png` |
| ISO boot menu colours/title/timeout | patched in place by `config/hooks/normal/0500-brand-boot.hook.binary` |
| GRUB / kernel quiet flags | `config/hooks/normal/0200-hidden-boot.hook.chroot` → `hifi-finalize-boot.sh` |
| Kiosk session (Wayland) | `os-update/files/kiosk-wayland-session`, `kiosk-wayland-launch`, `hifi-kiosk-wayland.desktop` — single source of truth, injected by `build-distro.sh` **and** shipped by `apply.d/0049` |
| Kiosk session (X11 fallback) / launch flags | `os-update/files/xsession` (same rule) |
| Wayland-vs-X11 decision | `os-update/files/kiosk-session-select` + `hifi-kiosk-session.service` (`apply.d/0050`) |
| Autologin user/session | `config/includes.chroot/etc/lightdm/lightdm.conf.d/99-hifi-autologin.conf` |
| squeezelite args (incl. `-v`) | `config/includes.chroot/etc/default/squeezelite` |
| Enabled/disabled services | `config/hooks/normal/0400-enable-services.hook.chroot` |
| `hifi` user, groups, hostname | `config/hooks/normal/0100-system-setup.hook.chroot` |
| Electron app finalisation (`/opt/hifi-media-player`, chrome-sandbox) | `config/hooks/normal/0300-app-install.hook.chroot` |
| sudo rules for the kiosk user | `config/includes.chroot/etc/sudoers.d/hifi` (pinned commands, no wildcards) |
| Helper scripts run as root by the services | `config/includes.chroot/usr/local/sbin/` |

Python daemons are injected into `includes.chroot/usr/local/bin` by
`build-distro.sh` from the repo root (`api_server.py`, `sources_server.py`,
`webui_server.py`, `vu_meter_daemon.py`, `hifi_backup.py`, `hifi_i18n.py`,
`hifi_logging.py`); the same files ship in the **system** OTA bundle.

## Over-the-air updates

Installed devices never need the ISO again: four OTA channels (UI, System, OS,
Lyrion) are served from GitHub Releases and applied by the scripts in
`config/includes.chroot/usr/local/sbin/` (`hifi-ota-update.sh`,
`hifi-system-update.sh`, `hifi-os-update.sh`, `hifi-lyrion-update.sh`), driven
by `api_server.py`. The combined "Update now" stages everything live and
applies it in an isolated `system-update.target` boot. The OS channel is the
cumulative, signed, idempotent `os-update/` payload — see
[`os-update/README.md`](os-update/README.md), [`ota-keys/README.md`](ota-keys/README.md)
and [ARCHITECTURE.md → OTA update system](../ARCHITECTURE.md#ota-update-system).

Publishing an update = pushing a `v*` tag (see
[TAG_CONVENTIONS.md](../.github/workflows/TAG_CONVENTIONS.md)). For heavy dev
iteration the Release also carries `hifi-install-<ver>.sh`
(`dev-installer/install.sh.tmpl`), an offline installer that applies the same
bundles over SSH without touching the rate-limited GitHub REST API.

**UI rollback**: `hifi-ota-update.sh` keeps the previous app dir aside as
`/opt/hifi-media-player.old` (atomic swap). To go back:

```bash
sudo systemctl stop lightdm
sudo rm -rf /opt/hifi-media-player && sudo mv /opt/hifi-media-player.old /opt/hifi-media-player
sudo chmod 4755 /opt/hifi-media-player/chrome-sandbox
sudo systemctl start lightdm
```

## Troubleshooting

- **VU meter flat / not moving** → confirm `/dev/shm/squeezelite-*` exists while
  playing. If not, check squeezelite is started with `-v` (`/etc/default/squeezelite`).
- **Black screen after install (kiosk never appears)** → `systemctl status
  lightdm hifi-kiosk-session`; in a VM (VMware/VirtualBox/QEMU) the selector
  must have picked X11 — force it with `echo x11 >
  /etc/hifi-player/kiosk-session` and reboot. X11 session errors are in
  `/home/hifi/.xsession-errors`; the Wayland session logs to the journal
  (`journalctl -b _COMM=labwc`).
- **Lyrion not reachable** → `systemctl status lyrionmusicserver` (and
  `hifi-firstboot` if it was never installed: it needs network on first boot);
  first start initialises under `/var/lib/squeezeboxserver` and can take a
  minute.
- **CD Player: "No CD in drive (-1)"** with a CD inserted → the Lyrion user
  can't access the drive. The image includes `cdparanoia`/`libcdio-utils`/
  `icedax`, a udev rule (`/dev/cdrom`, group `cdrom`) and first boot adds the
  Lyrion user to `cdrom`. Check with `cdparanoia -Q -d /dev/sr0` and
  `ls -l /dev/sr0`; if needed `sudo usermod -aG cdrom squeezeboxserver && sudo
  systemctl restart lyrionmusicserver`.
- **GRUB menu still shows briefly** → the installed system hides GRUB entirely:
  `GRUB_TIMEOUT=0` + `GRUB_TIMEOUT_STYLE=hidden`, a black `gfxterm` background
  (`/boot/grub/hifi-bg.png`), and `hifi-finalize-boot.sh` blanks the
  "Loading Linux …/initial ramdisk …" strings in `/etc/grub.d/10_linux` so no
  text appears at all. Hold `Shift` (BIOS) / press `Esc` (UEFI) to reveal it for
  repair.
- **An update left the box on the Plymouth progress bar in red** → the
  isolated apply failed; on the next boot it reruns from the top (every step is
  idempotent). If SSH was enabled before the update it is available during the
  apply session; otherwise recovery is physical.
