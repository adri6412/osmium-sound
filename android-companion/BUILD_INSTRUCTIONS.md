# HiFi Media Player Companion - Build Instructions

## Prerequisites

### Required Tools
- **Android SDK**: API 31 or higher
- **Android SDK Tools**: Latest version
- **Java Development Kit (JDK)**: Version 17 or higher
- **Gradle**: 8.0+ (included with Android Studio or bundled in project)
- **Git**: For version control

### Development Environment
- **Android Studio**: Latest stable version (optional but recommended)
- **Windows/Mac/Linux**: Any platform with Java 17+ support

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/adriano-frongillo/hifi-media-player.git
cd hifi-media-player/android-companion
```

### 2. Install Android SDK

If you don't have Android Studio installed:
1. Download Android SDK command-line tools from: https://developer.android.com/studio
2. Install minimum SDK 31 and target SDK 34

### 3. Set Environment Variables

```bash
# Windows
set ANDROID_SDK_ROOT=C:\path\to\android-sdk
set JAVA_HOME=C:\path\to\jdk17

# macOS/Linux
export ANDROID_SDK_ROOT=~/Library/Android/sdk
export JAVA_HOME=$(jenv prefix 17)
```

## Build Variants

### Debug Build

```bash
# Build debug APK
./gradlew assembleDebug

# Install on connected device
./gradlew installDebug

# Build and run immediately
./gradlew assembleDebug && adb install -r build/outputs/apk/debug/HiFiMediaPlayer-debug.apk
```

### Release Build

#### Prerequisites for Release Build
1. Create a keystore file (first time only):
```bash
keytool -genkey -v -keystore hifi-media-player-local-release-key.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias hifi-media-player
```

2. Place keystore in: `android-companion/HiFiMediaPlayer/`

#### Building Release APK
```bash
# Build release APK (unsigned initially)
./gradlew bundleRelease

# Or build signed APK directly
./gradlew assembleRelease
```

#### Configuration via Properties File

For automated signing, create `HiFiMediaPlayer.properties`:

```properties
key.store.password=your-keystore-password
key.alias.password=your-key-password
```

Place in: `android-companion/` directory

## Testing

### Unit Tests
```bash
./gradlew test
```

### Android Instrumentation Tests
```bash
# Connect device or start emulator first
./gradlew connectedAndroidTest
```

### Manual Testing
1. **Install app**: `./gradlew installDebug`
2. **Test server discovery**: Auto-connects to servers on local network
3. **Test playback control**: Play/pause/skip functionality
4. **Test navigation**: Browse library, manage playlists
5. **Test responsive layout**: Portrait and landscape modes

## Device Requirements

### Minimum Specifications
- **Android Version**: 8.0 (API 26) and up
- **Screen Size**: 4.5" phones to 10" tablets
- **RAM**: 2GB minimum (4GB recommended)
- **Storage**: ~50MB for app + data

### Tested Devices
- Samsung Galaxy S10+ (Android 12)
- Pixel 5 (Android 13)
- iPad 7th Gen running Android emulator
- Various tablets (7"-10" screens)

## Troubleshooting

### Gradle Build Errors

**Issue**: `org.gradle.api.GradleException: A problem occurred evaluating project...`
- **Solution**: Update Gradle wrapper: `./gradlew wrapper --gradle-version 8.1`

**Issue**: `Duplicate class...` errors
- **Solution**: Check for conflicting dependencies in `build.gradle`

### Compilation Errors

**Issue**: `Can't find...` symbols
- **Solution**: Run `./gradlew clean` then rebuild
- **Alternative**: Invalidate caches in Android Studio (File > Invalidate Caches)

### Connection Issues

**Issue**: App can't connect to HiFi Media Player server
- **Solution**: 
  - Verify server is running and accessible on local network
  - Check firewall settings (default port: 9000)
  - Manually enter server address in Settings

### APK Installation Issues

**Issue**: `INSTALL_FAILED_INVALID_APK`
- **Solution**: Clear app data: `adb shell pm clear com.hifi.mediaplayer`
- **Alternative**: Uninstall first: `adb uninstall com.hifi.mediaplayer`

## Distribution

### Google Play Store

1. **Generate signed release APK**:
   ```bash
   ./gradlew assembleRelease
   ```

2. **Output location**: `HiFiMediaPlayer/build/outputs/apk/release/`

3. **Upload to Google Play Console**:
   - Create app listing
   - Upload APK
   - Fill in description, screenshots, etc.
   - Submit for review

### Direct Distribution

For beta testing or alternative distribution:

1. **Generate APK/AAB**:
   ```bash
   ./gradlew bundleRelease
   ```

2. **Share APK file**: Via email, GitHub releases, or your own server

3. **Installation**: Users download and open APK on Android device

### Version Management

Update version in `HiFiMediaPlayer/build.gradle`:

```gradle
android {
    defaultConfig {
        versionCode 159  // Increment for each release
        versionName "2.5.0"  // Semantic versioning
    }
}
```

## Performance Optimization

### Proguard/R8 Configuration

The build includes:
- `proguard-android-optimize.txt` (standard Android rules)
- `proguard-cometd.cfg` (CometD client rules)
- `proguard-guava.cfg` (Guava library rules)

Custom rules in: `HiFiMediaPlayer/proguard-squeezer.cfg`

### Build Optimization Tips

1. Enable build cache: `org.gradle.caching=true` in `gradle.properties`
2. Increase heap size: `org.gradle.jvmargs=-Xmx2048m`
3. Use parallel builds: `org.gradle.parallel=true`

## Continuous Integration

For CI/CD pipelines:

```yaml
# Example GitHub Actions
name: Build
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-java@v3
        with:
          java-version: '17'
          distribution: 'temurin'
      - run: cd android-companion && ./gradlew assembleDebug
```

## Support & Issues

For build issues, check:
1. [Android Developer Documentation](https://developer.android.com/)
2. [Gradle Build Tool Documentation](https://developer.android.com/build)
3. Project GitHub Issues: https://github.com/adriano-frongillo/hifi-media-player/issues

---

**Last Updated**: 2026-06-21
**Android Gradle Plugin**: 8.0+
**Target SDK**: 34 (Android 14)
