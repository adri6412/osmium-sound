<div align="center">

<img src="logo%20osmium.png" alt="Osmium Sound" width="96" />

# Osmium Sound

**A touchscreen-first hi-fi media appliance for x86, built on Debian.**
Bit-perfect audio, streaming services, and signed OTA updates — one sleek dark interface.

![UI](https://img.shields.io/badge/UI-Qt%206%20%2F%20QML-41cd52)
![License](https://img.shields.io/badge/license-AGPL--3.0-green)
![Node](https://img.shields.io/badge/node-20%2B-brightgreen)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://osmiumsound.it/kofi?from=github)

[**🌐 Website**](https://osmiumsound.it) · [**⬇️ Download**](https://github.com/adri6412/osmium-sound/releases) · [**📱 Android companion**](https://github.com/adri6412/osmium-sound/releases?q=companion) · [**📖 Architecture**](ARCHITECTURE.md)

<img src="website/01.png" alt="Osmium Sound — Now Playing" width="640" />

</div>

---

## ✨ Features

- 🎵 **High-resolution audio** — FLAC, DSD (DoP), PCM up to 192kHz, bit-perfect (no resampling)
- 🎧 **Streaming services** — Deezer, Qobuz, TIDAL, Spotify and more, via Lyrion plugins
- 📁 **Music library** — browse by artist, album, folder or playlist, fast indexing
- 💾 **Music sources** — USB drives, internal disks (adopt or format from the UI), NAS/SMB shares found for you on the network; adopted disks can be shared back on the LAN over SMB, and a file manager in the web admin copies, moves and renames what's on them
- 💿 **CD playback & ripping** — insert a disc, play it or rip it to tagged FLAC (MusicBrainz metadata + cover art) straight into your library
- 🧭 **Discover** — endless random mixes, "keep playing similar music", similar artists and artist bios on the touchscreen
- 📻 **Internet radio** — thousands of stations, save favourites from the touchscreen
- 🎚️ **Analog VU meters** — six built-in looks, more downloadable from a signed online catalogue, plus a status plate showing Hi-Res/PCM/DSD and BitPerfect/ReplayGain
- 🔀 **Any player, one screen** — drive the other players on the same Lyrion from the touchscreen, then come back to this one
- 🖥️ **With screen or headless** — touchscreen kiosk, headless (web admin + companion app), or server-only (serves Lyrion to other players, plays nothing itself)
- 🌐 **Web admin** — manage a unit from any browser on the LAN (network, audio, sources, updates, backups, SSH, Tailscale remote access)
- 📱 **Android companion app** — browse, control playback/queue, adjust volume, pair by QR code, the web admin's settings, turn the device off; the phone can also be a player itself
- 💼 **Backup & restore** — profile backups (settings, sources, Lyrion prefs, optionally Wi-Fi/accounts encrypted), scheduled or on demand, restorable even from the first-boot wizard
- 🛡️ **Read-only system, A/B updates** — the OS is a signed image in one of two slots; an update is written to the other one and a device that doesn't come up healthy rolls back on its own. Older installs convert over the air, no reinstall
- ⬆️ **Signed OTA updates** — signed image bundles (RAUC) and Ed25519-signed OS payloads, Prod / Dev release channels (plus a private Alpha channel for testers)
- 🧩 **Add-ons** — `apt install` over SSH still works on the read-only image: extra packages become system extensions that survive updates

## 📋 Specs

| | |
|---|---|
| **Hardware** | x86-64 mini-PC (Intel iGPU-class graphics is plenty) |
| **Display** | 1024×600 touchscreen (optimized for this resolution); headless operation also supported |
| **OS** | Custom Debian 13 ("trixie") appliance image built with live-build: a ~850 MiB read-only squashfs in A/B slots, settings and music on a separate data partition |
| **Interface** | Native Qt 6 / QML app drawing straight to the display over DRM/KMS (no X server, no compositor) — about 3.3 W and 175 MB on Now Playing with the VU meters, against 4.9 W and 650 MB for the previous Electron kiosk; a Vue web admin for any browser on the LAN |
| **Media server** | Lyrion Music Server (installed by the setup wizard when this device is the server, or an existing one on the LAN), web player on Material Skin with the "Osmium" theme |
| **Audio formats** | FLAC, DSD (64/128/256), MP3, AAC, WAV, AIFF |
| **Max resolution** | 32-bit / 192kHz PCM |
| **Output** | USB DAC, HDMI |
| **Update system** | Whole-image A/B updates with automatic rollback (RAUC, signed), streamed straight into the spare slot; Prod/Dev channels |
| **License** | AGPL-3.0 (app code), commercial licenses available — see [Licensing](#-licensing) |

## 🚀 Get started

1. **Download** the latest install ISO from [Releases](https://github.com/adri6412/osmium-sound/releases) (or use **Osmium Flasher**, see `flasher/`, which downloads and verifies the current image for you).
2. **Flash** it to an 8GB+ USB stick with [Osmium Flasher](https://osmiumsound.it), [balenaEtcher](https://etcher.balena.io/), Rufus, or `dd`.
3. **Boot** your x86 mini-PC from the stick and finish the install from there: pick the disk, confirm, done.
4. On first boot after install, pick your Wi-Fi on the screen (or just plug in a cable); the screen then shows its own address (`http://<ip>`). Open it on your phone or laptop to finish setup: language, restore-from-backup or fresh start, any required update, device name and mode, audio output, Lyrion (this device, or a server already on your network), web-player look, music services, web-admin account, time zone, music sources.

Every later version — the system image and Lyrion — arrives over the air from the Settings screen (or the web admin, or the companion). It is written to the spare slot while the device keeps playing, and the reboot switches over; if the new version doesn't come up healthy, the device goes back to the previous one by itself. No reflashing required.

> **Try it live.** Pick **Try Osmium Sound (no install)** at the boot menu to run the interface straight from the USB stick, nothing is written to disk.

## 📱 Android companion

Control Osmium Sound from your phone — browse the library, drive playback and the queue, adjust volume, and reach the same settings as the web admin (audio output, music sources, Lyrion, playback and VU meters, display, updates, backups, system), or turn the device off from the top bar. The phone can also play music itself, as one more player in the house, and connect to any Lyrion server, not only an Osmium device. Pair in seconds by scanning the QR code on the device's Settings screen. Distributed as a signed APK or via our self-hosted F-Droid repo (not on the Play Store) — see the [website](https://osmiumsound.it/#android) and [COMPANION_APP.md](COMPANION_APP.md).

## 📖 Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — components, ports, backend API reference, provisioning flow, OTA internals, project layout, local dev setup
- **[QUICKSTART.md](QUICKSTART.md)** — quick start guide (also in [Italian](GUIDA-RAPIDA.md))
- **[User manual](https://osmiumsound.it/manual.html)** — full installation & configuration manual on the website (English/Italian)
- **[COMPANION_APP.md](COMPANION_APP.md)** — the Android companion app
- **[distro/README.md](distro/README.md)** — building the appliance ISO; **[flasher/README.md](flasher/README.md)** — the desktop USB flasher
- **[.github/workflows/README.md](.github/workflows/README.md)** — CI: release, OTA, ISO, companion and website workflows; **[TAG_CONVENTIONS.md](.github/workflows/TAG_CONVENTIONS.md)** — tags, branches and release channels
- **[SECURITY.md](SECURITY.md)** — security policy and the appliance's security model
- Release notes ship with every GitHub Release (auto-generated `CHANGELOG_RELEASE.md`, also shown as "what's new" in the Updates screens)

## 📄 Licensing

**The application code authored by this project** (the Qt/QML on-screen interface, the earlier Electron/React kiosk, Vue web admin, Python services, distro packaging, flasher, hardware designs) is released under the **GNU Affero General Public License v3.0 only (AGPL-3.0-only)** — see [`LICENSE`](LICENSE). The project is **dual-licensed**: if the AGPL doesn't fit your use case (e.g. a commercial product or service that can't publish its source), commercial licenses are available — write to **info@osmiumsound.it**. See [`LICENSING.md`](LICENSING.md) for details.

**Exception:** the Android companion app (`android-companion/`) remains under **Apache-2.0**, as it is a rebranded derivative of [android-squeezer](https://github.com/kaaholst/android-squeezer).

**Historical note:** code published by this project **before 2026-08-23** (all releases up to that date) was released under the MIT License and remains available under those terms; the AGPL-3.0 applies from this change onward.

**This project also includes and redistributes third-party components** under their own licenses (Lyrion Music Server and squeezelite under GPL, the Qt 6 libraries under LGPL-3.0, npm/Python dependencies under MIT/BSD/ISC/Apache-2.0). See [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) for the complete list, license texts, and source locations.

**Disclaimer of affiliation:** Osmium Sound is an independent open-source project and is **NOT affiliated with, sponsored by, endorsed by, or officially associated with** the Lyrion Music Server project or the LMS-Community. "Lyrion" is used in a nominative sense only, to describe the service this frontend connects to.

## 🤝 Contributing & support

Contributions are welcome — pull requests and issues are open on [GitHub](https://github.com/adri6412/osmium-sound). First-time contributors are asked to sign the project's [Contributor License Agreement](CLA.md) (a bot guides you through it on your first PR) — see [CONTRIBUTING.md](CONTRIBUTING.md). For questions, open an issue, write to support@osmiumsound.it, or check the docs above.

If Osmium Sound is useful to you, you can support its development on Ko-fi:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://osmiumsound.it/kofi?from=github)

---

<div align="center">

**Built with ❤️ for music lovers**

</div>
