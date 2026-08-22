# 🎵 Osmium Sound — Quick Start

*[Leggi in italiano](GUIDA-RAPIDA.md)*

How to install and start using Osmium Sound on your x86 mini-PC.

## 🚀 Installation

1. **Download the ISO** of the latest release from
   [github.com/adri6412/osmium-sound/releases](https://github.com/adri6412/osmium-sound/releases).
2. **Write the ISO** to an 8&nbsp;GB+ USB stick, using
   [balenaEtcher](https://etcher.balena.io/), Rufus, or `dd`.
3. **Boot the mini-PC from the USB stick.** The screen shows only a QR
   code — no mouse or keyboard is ever needed. Scan it with your phone and
   the rest of the install (choosing the disk, confirming the erase,
   starting it) happens on your phone. The screen mirrors progress
   read-only and reboots on its own when it's done.

> **Disk selection.** You choose which disk to install on from your phone;
> only that disk is erased — nothing is wiped without confirmation.
> Tested on UEFI only so far (BIOS/legacy boot not yet verified with this
> flow).

> **Try it live.** Pick **Try Osmium Sound (no install)** at the boot menu
> to run the kiosk straight from the USB stick — nothing is written to
> disk. If it doesn't log in automatically, use `hifi` / `hifi` at the
> login screen.

**Note:** the ISO is only needed for the initial install. All subsequent
updates (UI, system, OS, Lyrion) arrive automatically via **OTA** from the
Settings screen — no need to reflash anything.

## 🧙 First boot

On first boot after install, the screen again shows only a QR code. Scan it
with your phone to run the **guided setup**, entirely from the phone: pick
a language, optionally restore a previous backup instead of starting fresh,
connect to your network, choose the device mode (with screen, headless, or
server-only — see below), pick the audio output, set up Lyrion Music Server
(local or point at one already on your network), add music sources, and set
the time zone. Once you finish on the phone, the device picks up on its own
— no button to press on the screen. From then on, the app opens straight to
the main screen (or stays headless, per what you chose).

> **If you connect via Wi-Fi**, the setup hotspot turns off the moment the
> device joins your home network (a single Wi-Fi radio can't run both at
> once) — reconnect your phone to your own Wi-Fi and open
> `https://hifiplayer.local` to pick the rest of setup back up. A wired
> connection has no such interruption: the hotspot stays up the whole time.

## 🎮 How to use it

- **Music / Radio / Apps**: the interface for Lyrion Music Server — local
  library, internet radio, and streaming services (Deezer, Qobuz, TIDAL,
  Spotify, and others) via **Lyrion plugins**. Install the plugin you need
  from Lyrion's web UI (Settings → Plugins): it shows up on its own in the
  Radio/Apps tabs, no app update needed.
- **Settings**: system and network info, DAC/audio output selection,
  optional DSP (EQ, crossfeed, room correction), Multiroom, OTA updates
  (Dev/Prod channel), Android companion app pairing.

## 📱 Android companion app

Control Osmium Sound from your phone — browse the library, manage playback
and queue, adjust volume. Pair by scanning the QR code from Settings on the
device. Distributed as a signed APK or via our self-hosted F-Droid repo —
not on the Play Store. Details at
[osmiumsound.qd.je](https://osmiumsound.qd.je/#android).

## 🔧 Common issues

- **Lyrion front-end won't load**: check the Lyrion server URL in Settings
  (default `http://localhost:9000`) and that the service is running.
- **Missing streaming/radio sources**: install the corresponding plugin from
  Lyrion's web UI.
- **No audio**: check the selected audio device in Settings and that the
  DAC is recognized.

## 🖥️ Device mode, headless & web administration

Osmium Sound can run **with a screen** (touchscreen kiosk), **headless** (no
screen, managed from a browser or the companion app), or **server-only**
(no screen *and* the player itself never plays audio locally — for a unit
whose only job is serving Lyrion Music Server to other Osmium players
elsewhere in the house).

**First boot (fresh install or a device redone via factory reset):**
1. The device raises a Wi-Fi hotspot **`Osmium-Setup-XXXX`** (WPA2, passphrase
   `osmiumsetup`). Connect your phone to it — the setup page opens automatically
   (captive portal). If it doesn't, open **http://10.42.0.1**.
2. Walk through the setup page on your phone: language, restore-from-backup
   or start fresh, your home Wi-Fi (or wired), device mode (**with screen** /
   **headless** / **server-only**), audio output, Lyrion (local or an
   existing server on your network), music sources, and time zone.
3. Press *Complete setup*. The setup hotspot drops; reconnect your phone to
   your home network and open **https://hifiplayer.local** to create the web
   admin account (username + password). Your browser will warn that the
   certificate is "not trusted" — that is expected on a local device (there
   is no public certificate authority); the connection is still encrypted.
   Accept and continue.

**Restoring instead of starting fresh:** on that same setup page, upload a
previous backup file (and its passphrase, if encrypted) instead of walking
through the steps — network, audio, Lyrion, sources and time zone are all
restored from it, and the device reboots to apply them.

**Managing a headless or server-only device:** open **https://hifiplayer.local**
(web admin — network, audio, updates, display mode, player on/off, account,
factory reset), the **companion app**, or the Lyrion library at
**http://hifiplayer.local:9000**.

**Switching modes later:** Settings → *Display mode* (screen ⇄ headless) and
Settings → *Player* (on ⇄ off, for server-only) — on-screen if you have one,
or from the web admin/companion app if you don't. This is the way to bring
the screen back on a headless unit.

**Factory reset:** Settings → *Factory reset* (on screen), or the web admin
(with your password). It erases all settings **and the web admin account**, then
reboots back into this same QR-code setup flow.

## 📚 More resources

- **[README.md](README.md)**: overview, features, and specs
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: technical details, API, local dev setup
- Release notes: [changelog on the website](https://osmiumsound.qd.je/#changelog)

---

**Enjoy Osmium Sound! 🎶**
