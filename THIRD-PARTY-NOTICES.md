# Third-Party Notices

HiFi Media Player includes and/or redistributes the following third-party components under their respective licenses. **The MIT License of this project applies ONLY to the project's own code** (Electron/React application, Python services, distro packaging scripts). All third-party components are subject to their own licenses.

**HiFi Media Player is an independent project and is NOT affiliated with, sponsored by, or endorsed by the Lyrion / LMS-Community project.**

---

## Bundled in the Appliance ISO (`distro/`)

| Component | Version | License | Notes |
|-----------|---------|---------|-------|
| **Lyrion Music Server** | 9.1.0 (pinned) | GPL-2.0+ (with Perl/other) | Downloaded on-demand and installed in live image. Not bundled as a file in the ISO. Installed at first boot on the deployed system. [Official source](https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/) |
| **squeezelite** | Debian bookworm | GPL-3.0+ | Audio playback engine (Debian package). Installed from official Debian repos. |
| **cdparanoia, icedax, libcdio-utils** | Debian bookworm | GPL-2.0, GPL-3.0 | CD reading support (Debian packages). Installed from official Debian repos. |
| **Debian base system, kernel, firmware** | bookworm | Various (GPL/BSD/firmware EULAs) | Installed from official Debian repos. |

### GPL Source Code Offer

The above GPL-licensed components (Lyrion, squeezelite, CD tools) are unmodified binaries from official Debian and LMS-Community sources. The corresponding source code is available from:

- **Lyrion 9.1.0**: [LMS-Community GitHub](https://github.com/LMS-Community/slimserver/releases/tag/v9.1.0)
- **Debian packages**: [Debian source repositories](https://deb.debian.org/debian-source/), suite `bookworm`

A complete source code archive matching this ISO can be provided upon written request to `frongillo.adriano@gmail.com`.

---

## Android Companion App (`android-companion/`)

| Component | License | Copyright | Notes |
|-----------|---------|-----------|-------|
| **android-squeezer (rebranded)** | Apache-2.0 | Kurt Aaholst, Google Inc. | Rebranded as "HiFi Media Player Companion" for remote control. Upstream: [android-squeezer GitHub](https://github.com/kaaholst/android-squeezer). Full license text in `android-companion/docs/LICENSE.md`. |

---

## Desktop Application Runtime Dependencies (npm)

All npm dependencies bundled in the Electron build are permissive open source licenses:

- **React, react-dom** (MIT)
- **react-router-dom** (MIT)
- **react-use-websocket** (MIT)
- **qrcode.react** (MIT)
- **framer-motion** (MIT)
- **lucide-react** (ISC)
- **simple-keyboard** (MIT)
- **Electron** (MIT)

For a complete list with versions, see `package.json` and `package-lock.json`.

---

## Python Service Dependencies

All Python dependencies are permissive open source:

- **Flask** (BSD-3-Clause) — web framework for API and settings server
- **flask-cors** (MIT) — cross-origin request support
- **psutil** (BSD-3-Clause) — system monitoring for VU meter and CPU stats
- **websockets** (BSD-3-Clause) — WebSocket support

For a complete list, see `requirements.txt`.

---

## Not Bundled (Runtime Interaction Only)

- **Lyrion Material Skin** (GPL-3.0) — served by Lyrion at runtime over HTTP and NOT redistributed by this project.
- **Lyrion Plugins** (various licenses: Spotify Spotty, AirPlay ShairTunes2, UPnP-DLNA) — installed on-demand from the Lyrion web UI and NOT bundled.

---

## Disclaimer of Affiliation

HiFi Media Player is an **independent open-source project** developed to provide a touchscreen-friendly interface for the Lyrion Music Server. It is not affiliated with, sponsored by, endorsed by, or officially associated with the Lyrion project, the LMS-Community, or their contributors. The name "Lyrion" is used in a nominative sense only to describe the service that this frontend connects to.

---

**For license compliance questions or to request source code, please contact:** `frongillo.adriano@gmail.com`
