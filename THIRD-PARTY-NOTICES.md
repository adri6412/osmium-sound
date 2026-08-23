# Third-Party Notices

<!-- Also rendered in-app (Settings → Third-Party Notices) from src/data/thirdPartyNotices.js.
     Keep that file in sync whenever a dependency is added, removed or changed here. -->

Osmium Sound includes and/or redistributes the following third-party components under their respective licenses. **The AGPL-3.0-only license of this project applies ONLY to the project's own code** (Electron/React kiosk, Vue web admin, Python services, distro packaging scripts, Osmium Flasher, the "Osmium" theme/CSS for Material Skin) — with the exception of the Android companion app, which remains Apache-2.0 (see below), and of code published before 2026-08-23, which was released under MIT (see `LICENSING.md`). All third-party components are subject to their own licenses.

**Osmium Sound is an independent project and is NOT affiliated with, sponsored by, or endorsed by the Lyrion / LMS-Community project.**

---

## Bundled in the Appliance ISO (`distro/`)

| Component | Version | License | Notes |
|-----------|---------|---------|-------|
| **Lyrion Music Server** | 9.1.0 (pinned in `hifi-firstboot.sh` / `build-distro.sh`) | GPL-2.0+ (with Perl/other) | **Not bundled as a file in the ISO.** Downloaded from the official LMS-Community server and installed on the first boot of the installed system (`hifi-firstboot.service`), or by the setup wizard; later updated in place from Settings. [Official source](https://downloads.lms-community.org/LyrionMusicServer_v9.1.0/) |
| **squeezelite** | Debian trixie | GPL-3.0+ | Audio playback engine (Debian package). Installed from official Debian repos. |
| **cdparanoia, icedax, libcdio-utils, cd-discid, flac, lame, faad, sox, wavpack, ffmpeg** | Debian trixie | GPL-2.0 / GPL-3.0 / LGPL (per package) | CD reading/ripping and codec support (Debian packages). Installed from official Debian repos. |
| **labwc, wlroots, wlr-randr, XWayland, Xorg, LightDM, Plymouth** | Debian trixie | MIT / GPL / X11 (per package) | Kiosk session (Wayland compositor with X11 fallback), display manager, boot splash (Debian packages). |
| **NetworkManager, dnsmasq-base, Avahi, Samba, wsdd2, Tailscale** | Debian trixie / Tailscale repo | GPL / LGPL / BSD (per package) | Networking, setup hotspot, mDNS, SMB shares and their discovery, optional remote access (Tailscale is installed from Tailscale's own repository). |
| **Debian base system, kernel, firmware** | trixie (Debian 13) | Various (GPL/BSD/firmware EULAs) | Installed from official Debian repos. |

### GPL Source Code Offer

The above GPL-licensed components (Lyrion, squeezelite, CD tools, …) are unmodified binaries from official Debian and LMS-Community sources. The corresponding source code is available from:

- **Lyrion 9.1.0**: [LMS-Community GitHub](https://github.com/LMS-Community/slimserver/releases/tag/v9.1.0)
- **Debian packages**: [Debian source repositories](https://deb.debian.org/debian-source/), suite `trixie`

A complete source code archive matching this ISO can be provided upon written request to `info@osmiumsound.it`.

**Historical note:** install ISOs **v2.5.7 and earlier** bundled Lyrion 9.1.0 directly as a file in the image, rather than downloading it at first boot (the model described above, used from v2.6.0-era images onward). Earlier images were built on Debian 12 "bookworm"; current images are built on Debian 13 "trixie". The source offer above covers those older ISOs too.

---

## Android Companion App (`android-companion/`)

| Component | License | Copyright | Notes |
|-----------|---------|-----------|-------|
| **android-squeezer (rebranded)** | Apache-2.0 | Kurt Aaholst, Google Inc. | Rebranded as "Osmium Sound Companion" for remote control. Upstream: [android-squeezer GitHub](https://github.com/kaaholst/android-squeezer). Full license text in `android-companion/docs/LICENSE.md`. |
| **OkHttp** | Apache-2.0 | Square, Inc. | HTTP client. [square/okhttp](https://square.github.io/okhttp/) |
| **ZXing Android Embedded** | Apache-2.0 | journeyapps / ZXing | QR code pairing scanner. [journeyapps/zxing-android-embedded](https://github.com/journeyapps/zxing-android-embedded) |
| **CometD Java Client** | Apache-2.0 | CometD project | Comet/Bayeux client used for LMS server push notifications. [cometd/cometd](https://github.com/cometd/cometd) |
| **SLF4J Android** | MIT | QOS.ch | Logging facade binding. [slf4j.org](https://www.slf4j.org/) |
| **ckChangeLog** | Apache-2.0 | cketti | In-app changelog display. [cketti/ckChangeLog](https://github.com/cketti/ckChangeLog) |
| **RecyclerView-FastScroller** | Apache-2.0 | quiph | Fast-scroll UI widget. [quiph/RecyclerView-FastScroller](https://github.com/quiph/RecyclerView-FastScroller) |
| **AndroidX libraries & Material Components** | Apache-2.0 | Google / AOSP | `core`, `palette`, `webkit`, `appcompat`, `activity`, `preference`, `media`, `material`. [developer.android.com/jetpack/androidx](https://developer.android.com/jetpack/androidx) |

---

## Desktop Application Runtime Dependencies (npm)

All npm dependencies bundled in the Electron kiosk build are permissive open source licenses:

- **React, react-dom** (MIT)
- **react-use-websocket** (MIT)
- **qrcode.react** (MIT)
- **framer-motion** (MIT)
- **lucide-react** (ISC)
- **simple-keyboard** (MIT)
- **Electron** (MIT)

For a complete list with versions, see `package.json` and `package-lock.json`.

### Web admin (`admin-webui/`, served by `webui_server.py`)

- **Vue 3, vue-router** (MIT)
- **qrcode** (MIT)

See `admin-webui/package.json`.

### Osmium Flasher (`flasher/`, desktop USB writer — not part of the appliance)

- **Electron** (MIT)
- **etcher-sdk** (Apache-2.0, balena) — drive enumeration, unmount/locking, block-device writes
- **@vscode/sudo-prompt** (MIT) — privilege elevation for the writer helper
- **file-type** (MIT) — vendored compatibility shim in `flasher/vendor/file-type-compat`
- **usb, follow-redirects** (MIT) — pinned transitive dependencies

See `flasher/package.json`.

---

## Python Service Dependencies

All Python dependencies are permissive open source:

- **Flask** (BSD-3-Clause) — web framework for the API, sources and web-admin servers
- **Werkzeug** (BSD-3-Clause, ships with Flask) — password hashing for the web-admin account
- **flask-cors** (MIT) — cross-origin request support
- **psutil** (BSD-3-Clause) — system monitoring / CPU stats
- **websockets** (BSD-3-Clause) — VU meter WebSocket stream
- **PyYAML, NumPy** (MIT / BSD-3-Clause) — Debian packages used by the on-device services

For a complete list, see `requirements.txt` and `distro/config/package-lists/hifi.list.chroot`.

---

## Not Bundled (Runtime Interaction Only)

- **Lyrion Material Skin** (GPL-3.0, Craig Drummond) — the Lyrion web player. It is **not redistributed** by this project: the appliance downloads it at runtime from the LMS community plugin repository and installs it into Lyrion the same way Lyrion installs any plugin. The "Osmium" theme, global CSS and menu entry (`distro/config/includes.chroot/usr/local/share/hifi-lms-skin/`) are this project's own files (AGPL-3.0-only) placed into Material's documented user-customisation hooks.
- **Lyrion plugins** (various licenses: Spotty, TIDAL, Qobuz, Deezer, RadioNowPlaying, Radio.net, MusicArtistInfo, ShairTunes2, UPnP/DLNA, …) — installed on demand from the setup wizard or the Lyrion web UI and NOT bundled.
- **MusicBrainz** web service — queried at runtime for CD metadata; data under MusicBrainz's own terms.

---

## Disclaimer of Affiliation

Osmium Sound is an **independent open-source project** developed to provide a touchscreen-friendly interface for the Lyrion Music Server. It is not affiliated with, sponsored by, endorsed by, or officially associated with the Lyrion project, the LMS-Community, or their contributors. The name "Lyrion" is used in a nominative sense only to describe the service that this frontend connects to.

---

**For license compliance questions or to request source code, please contact:** `info@osmiumsound.it`

---

**Last reviewed:** 2026-08-23 (full transitive npm scan with license-checker for the AGPL relicensing), against `package.json`, `admin-webui/package.json`, `flasher/package.json`, `requirements.txt`, `distro/config/package-lists/hifi.list.chroot` and `android-companion/HiFiMediaPlayer/build.gradle`.
