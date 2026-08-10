# Osmium Sound Companion — Android App

Companion mobile application for Osmium Sound, allowing remote control and
playback management from Android devices.

## Overview

This is a rebranded and integrated version of [android-squeezer](https://github.com/kaaholst/android-squeezer), customized to serve as the official companion app for Osmium Sound.

## Key changes from the original

- **Package name**: `uk.org.ngo.squeezer` → `com.osmium.sound.companion`
- **App name**: "Squeezer" → "Osmium Sound Companion"
- **Module name**: `Squeezer` → `HiFiMediaPlayer`

## Features

- Playback and queue control (play/pause/skip, seek, shuffle/repeat)
- Volume control
- Library browsing (artists, albums, playlists)
- **QR-code pairing** — scan the code from the appliance's Settings screen, no manual address entry
- DSP and system admin controls once paired (EQ/DSP settings, audio device, SSH, updates, reboot/shutdown)
- Server discovery and connection on the local network
- Screen rotation and responsive layouts (phone/tablet)

Not included: the analog VU meter (intentionally excluded — mobile-optimized layout).

## Build & development

### Prerequisites
- Android SDK (compileSdk/targetSdk 36, minSdk 26 / Android 8.0)
- Gradle 8.0+
- Java 17

### Building

```bash
cd android-companion
./gradlew build
```

### Running on device

```bash
./gradlew installDebug
```

## Project structure

```
HiFiMediaPlayer/
├── src/
│   ├── main/
│   │   ├── java/com/osmium/sound/companion/  # Main app source
│   │   └── res/                                # Resources (layouts, strings, etc.)
│   └── androidTest/                            # Android instrumentation tests
├── build.gradle                                # Module build configuration
└── lint.xml                                    # Lint configuration
```

## Integration with Osmium Sound

This app communicates with the appliance using two channels:
- **Lyrion Music Server** (CometD/WebSocket) — library browsing, playback and queue control
- **Flask API on the appliance** (HTTPS) — pairing, DSP settings, and system admin actions; see [ARCHITECTURE.md](../ARCHITECTURE.md)

Both are LAN-only — phone and appliance must be on the same local network.
The UI is designed to mirror the appliance's UI while being optimized for mobile screens.

## Distribution

Not published on the Google Play Store. Ships as a signed APK (sideload) or
via the self-hosted F-Droid repo at `https://osmiumsound.qd.je/fdroid/repo` —
see the [website](https://osmiumsound.qd.je/#android) for details.

There's also an **opt-in dev repo**, `https://osmiumsound.qd.je/fdroid/dev/repo`,
fed by every `companion-vX.Y.Z-svilN` tag (same app, not tested to the same
standard as stable). Add it manually in the F-Droid client (Settings →
Repositories → add repository) only if you want early builds — it's separate
from, and doesn't affect, the stable repo above.

## License

This application is released under the **Apache License, Version 2.0**. See [`docs/LICENSE.md`](docs/LICENSE.md) for the full license text.

### Copyright notice

This is a derivative work of [android-squeezer](https://github.com/kaaholst/android-squeezer), maintained by Kurt Aaholst and contributors, originally licensed under Apache 2.0. Substantial portions of the original code, architecture, and design patterns are preserved.

**Osmium Sound Companion is an independent project and is NOT affiliated with, endorsed by, or officially associated with the original Squeezer project or the Lyrion/LMS-Community.**

## References

- Original project: https://github.com/kaaholst/android-squeezer (Apache-2.0, by Kurt Aaholst and contributors)
- Osmium Sound: https://github.com/adri6412/osmium-sound
