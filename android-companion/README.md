# HiFi Media Player Companion - Android App

Companion mobile application for HiFi Media Player, allowing remote control and playback management from Android devices.

## Overview

This is a rebranded and integrated version of [android-squeezer](https://github.com/kaaholst/android-squeezer), customized to serve as the official companion app for HiFi Media Player.

## Key Changes from Original

- **Package name**: `uk.org.ngo.squeezer` → `com.hifi.mediaplayer`
- **App name**: "Squeezer" → "HiFi Media Player Companion"
- **Module name**: `Squeezer` → `HiFiMediaPlayer`
- **Application class**: `Squeezer` → `HiFiMediaPlayer`
- **Service**: Updated label to "HiFi Media Player Service"

## Features

- Remote control of HiFi Media Player playback
- Player selection and management
- Playlist browsing and editing
- Alarm management
- Server discovery and connection
- Screen rotation and responsiveness optimization

## Build & Development

### Prerequisites
- Android SDK (API level 24 or higher)
- Gradle 8.0+
- Java 17

### Building

```bash
cd android-companion
./gradlew build
```

### Running on Device

```bash
./gradlew installDebug
```

## Project Structure

```
HiFiMediaPlayer/
├── src/
│   ├── main/
│   │   ├── java/com/hifi/mediaplayer/     # Main app source
│   │   └── res/                            # Resources (layouts, strings, etc.)
│   └── androidTest/                        # Android instrumentation tests
├── build.gradle                            # Module build configuration
└── lint.xml                                # Lint configuration
```

## Integration with HiFi Media Player

This app communicates with the HiFi Media Player server using:
- **Protocol**: CometD (modern WebSocket-based protocol)
- **Connection**: Network communication on local network
- **Server Discovery**: Automatic server detection on network

The UI is designed to mirror the desktop app while being optimized for mobile screens.

## License

MIT License - See original project for details.

## References

- Original Project: https://github.com/kaaholst/android-squeezer
- HiFi Media Player: https://github.com/adriano-frongillo/hifi-media-player
