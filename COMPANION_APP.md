# Osmium Sound — Android Companion App

## Overview

The **Osmium Sound Companion** is the official Android app for remote control
of an Osmium Sound appliance — browse the library, drive playback and the
queue, adjust volume, and (once paired) manage DSP and system admin actions
from the phone.

## Location

The companion app source lives in [`android-companion/`](android-companion/):

```
hifi-media-player/
├── android-companion/            # Android Companion App
│   ├── HiFiMediaPlayer/          # Main app module
│   │   ├── src/main/java/com/osmium/sound/companion/
│   │   └── src/main/res/         # Resources, layouts, strings, themes
│   ├── README.md                 # Quick start guide
│   ├── DESIGN_GUIDELINES.md      # UI/UX design specifications
│   └── BUILD_INSTRUCTIONS.md     # Build and deployment guide
└── ... (other project files)
```

## Features

- **Playback & queue control** — play/pause/skip, seek, shuffle/repeat, queue management
- **Volume control**
- **Library browsing** — artists, albums, playlists
- **QR-code pairing** — scan the code from the device's Settings screen, no manual address entry
- **DSP & admin controls** (once paired) — EQ/DSP settings, audio device selection, SSH, updates, reboot/shutdown
- **Server discovery** on the local network
- Dark theme matching the appliance's UI

**Not included**: the analog VU meter (intentionally excluded — mobile-optimized layout).

## Technology stack

- Package: `com.osmium.sound.companion` · Min SDK 26 (Android 8.0) · Java
- Communication: CometD (WebSocket) with Lyrion Music Server for library/playback, plus direct HTTPS calls to the appliance's Flask API (see [ARCHITECTURE.md](ARCHITECTURE.md)) for pairing, DSP and admin actions
- LAN-only — phone and appliance must be on the same local network

## Build & development

```bash
cd android-companion
./gradlew assembleDebug     # Build debug APK
./gradlew installDebug      # Install on a connected device
./gradlew assembleRelease   # Build release APK
```

See [BUILD_INSTRUCTIONS.md](android-companion/BUILD_INSTRUCTIONS.md) for full details.

## Distribution

Not published on the Google Play Store. Ships as a signed APK (sideload) or
via the self-hosted F-Droid repo at `https://osmiumsound.qd.je/fdroid/repo` —
see the [website](https://osmiumsound.qd.je/#android) for details.

## License

Apache License 2.0 — see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
Based on [android-squeezer](https://github.com/kaaholst/android-squeezer) by Kurt Aaholst.

## Support

For issues or feature requests, open a GitHub issue at
[github.com/adri6412/osmium-sound](https://github.com/adri6412/osmium-sound/issues).
