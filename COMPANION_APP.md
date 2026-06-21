# HiFi Media Player - Android Companion App

## Overview

The **HiFi Media Player Companion** is an official Android mobile application that provides remote control and playback management for HiFi Media Player servers. It allows users to control their hi-fi audio playback from smartphones and tablets.

## Location

The companion app source code is located in the `android-companion/` directory:

```
hifi-media-player/
├── android-companion/          # Android Companion App
│   ├── HiFiMediaPlayer/        # Main app module
│   │   ├── src/
│   │   │   ├── main/java/com/hifi/mediaplayer/
│   │   │   └── main/res/        # Resources, layouts, strings, themes
│   │   └── build.gradle
│   ├── settings.gradle
│   ├── build.gradle
│   ├── README.md               # Quick start guide
│   ├── DESIGN_GUIDELINES.md    # UI/UX design specifications
│   └── BUILD_INSTRUCTIONS.md   # Build and deployment guide
└── ... (other project files)
```

## Features

- **Remote Playback Control**: Play, pause, skip, volume control
- **Player Management**: Select and manage multiple connected players
- **Library Browsing**: Browse music library, artists, albums, playlists
- **Playlist Management**: Create, edit, and manage playlists
- **Alarm Management**: Set and manage alarms on the server
- **Server Discovery**: Auto-discover HiFi Media Player servers on local network
- **Responsive Design**: Optimized for phones (4.5"-6.7") and tablets (7"-10"+)
- **Dark Theme**: Premium dark interface matching desktop app
- **Gesture Support**: Touch-optimized controls with haptic feedback

## Architecture

### Communication Protocol
- **Protocol**: CometD (WebSocket-based)
- **Connection**: LAN-only (local network)
- **Default Port**: 9000 (configurable)
- **Security**: TLS/SSL support

### Technology Stack
- **Language**: Java 17
- **Min SDK**: Android 8.0 (API 26)
- **Target SDK**: Android 14 (API 34)
- **UI Framework**: Android Material Design 3
- **Build System**: Gradle 8.0+
- **Architecture**: MVVM with Repository pattern

### Key Dependencies
- AndroidX (appcompat, preference, media)
- Material Components for Android
- CometD Java Client (3.1.11)
- ChangeLog library (ckChangeLog)
- RecyclerView Fast Scroller

## Design & Branding

The app maintains visual consistency with the desktop HiFi Media Player:

### Color Scheme
- **Primary Background**: `#0a0a0a` (Deep Black)
- **Secondary Surfaces**: `#1a1a1a`, `#2a2a2a`, `#3a3a3a` (Grays)
- **Accent Color**: `#D4AF37` (Gold)
- **Text**: `#ffffff` (White)

### Typography
- **Font Family**: System default (Segoe UI, Roboto, Ubuntu)
- **Style**: Modern, minimalist, readable

### Layout
- **Portrait**: Single-column vertical stack
- **Landscape**: Multi-column responsive layout
- **Tablet**: 2-3 column sidebar + content

See [DESIGN_GUIDELINES.md](android-companion/DESIGN_GUIDELINES.md) for complete specifications.

## Build & Development

### Quick Start
```bash
cd android-companion
./gradlew assembleDebug           # Build debug APK
./gradlew installDebug            # Install on device
./gradlew assembleRelease         # Build release APK
```

### Requirements
- Java 17 or higher
- Android SDK (API 31+)
- Gradle 8.0+

### For Detailed Instructions
See [BUILD_INSTRUCTIONS.md](android-companion/BUILD_INSTRUCTIONS.md)

## Integration with HiFi Media Player Server

### Server Setup
1. Ensure HiFi Media Player server is running and accessible on local network
2. Server port should be accessible (default: 9000)
3. Server must support CometD protocol

### Client Connection Flow
1. App starts and performs auto-discovery via UDP broadcast
2. User selects from discovered servers or manually enters address
3. App establishes CometD websocket connection
4. Real-time playback status and library data synced

### Network Requirements
- Local network connectivity (WiFi or LAN)
- Same subnet as server (for auto-discovery)
- Port 9000 (or configured port) accessible
- TLS/SSL optional but recommended

## Project Structure

```
android-companion/HiFiMediaPlayer/src/
├── main/
│   ├── java/com/hifi/mediaplayer/
│   │   ├── itemlist/              # List activities (home, players, alarms)
│   │   ├── service/               # Background service for playback
│   │   ├── download/              # Download management
│   │   ├── homescreenwidgets/     # Home screen widgets
│   │   ├── screensaver/           # Idle screensaver
│   │   └── ... (other packages)
│   └── res/
│       ├── values/                # Colors, strings, themes
│       ├── layout/                # Activity layouts
│       ├── drawable/              # Icons and graphics
│       └── menu/                  # Menu definitions
└── androidTest/
    └── java/com/hifi/mediaplayer/ # Instrumentation tests
```

## Version Management

- **Current Version**: 2.4.1 (rebranded from android-squeezer)
- **Versioning Scheme**: Semantic versioning (major.minor.patch)
- **Build Config**: See [HiFiMediaPlayer/build.gradle](android-companion/HiFiMediaPlayer/build.gradle)

## Contributing

### Code Style
- Follow Android development best practices
- Use Material Design 3 components
- Maintain responsive layouts for different screen sizes
- Write unit tests for business logic

### Testing
- Unit tests: `./gradlew test`
- Integration tests: `./gradlew connectedAndroidTest`
- Manual testing on multiple devices recommended

### Pull Requests
1. Create feature branch from `main`
2. Make changes following design guidelines
3. Test on minimum SDK and latest SDK versions
4. Submit PR with description of changes

## Known Issues & Limitations

1. **Auto-discovery** only works on same network subnet
2. **TLS/SSL**: Currently supports basic TLS (no certificate validation)
3. **Offline Mode**: Not supported (requires active server connection)
4. **Music Library Sync**: One-way sync from server only

## Future Enhancements

- [ ] Offline playlist caching
- [ ] Custom voice commands
- [ ] Notification-based playback control
- [ ] Home Assistant integration
- [ ] Bluetooth remote support
- [ ] Apple Watch companion app

## Troubleshooting

### App Won't Connect to Server
- Verify server is running and on same network
- Check firewall settings
- Try manually entering server address instead of auto-discovery
- Check server logs for CometD errors

### App Crashes on Launch
- Clear app data: Settings > Apps > HiFi Media Player Companion > Clear Data
- Uninstall and reinstall app
- Check Android version (minimum 8.0 required)

### Playback Controls Not Responding
- Verify network connection is stable
- Restart the app
- Restart the server
- Check server connectivity logs

## Support

For issues, feature requests, or questions:
1. Check [BUILD_INSTRUCTIONS.md](android-companion/BUILD_INSTRUCTIONS.md) for common build issues
2. Review [DESIGN_GUIDELINES.md](android-companion/DESIGN_GUIDELINES.md) for UI questions
3. Create GitHub issue: https://github.com/adriano-frongillo/hifi-media-player/issues

## License

MIT License - See LICENSE file for details

## Credits

- **Original Project**: [android-squeezer](https://github.com/kaaholst/android-squeezer) by Kristian Höstebo
- **Rebranding & Integration**: HiFi Media Player Team
- **Material Design**: Google Material Design 3

---

**Last Updated**: 2026-06-21  
**App Version**: 2.4.1  
**Target SDK**: Android 14 (API 34)  
**Min SDK**: Android 8.0 (API 26)
