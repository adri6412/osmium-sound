# Osmium Sound Companion - Build Instructions

## Prerequisites

- **JDK 17** (the build uses `sourceCompatibility`/`targetCompatibility` 17)
- **Android SDK** with platform **36** installed (`compileSdk`/`targetSdk` 36, `minSdk` 26 — defined in the root `build.gradle`)
- **Gradle**: use the bundled wrapper (Gradle **8.13**) with **Android Gradle Plugin 8.13.0**. Don't upgrade either blindly: AGP 8.13 does not accept newer Gradle majors, and the `com.github.triplet.play` plugin has its own Gradle floor
- **Git**; Android Studio is optional

## Setup

```bash
git clone https://github.com/adri6412/osmium-sound.git
cd osmium-sound/android-companion
export ANDROID_SDK_ROOT=~/Android/Sdk      # or ANDROID_HOME
export JAVA_HOME=/path/to/jdk17
```

The Gradle wrapper script may not carry the executable bit after checkout
(the repo is used from Windows too) — always invoke it as `bash gradlew …`.
Many files in this directory are CRLF on disk but LF in git; normalize before
editing or diffs become whole-file.

## Build variants

### Debug

```bash
bash gradlew assembleDebug
bash gradlew installDebug        # install on a connected device/emulator
# APK: HiFiMediaPlayer/build/outputs/apk/debug/
```

### Release

The release signing config in `HiFiMediaPlayer/build.gradle` reads either a
`keystore` file decoded by CI, or a local
`HiFiMediaPlayer/hifi-media-player-local-release-key.keystore` with the
`KEY_ALIAS`, `KEY_STORE_PASSWORD` and `KEY_PASSWORD` environment variables
(alias defaults to `hifi-media-player`).

```bash
keytool -genkey -v -keystore HiFiMediaPlayer/hifi-media-player-local-release-key.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 -alias hifi-media-player   # first time only
export KEY_ALIAS=hifi-media-player KEY_STORE_PASSWORD=… KEY_PASSWORD=…
bash gradlew assembleRelease
# APK: HiFiMediaPlayer/build/outputs/apk/release/
```

## Testing

```bash
bash gradlew test                   # unit tests
bash gradlew lintVitalRelease       # the lint gate CI's release build runs — catches strings missing from values-XX/
bash gradlew connectedAndroidTest   # instrumentation tests (device/emulator)
```

Manual checks worth doing before a release: pairing by QR from the appliance's
Settings screen, playback control, the *Osmium Sound* settings category
(updates, audio output, system admin), portrait + landscape.

## Device requirements

- Android 8.0 (API 26) or newer; phones and tablets
- Same LAN (or Tailscale tailnet) as the Osmium Sound appliance — Lyrion on `:9000`, appliance services on `:8080`

## Troubleshooting

- **`versionName '…' is not valid`** at configuration time → `publishTrack()` in `HiFiMediaPlayer/build.gradle` whitelists the accepted formats; add a case before using a new scheme.
- **`lintVitalRelease` fails on a missing translation** → you removed/renamed a base string; remove it from every `values-XX/strings.xml` as well. Debug builds won't catch this.
- **Gradle/AGP incompatibility** → stay on the wrapper's 8.13 / AGP 8.13.0 pairing.
- **Can't connect to the appliance** → check both devices are on the same network; the Lyrion port is 9000; the pairing QR is in the appliance's Settings (kiosk) or web admin (Companion card).
- **`INSTALL_FAILED_UPDATE_INCOMPATIBLE`** → a build signed with a different key is installed: `adb uninstall com.osmium.sound.companion` first.
- **Duplicate class / stale build errors** → `bash gradlew clean`, or invalidate caches in Android Studio.

## Distribution

Not on the Google Play Store. Releases are produced by
`.github/workflows/build-companion-apk.yml` on `companion-v*` tags: signed APK
on the GitHub Release plus the self-hosted F-Droid repos
(`https://osmiumsound.it/fdroid/repo` for stable, `…/fdroid/dev/repo` for
`-svilN` dev builds). See [RELEASE_PROCESS.md](RELEASE_PROCESS.md) and
[`.github/workflows/README.md`](../.github/workflows/README.md).

### Version management

```gradle
// HiFiMediaPlayer/build.gradle
versionCode 23       // +1 for each release
versionName "1.0.7"  // must match a publishTrack() case
```

## ProGuard/R8

The release build uses `proguard-android-optimize.txt`, `proguard-cometd.cfg`,
`proguard-guava.cfg` and the project's own `HiFiMediaPlayer/proguard-squeezer.cfg`.

## Support & issues

- Project issues: https://github.com/adri6412/osmium-sound/issues — support@osmiumsound.it
- [Android developer documentation](https://developer.android.com/) · [Gradle build docs](https://developer.android.com/build)

---

**Last updated**: 2026-08-22 · AGP 8.13.0 · Gradle 8.13 · compile/target SDK 36 · min SDK 26
