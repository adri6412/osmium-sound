# Osmium Sound — Android Companion App

## Overview

The **Osmium Sound Companion** is the official Android app for remote control
of an Osmium Sound appliance — browse the library, drive playback and the
queue, adjust volume, and (once paired) manage the appliance itself: audio
output, multiroom, updates, backups, display mode and a few system actions,
all from the phone.

## Location

The companion app source lives in [`android-companion/`](android-companion/):

```
hifi-media-player/
├── android-companion/            # Android Companion App
│   ├── HiFiMediaPlayer/          # Main app module (Java 17)
│   │   ├── src/main/java/com/osmium/sound/companion/
│   │   └── src/main/res/         # Resources, layouts, strings (10 languages), themes
│   ├── README.md                 # Quick start guide
│   ├── DESIGN_GUIDELINES.md      # UI/UX design specifications
│   ├── BUILD_INSTRUCTIONS.md     # Build and deployment guide
│   └── RELEASE_PROCESS.md        # How releases are tagged and published
├── fdroid/                       # Self-hosted F-Droid repo (stable) — fdroidserver config + metadata
├── fdroid-dev/                   # Self-hosted F-Droid repo (dev builds)
└── ... (other project files)
```

## Features

- **Playback & queue control** — play/pause/skip, seek, shuffle/repeat, queue management
- **Volume control**
- **Library browsing** — artists, albums, playlists, radio, apps/plugins
- **QR-code pairing** — scan the code from the device's Settings screen (or the web admin); it carries the device address, the pairing token and the Lyrion web-player URL, no manual entry
- **Appliance settings** (once paired): audio output, multiroom (follow another Osmium's Lyrion, player name), updates (check/"Update now", Prod/Dev channel, Lyrion updates, release notes), backup & restore, Lyrion library rescan, Lyrion web-player look (Osmium/Material), and a *System admin* screen: display mode (screen ⇄ headless), UI render resolution, panel refresh rate, analog VU meter on/off, SSH on/off (shows the login name), reboot/shutdown, system info
- **Server discovery** on the local network
- Dark theme matching the appliance's UI

**Not included**: the analog VU meter (intentionally excluded — mobile-optimized layout).

## Technology stack

- Package: `com.osmium.sound.companion` · Min SDK 26 (Android 8.0) · target/compile SDK 36 · Java 17
- Build: Android Gradle Plugin 8.13, Gradle 8.13 (wrapper)
- Communication:
  - **CometD (Bayeux over HTTP)** with Lyrion Music Server on `:9000` for library/playback;
  - **HTTP to the appliance's sources service on `:8080`** (`sources_server.py`), authenticated with the pairing bearer token. That service exposes a deliberately limited proxy of the root-only system API (`/api/system/*` — see `_SYSTEM_PROXY_ROUTES` in `sources_server.py`) plus its own backup/restore and Lyrion-skin routes. The companion never talks to the loopback-only `api_server.py` directly, and it cannot reach factory reset, the shell/SSH account, network configuration or the web-admin account — see [SECURITY.md](SECURITY.md) and [ARCHITECTURE.md](ARCHITECTURE.md#pairing--security).
- LAN-only — phone and appliance must be on the same local network (or a Tailscale tailnet the owner set up)

## Build & development

```bash
cd android-companion
bash gradlew assembleDebug     # Build debug APK (use `bash gradlew`: the wrapper may not be executable on checkout)
bash gradlew installDebug      # Install on a connected device
bash gradlew assembleRelease   # Build release APK (needs the signing config / env vars)
```

See [BUILD_INSTRUCTIONS.md](android-companion/BUILD_INSTRUCTIONS.md) for full details.

## Distribution

Not published on the Google Play Store. Ships as:

- a **signed APK** attached to GitHub Releases tagged `companion-vX.Y.Z` (dev builds: `companion-vX.Y.Z-svilN`, marked prerelease);
- the **self-hosted F-Droid repo** `https://osmiumsound.it/fdroid/repo` (stable builds only), plus an opt-in dev repo `https://osmiumsound.it/fdroid/dev/repo` fed by the `-svilN` tags.

Both are produced by `.github/workflows/build-companion-apk.yml` — see the
[workflows README](.github/workflows/README.md) and the
[website](https://osmiumsound.it/#android) for install details.

## License

Apache License 2.0 — see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) and
[`android-companion/docs/LICENSE.md`](android-companion/docs/LICENSE.md).
Based on [android-squeezer](https://github.com/kaaholst/android-squeezer) by Kurt Aaholst and contributors.

## Support

For issues or feature requests, open a GitHub issue at
[github.com/adri6412/osmium-sound](https://github.com/adri6412/osmium-sound/issues)
or write to support@osmiumsound.it.
