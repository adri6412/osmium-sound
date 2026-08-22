# 🎵 Osmium Sound — Quick Start

*[Leggi in italiano](GUIDA-RAPIDA.md)*

How to install and start using Osmium Sound on your x86 mini-PC.

## 🚀 Installation

1. **Get the installer image.** Either download the latest ISO from
   [github.com/adri6412/osmium-sound/releases](https://github.com/adri6412/osmium-sound/releases)
   and write it to an 8&nbsp;GB+ USB stick with [balenaEtcher](https://etcher.balena.io/),
   Rufus or `dd`, or use **Osmium Flasher** (Windows/Linux desktop app, see
   [`flasher/`](flasher/README.md)): it fetches the current image, verifies its
   signature and writes the stick for you.
2. **Boot the mini-PC from the USB stick.** The screen shows only a QR
   code — no mouse or keyboard is ever needed. Scan it with your phone: the
   phone joins the box's open `Osmium-Setup-XXXX` Wi-Fi hotspot (no password)
   and the install page opens on its own (captive portal; if it doesn't, open
   `http://10.42.0.1`). If the box is on Ethernet you can simply open its LAN
   address instead — the QR shows it.
3. **Finish from the phone**: pick the target disk, confirm the erase,
   start. The screen mirrors progress read-only and reboots on its own when
   done.

> **Disk selection.** You choose which disk to install on from your phone;
> only that disk is erased — nothing is wiped without confirmation. The
> installer sets up GRUB for the firmware mode the machine booted in (UEFI is
> the tested, recommended path; legacy BIOS is supported but less exercised).

> **Try it live.** Pick **Try Osmium Sound (no install)** at the boot menu
> to run the kiosk straight from the USB stick — nothing is written to
> disk. If it doesn't log in automatically, use `hifi` / `hifi` at the
> login screen.

**Note:** the ISO is only needed for the initial install. All subsequent
updates (UI, system, OS, Lyrion) arrive automatically via **OTA** from the
Settings screen or the web admin — no need to reflash anything.

## 🧙 First boot

On first boot after install, the screen asks for one thing only: the
**network**. Pick your Wi-Fi on the touchscreen and type the password; with an
Ethernet cable there is nothing to do. The screen then shows the box's own
address (`http://<ip>`) — open it on your phone or laptop and run the
**guided setup** from the browser, in this order:

1. **Language** (English by default, Italian available).
2. **Restore from a backup, or start fresh.** Uploading a previous backup file
   (and its passphrase, if encrypted) restores network, audio, Lyrion, sources
   and time zone in one go; the device reboots to apply it and the remaining
   steps are skipped.
3. **Network** — already done from the screen in most cases; the step is there
   if you want to move a wired box onto Wi-Fi.
4. **Updates** — a mandatory update check, so the wizard itself runs on the
   newest software (this can reboot the box once; the wizard picks itself back
   up).
5. **Device name** (`<name>.local`, also the multiroom name).
6. **Device mode** — *with screen*, *headless*, or *server-only* (see below).
7. **Mouse pointer** on/off (screen mode only), **audio output** (DAC/HDMI).
8. **Lyrion** — run Lyrion Music Server on this box, or point at one already
   on your network (auto-discovered).
9. **Web player look** — the **Osmium** theme or plain **Material**, and the
   **music services** to enable (Spotify, TIDAL, Qobuz, Deezer, radio, …).
10. **Web admin account** (username + password — your credentials for the
    web admin page and, optionally, SSH).
11. **Time zone**, then **music sources** (NAS shares or internal disks,
    optional — a USB drive is picked up automatically).

Once you finish in the browser, the device continues on its own — no button
to press on the screen. From then on the app opens straight to the main
screen (or stays headless, per what you chose).

## 🎮 How to use it

- **Library / Radio / Apps**: the interface for Lyrion Music Server — local
  library, internet radio, Discover (random mixes, similar artists, artist
  bios) and streaming services (Deezer, Qobuz, TIDAL, Spotify, and others)
  via **Lyrion plugins**. Plugins picked during setup are ready to go; others
  can be installed from Lyrion's web UI (Settings → Plugins) and show up on
  their own, no app update needed.
- **Now Playing**: large artwork, transport and volume, optional analog VU
  meter, bit-perfect / ReplayGain indicator.
- **CD**: insert an audio CD to play it, or rip it to tagged FLAC into one of
  your sources.
- **Settings** (on screen): language, Lyrion (server, web-player look,
  rescan), music sources, audio output, playback, multiroom, alarm, network,
  web remote (QR to open the web player on a phone; iPhone notes), SSH,
  pointer, UI resolution, refresh rate, display mode, time zone, system info,
  updates (Prod/Dev channel, "Update now"), system controls (reboot, shutdown,
  factory reset, web-admin password reset), third-party notices.

## 📱 Android companion app

Control Osmium Sound from your phone — browse the library, manage playback
and queue, adjust volume, switch audio output, manage multiroom, updates and
backups. Pair by scanning the QR code from Settings on the device. Distributed
as a signed APK or via our self-hosted F-Droid repo — not on the Play Store.
Details at [osmiumsound.it](https://osmiumsound.it/#android) and in
[COMPANION_APP.md](COMPANION_APP.md).

## 🔧 Common issues

- **Lyrion front-end won't load**: check the Lyrion server in Settings →
  Lyrion (local, default `http://localhost:9000`, or the external server you
  picked) and that the service is running.
- **Missing streaming/radio sources**: install the corresponding plugin from
  Lyrion's web UI (Settings → Plugins).
- **No audio**: check the selected audio device in Settings → Audio and that
  the DAC is recognized; in server-only mode the player is off by design.
- **Can't reach `hifiplayer.local`**: use the IP address shown in Settings →
  Network (or on the setup screen) — `.local` names are ambiguous with more
  than one unit on the LAN.

## 🖥️ Device mode, headless & web administration

Osmium Sound can run **with a screen** (touchscreen kiosk), **headless** (no
screen, managed from a browser or the companion app), or **server-only**
(no screen *and* the player itself never plays audio locally — for a unit
whose only job is serving Lyrion Music Server to other Osmium players
elsewhere in the house).

**Web admin:** open **http://\<device-ip\>** (or `http://hifiplayer.local`)
from any browser on your LAN and log in with the account created during
setup. It is plain HTTP on the local network — no certificate warning, no
cloud involved. From there: network, audio, sources (NAS/internal disks,
SMB sharing), playback and display settings, Lyrion (web-player look, rescan,
Lyrion updates), updates, backups (on demand, scheduled, encrypted; restore),
SSH (with the Linux login you choose), Tailscale remote access, companion
pairing, account, factory reset, and a Debug card for support.

**Managing a headless or server-only device:** the web admin above, the
**companion app**, or the Lyrion web player at **http://\<device-ip\>:9000**
(the "Osmium Admin" entry in its menu opens the web admin too).

**Switching modes later:** Settings → *Display mode* holds both switches —
screen ⇄ headless, and player on ⇄ off (off = server-only) — on screen if you
have one, or from the web admin/companion app if you don't. This is the way to
bring the screen back on a headless unit.

**Lost network on a configured unit:** if the box can't reach any network any
more, it raises the `Osmium-Setup-XXXX` hotspot again with a network-only
page, so you can join it to a new Wi-Fi from your phone; the hotspot goes away
as soon as the network is back.

**Factory reset:** Settings → *System controls* (on screen), or the web admin
(re-enter your password). It erases all settings **and the web admin
account**, wipes stored backups, then reboots back into the first-boot setup.

## 📚 More resources

- **[README.md](README.md)**: overview, features, and specs
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: technical details, API, local dev setup
- **[User manual](https://osmiumsound.it/manual.html)** on the website
- Release notes: on every [GitHub Release](https://github.com/adri6412/osmium-sound/releases) and in the Updates screen ("what's new")

---

**Enjoy Osmium Sound! 🎶**
