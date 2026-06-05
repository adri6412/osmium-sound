# HiFi Player — Debian Appliance Distro

Builds a self-contained, **installable Debian ISO** that turns any x86 PC into a
commercial-style network streamer running the HiFi Player UI on top of Lyrion
Music Server — with a **completely hidden boot** (no GRUB menu, no kernel text,
branded Plymouth splash) that goes straight into the fullscreen player.

## What the image contains

| Component | Role | Service |
|---|---|---|
| HiFi Player (Electron) | Fullscreen kiosk UI | LightDM autologin → `hifi-kiosk` session |
| Lyrion Music Server `9.1.0` | Music server / library / streaming | `lyrionmusicserver.service` (`:9000`) |
| squeezelite (DietPi build, `-v`) | Local player + VU visualizer export | `squeezelite.service` |
| `vu_meter_daemon.py` | Streams VU levels from `/dev/shm/squeezelite-*` | `hifi-vumeter.service` (`:9001`) |
| `api_server.py` | OS control + WiFi setup (reboot/shutdown/update/network) | `hifi-api.service` (`:8000`) |
| `sources_server.py` | Web UI to add music sources (local + SMB) to Lyrion | `hifi-sources.service` (`:8080`) |

## First-run setup wizard

On first boot the Electron UI shows a setup wizard (welcome → network →
sources → done). Network is **always DHCP**; WiFi is scanned and joined via
NetworkManager. The "sources" step shows `http://<device-ip>:8080` (with a QR
code) where the user adds music folders from a phone/PC. The wizard can be
re-run later from **Settings → "Riavvia configurazione guidata"**.

SMB shares are mounted with `cifs-utils` under `/mnt/hifi-sources/<name>` and
written into Lyrion's `mediadirs` (so Lyrion sees them as local folders); the
mount state is re-applied on boot by `hifi-sources.service`.

The VU meter works because squeezelite is pulled from the **DietPi APT repo**
(`https://dietpi.com/apt`), whose build enables `VISEXPORT` and is launched with
`-v` (see `config/includes.chroot/etc/default/squeezelite`).

## Prerequisites (on the build server)

A Debian **bookworm** machine (or container/VM) with internet access. The build
script installs `live-build`, `imagemagick`, `curl`, `xorriso` itself. You need
~15 GB free disk and root.

> The build server does **not** need Node/npm — the Electron app is consumed
> pre-compiled as an unpacked directory.

## 1. Compile the Electron app (once, anywhere with Node)

Produce the `linux-unpacked` directory with electron-builder, e.g. on the dev
machine / WSL:

```bash
npm install
npm run build
npx electron-builder --linux dir   # → dist/linux-unpacked/
```

Copy `dist/linux-unpacked/` (or the whole repo) to the build server.

## 2. Build the ISO (on the Debian server, as root)

```bash
cd distro
sudo ./build-distro.sh --app-dir /path/to/dist/linux-unpacked
```

If `--app-dir` is omitted the script looks in `../dist/linux-unpacked`,
`../linux-unpacked`, and `~/hifi-build/dist/linux-unpacked`.

Result: **`../hifi-player-installer.iso`** (next to the repo root).

Useful overrides:

```bash
sudo ./build-distro.sh \
  --app-dir ../dist/linux-unpacked \
  --lyrion-url https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/lyrionmusicserver_9.1.0_all.deb \
  --suite bookworm
```

## 3. Install on the target PC

Write the ISO to a USB stick and boot the target:

```bash
sudo dd if=hifi-player-installer.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Pick **Install** from the boot menu. The installation is **fully automatic**
(preseeded — see `config/includes.installer/preseed.cfg`):

- It **clones** the live system, so the `hifi` user, services and app already
  exist → the installer **does not ask for a username/password**, language,
  keyboard or timezone.
- It auto-detects the **first disk** and wipes it (single partition), installs
  GRUB, then reboots — no questions.

> ⚠️ **The installer wipes the first detected disk without confirmation.** Boot
> it only on the target appliance. To require manual disk selection instead,
> remove the `partman/*` confirm lines from `preseed.cfg`.

After reboot the machine boots **silently** straight into the fullscreen player:
no desktop, no login screen, no visible GRUB.

Default credentials (for SSH/maintenance): user `hifi` / password `hifi`.

### Choosing automatic vs interactive install

The boot menu entry passes `auto=true priority=critical preseed/file=/preseed.cfg`
(set in `build-distro.sh` via `--bootappend-install`). For a one-off interactive
install, edit that line at the boot prompt (press `Tab`/`e`) and remove the
`auto=true priority=critical preseed/file=...` part.

## Audio output

The default squeezelite device is ALSA `default`. For a dedicated USB DAC, edit
`/etc/default/squeezelite` on the installed system, set e.g. `-o hw:DAC` (find
the name with `aplay -l`), then `systemctl restart squeezelite`.

## Customisation map

| Want to change | Edit |
|---|---|
| Packages installed | `config/package-lists/hifi.list.chroot` |
| Boot splash logo/text | logo generated in `build-distro.sh`; theme in `config/.../plymouth/themes/hifi/` |
| GRUB / kernel quiet flags | `config/hooks/normal/0200-hidden-boot.hook.chroot` |
| Kiosk launch flags | `.xsession` written by `config/hooks/normal/0100-system-setup.hook.chroot` |
| Autologin user/session | `config/includes.chroot/etc/lightdm/lightdm.conf.d/99-hifi-autologin.conf` |
| squeezelite args (incl. `-v`) | `config/includes.chroot/etc/default/squeezelite` |

## Troubleshooting

- **VU meter flat / not moving** → confirm `/dev/shm/squeezelite-*` exists while
  playing. If not, squeezelite lacks `VISEXPORT` or isn't started with `-v`.
  Verify the DietPi APT repo was reachable during the build.
- **Black screen after install** → check `systemctl status lightdm` and
  `~/.xsession` errors in `/home/hifi/.xserver-errors`.
- **Lyrion not reachable** → `systemctl status lyrionmusicserver`; first start
  initialises under `/var/lib/squeezeboxserver` and can take a minute.
- **GRUB menu still shows briefly** → normal on some firmware; the installed
  system uses `GRUB_TIMEOUT=0` + `hidden`. Hold `Shift` to reveal it for repair.
