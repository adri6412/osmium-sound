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

> **Disk selection.** The installer asks which disk to install on and
> formats only the one you pick — nothing is wiped without confirmation.
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
- **No audio**: check the selected audio device in Settings and that the
  DAC is recognized.

## 🖥️ Headless mode & web administration

Osmium Sound can run **with a screen** (touchscreen kiosk) or **headless** (no
screen, managed from a browser or the companion app).

**First boot (fresh install):**
1. The device raises a Wi-Fi hotspot **`Osmium-Setup-XXXX`** (WPA2, passphrase
   `osmiumsetup`). Connect your phone to it — the setup page opens automatically
   (captive portal). If it doesn't, open **http://10.42.0.1**.
2. Pick your home Wi-Fi and choose **With a screen** or **Headless**. The setup
   hotspot then drops; reconnect your phone to your home network.
3. Open **https://hifiplayer.local** and create the web admin account (username +
   password). Your browser will warn that the certificate is "not trusted" — that
   is expected on a local device (there is no public certificate authority); the
   connection is still encrypted. Accept and continue.

**Managing a headless device:** open **https://hifiplayer.local** (web admin —
network, audio, updates, display mode, account, factory reset), the **companion
app**, or the Lyrion library at **http://hifiplayer.local:9000**.

**Switching modes:** on-screen, go to Settings → *Display mode*. Remotely, use
the companion app (System → *On-screen interface*) — this is the way to bring the
screen back on a headless unit.

**Factory reset:** Settings → *Factory reset* (on screen), or the web admin
(with your password). It erases all settings **and the web admin account**, then
reboots into this setup flow. If you forget the web password, reset it from the
on-screen Settings, or factory reset.

## 📚 More resources

- **[README.md](README.md)**: overview, features, and specs
- **[ARCHITECTURE.md](ARCHITECTURE.md)**: technical details, API, local dev setup
- Release notes: [changelog on the website](https://osmiumsound.qd.je/#changelog)

---

**Enjoy Osmium Sound! 🎶**
