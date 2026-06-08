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
| squeezelite (Debian, `-v`) | Local player + VU visualizer export | `squeezelite.service` |
| `vu_meter_daemon.py` | Streams VU levels from `/dev/shm/squeezelite-*` | `hifi-vumeter.service` (`:9001`) |
| `api_server.py` | OS control + WiFi setup (reboot/shutdown/update/network) | `hifi-api.service` (`:8000`) |
| `sources_server.py` | Web UI to add music sources (local + SMB) to Lyrion | `hifi-sources.service` (`:8080`) |

## Network audio receivers ("cast" dal telefono)

Il device può apparire in rete come bersaglio audio dalle app del telefono. Si
realizza con i **plugin di Lyrion**, non con servizi di sistema: l'audio passa
per Lyrion/squeezelite, quindi un solo percorso audio e nessuna contesa ALSA.
Si installano una volta dal web di Lyrion → **Settings → Plugins** (il device ha
internet):

| Protocollo | Plugin Lyrion | App sorgente |
|---|---|---|
| **AirPlay** | ShairTunes2 | iPhone/iPad/Mac → icona AirPlay |
| **UPnP/DLNA** | UPnP/DLNA Media Interface | BubbleUPnP & co. (Android) |
| **Spotify Connect** | Spotty | app Spotify (Premium) → dispositivi |

> Un vero ricevitore **Google Cast/Chromecast** non è disponibile: il lato
> ricevitore del protocollo è proprietario e non esiste un'implementazione open
> per l'audio.

## First-run setup wizard

On first boot the Electron UI shows a setup wizard (welcome → network →
sources → done). Network is **always DHCP**; WiFi is scanned and joined via
NetworkManager. The "sources" step shows `http://<device-ip>:8080` (with a QR
code) where the user adds music folders from a phone/PC. The wizard can be
re-run later from **Settings → "Riavvia configurazione guidata"**.

SMB shares are mounted with `cifs-utils` under `/mnt/hifi-sources/<name>` and
written into Lyrion's `mediadirs` (so Lyrion sees them as local folders); the
mount state is re-applied on boot by `hifi-sources.service`.

The VU meter works because the Debian `squeezelite` package is built with
`VISEXPORT` and is launched with `-v` (see
`config/includes.chroot/etc/default/squeezelite`), which exports
`/dev/shm/squeezelite-*` for the VU daemon.

Lyrion Music Server is downloaded by `build-distro.sh` into
`includes.chroot/opt/hifi-lyrion/` and installed during the chroot stage by
`config/hooks/normal/0050-install-lyrion.hook.chroot` (it is **not** placed in
`packages.chroot`, which current apt/live-build rejects).

> **Lyrion on the installed system.** The debian-installer step
> `finish-install.d/14remove-live-packages` (live-installer) runs *after* the
> preseed `late_command` and **purges packages added via chroot hooks**,
> including Lyrion — so a fresh install would boot without it. To survive this,
> the staged `/opt/hifi-lyrion/*.deb` is kept in the image and `hifi-firstboot.service`
> re-installs Lyrion on the **first boot of the real system**, then self-disables
> (and removes the staged `.deb`). It runs only outside the live session
> (`ConditionKernelCommandLine=!boot=live`). If first boot has no network and the
> staged `.deb` is somehow missing, it retries on the next boot.

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

## Aggiornamento OTA della UI

La UI Electron può essere aggiornata **over-the-air** senza reinstallare la ISO.
L'intera cartella `/opt/hifi-media-player` viene sostituita in modo atomico con
backup per rollback.

**Pubblicare un aggiornamento** (manutentore):

1. Aggiorna la `version` in `package.json` e crea un tag, es. `git tag v1.1.0 && git push --tags`.
2. Il workflow `.github/workflows/build-ui-ota.yml` costruisce
   `dist/linux-unpacked`, lo impacchetta in `hifi-ui-<tag>.tar.gz` + `.sha256`
   e li allega alla **Release** del tag.

**Aggiornare un dispositivo** (utente): la UI controlla automaticamente la
disponibilità all'apertura di **Settings → Aggiornamento UI**, mostra la versione
disponibile e — su pressione di **"Aggiorna ora"** — scarica il bundle, ne verifica
lo `sha256`, sostituisce l'app e riavvia l'interfaccia.

Sotto il cofano, `api_server.py` (root) interroga
`https://api.github.com/repos/<owner>/<repo>/releases/latest` (override con la env
`HIFI_OTA_REPO`) e lancia `/usr/local/sbin/hifi-ota-update.sh` via `systemd-run`,
così l'update sopravvive al riavvio di `lightdm`. La versione installata è in
`/opt/hifi-media-player/UI_VERSION` (seminata da `build-distro.sh`, override con
`--app-version`).

### Aggiornamento di Lyrion Music Server

Dalla stessa pagina **Settings → Aggiornamento Lyrion** è possibile aggiornare il
server musicale. La UI rileva la versione installata (`dpkg-query`) e l'ultima
**stable** pubblicata su `https://downloads.lms-community.org/` (le nightly sotto
`/nightly/` sono escluse), e — su **"Aggiorna Lyrion"** — `api_server.py` (root)
lancia `/usr/local/sbin/hifi-lyrion-update.sh` che scarica il `.deb`, lo installa
con `apt-get` (risolve le dipendenze) e riavvia `lyrionmusicserver`. Il controllo
è automatico all'apertura di Settings; l'installazione resta manuale.

**Rollback**: la versione precedente resta in `/opt/hifi-media-player.old`. Per
ripristinarla:

```bash
sudo systemctl stop lightdm
sudo rm -rf /opt/hifi-media-player && sudo mv /opt/hifi-media-player.old /opt/hifi-media-player
sudo chmod 4755 /opt/hifi-media-player/chrome-sandbox
sudo systemctl start lightdm
```

## Troubleshooting

- **VU meter flat / not moving** → confirm `/dev/shm/squeezelite-*` exists while
  playing. If not, check squeezelite is started with `-v` (`/etc/default/squeezelite`).
- **Black screen after install** → check `systemctl status lightdm` and
  `~/.xsession` errors in `/home/hifi/.xserver-errors`.
- **Lyrion not reachable** → `systemctl status lyrionmusicserver`; first start
  initialises under `/var/lib/squeezeboxserver` and can take a minute.
- **GRUB menu still shows briefly** → normal on some firmware; the installed
  system uses `GRUB_TIMEOUT=0` + `hidden`. Hold `Shift` to reveal it for repair.
