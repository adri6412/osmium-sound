# Osmium Sound Companion — Android App

Companion mobile application for Osmium Sound: remote control, library
browsing and appliance management from an Android phone or tablet.

## Overview

This is a rebranded and extended fork of [android-squeezer](https://github.com/kaaholst/android-squeezer)
(Apache-2.0), customized to serve as the official companion app for the Osmium
Sound appliance. Upstream Squeezer talks only to Lyrion Music Server; this app
additionally pairs with the appliance itself and exposes its settings.

## Key changes from the original

- **Package name**: `uk.org.ngo.squeezer` → `com.osmium.sound.companion`
- **App name**: "Squeezer" → "Osmium Sound Companion"
- **Module name**: `Squeezer` → `HiFiMediaPlayer`
- Dark "Osmium" theme (gold on black), desktop-inspired Now Playing layout
- QR-code pairing with the appliance + an "Osmium Sound" settings category

## Features

- Playback and queue control (play/pause/skip, seek, shuffle/repeat), volume
- Library browsing (artists, albums, playlists, radio, apps/plugins), search, Discover/random mixes via Lyrion
- **Connection wizard** — pick the app language (Italian / English) first, then choose between an Osmium Sound appliance (QR pairing, appliance settings) and any other Lyrion server (host:port, no appliance settings)
- **QR-code pairing** — scan the code from the appliance's Settings screen or web admin; it carries host, pairing token and the Lyrion web-player URL
- **This phone as a player** — registers with Lyrion over SlimProto (TCP 3483) and plays the audio on the phone with Media3/ExoPlayer: gapless, server volume, quality per network. See `HiFiMediaPlayer/src/main/java/com/osmium/sound/companion/service/localplayer/`
- Appliance settings once paired (Settings → *Osmium Sound*): **audio output**, **multiroom** (follow another unit's Lyrion, player name), **updates** (check / "Update now", Prod/Dev channel, Lyrion updates, release notes), **backup & restore**, **system admin** (display mode screen ⇄ headless, UI render resolution, panel refresh rate, VU meter on/off, SSH on/off + login name, reboot/shutdown, system info); under *Lyrion server*: library rescan and the web-player look (Osmium / Material)
- Server discovery and connection on the local network
- Screen rotation and responsive layouts (phone/tablet); 10 UI languages

Not included: the analog VU meter (intentionally excluded — mobile-optimized layout).

## Build & development

### Prerequisites
- Android SDK — compileSdk/targetSdk **36**, minSdk **26** (Android 8.0) — set in the root `build.gradle`
- JDK **17**
- Gradle **8.13** via the wrapper, Android Gradle Plugin **8.13.0** (`build.gradle`); Dependabot bumps of the wrapper/AGP/triplet-play are held back on purpose — check compatibility before accepting one

### Building

```bash
cd android-companion
bash gradlew assembleDebug        # the wrapper may not be executable after checkout — always `bash gradlew`
bash gradlew installDebug         # install on a connected device
bash gradlew assembleRelease      # needs the signing config (KEY_ALIAS/KEY_STORE_PASSWORD/KEY_PASSWORD env or a local keystore)
bash gradlew test lintVitalRelease
```

Line endings: many files here are CRLF on disk but LF in git — normalize to LF
before editing, or the diff becomes the whole file.

`versionName` in `HiFiMediaPlayer/build.gradle` must match one of the patterns
accepted by `publishTrack()` (e.g. `1.0.7`, `1.0.7-beta-1`); an unknown format
makes **every** Gradle invocation fail at configuration time. When removing a
base string, remove it from all `values-XX/strings.xml` too, or
`lintVitalRelease` (release builds only) fails.

## Project structure

```
HiFiMediaPlayer/
├── src/
│   ├── main/
│   │   ├── java/com/osmium/sound/companion/  # Main app source (Java)
│   │   │   ├── SystemAdminActivity, UpdatesActivity, AudioOutputActivity,
│   │   │   ├── MultiroomActivity, BackupRestoreActivity, SettingsFragment, …
│   │   │   └── dialog/ServerAddressView   # QR pairing parsing
│   │   ├── res/                            # Resources (layouts, strings, themes)
│   │   └── play/                           # Listing texts (legacy Play-style layout, reused by the F-Droid metadata)
│   └── androidTest/                        # Android instrumentation tests
├── build.gradle                            # Module build configuration (versionCode/versionName, signing, publishTrack())
└── lint.xml                                # Lint configuration
docs/        # LICENSE.md (Apache-2.0), upstream changelog NEWS.md, privacy note
```

## Integration with Osmium Sound

The app communicates with the appliance over two channels:

- **Lyrion Music Server** (CometD on `:9000`) — library browsing, playback and queue control, rescan.
- **Appliance sources/proxy service** (`sources_server.py` on `:8080`, HTTP with the pairing bearer token) — pairing, backup/restore, Lyrion skin, and a whitelisted proxy (`/api/system/*`) of the root-only system API for updates, audio output, display mode, UI resolution/refresh, VU meter, multiroom, SSH toggle, reboot/shutdown. See [ARCHITECTURE.md](../ARCHITECTURE.md#pairing--security) and [COMPANION_APP.md](../COMPANION_APP.md).

Both are LAN-only — phone and appliance must be on the same local network (or
the owner's Tailscale tailnet).

## Distribution

Not published on the Google Play Store. Ships as a signed APK (sideload,
attached to `companion-vX.Y.Z` GitHub Releases) or via the self-hosted F-Droid
repo at `https://osmiumsound.it/fdroid/repo` — see the
[website](https://osmiumsound.it/#android) for details.

There's also an **opt-in dev repo**, `https://osmiumsound.it/fdroid/dev/repo`,
fed by every `companion-vX.Y.Z-svilN` tag (same app, not tested to the same
standard as stable). Add it manually in the F-Droid client (Settings →
Repositories → add repository) only if you want early builds — it's separate
from, and doesn't affect, the stable repo above.

Releases are built by `.github/workflows/build-companion-apk.yml` — see
[RELEASE_PROCESS.md](RELEASE_PROCESS.md).

## License

This application is released under the **Apache License, Version 2.0**. See [`docs/LICENSE.md`](docs/LICENSE.md) for the full license text.

### Copyright notice

This is a derivative work of [android-squeezer](https://github.com/kaaholst/android-squeezer), maintained by Kurt Aaholst and contributors, originally licensed under Apache 2.0. Substantial portions of the original code, architecture, and design patterns are preserved.

**Osmium Sound Companion is an independent project and is NOT affiliated with, endorsed by, or officially associated with the original Squeezer project or the Lyrion/LMS-Community.**

## References

- Original project: https://github.com/kaaholst/android-squeezer (Apache-2.0, by Kurt Aaholst and contributors)
- Osmium Sound: https://github.com/adri6412/osmium-sound — support@osmiumsound.it
