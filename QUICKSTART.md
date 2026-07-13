# 🎵 Osmium Sound — Quick Start

*[Leggi in italiano](GUIDA-RAPIDA.md)*

How to install and start using Osmium Sound on your x86 mini-PC.

## 🚀 Installation

1. **Download the ISO** of the latest release from
   [github.com/adri6412/osmium-sound/releases](https://github.com/adri6412/osmium-sound/releases).
2. **Write the ISO** to an 8&nbsp;GB+ USB stick, using
   [balenaEtcher](https://etcher.balena.io/), Rufus, or `dd`.
3. **Boot the mini-PC from the USB stick** and follow the on-screen guided
   installer. On reboot, the appliance is ready.

> ⚠️ **Unattended install — automatically wipes a disk.**
> The ISO asks no questions and requests no confirmation: it picks the
> **first disk it detects**, wipes it entirely (new GPT, all partitions and
> data lost), and reboots on its own. Only use it on a machine with no data
> to keep, and unplug any disk you don't want touched beforehand.

**Note:** the ISO is only needed for the initial install. All subsequent
updates (UI, system, OS, Lyrion) arrive automatically via **OTA** from the
Settings screen — no need to reflash anything.

## 🧙 First boot

On first boot, the **guided setup wizard** runs: network, music library,
DAC/audio output, and (if missing) automatic installation of Lyrion Music
Server. From then on, the app opens straight to the main screen.

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
- **Touch screen not responding**: recalibrate the touch screen from the
  appliance's system Settings.
- **No audio**: check the selected audio device in Settings and that the
  DAC is recognized.

## 📚 More resources

- **[README.md](README.md)**: overview, features, and specs
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: technical details, API, local dev setup
- Release notes: [changelog on the website](https://osmiumsound.qd.je/#changelog)

---

**Enjoy Osmium Sound! 🎶**
