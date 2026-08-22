# Contributing to the Osmium Sound Companion

The companion app lives inside the Osmium Sound monorepo
(https://github.com/adri6412/osmium-sound, directory `android-companion/`).
Bugs, feature requests and pull requests go there — not to the upstream
[android-squeezer](https://github.com/kaaholst/android-squeezer) project this
app is derived from (Apache-2.0); please don't report Osmium-specific issues
upstream.

## Reporting bugs and feature requests

Use the [issues page](https://github.com/adri6412/osmium-sound/issues). Say
which app version (Settings → About) and which appliance version (Settings →
Updates) you were running, and whether the problem is in the Lyrion side
(library/playback) or in the appliance side (pairing, updates, system admin).

## Translations

The easiest way to contribute, especially if you are not a programmer, is to
help translate the interface. Strings live in
`HiFiMediaPlayer/src/main/res/values/strings.xml`; a translation is a copy of
that file in `values-<language>/` (two-letter ISO 639-1 code, optionally
`-r<REGION>`). English and Italian must always be complete; when a base string
is removed it has to be removed from every `values-XX/` file too, or the release
lint gate fails.

## Code

- Branches: `svil` is day-to-day development, `alpha` is for private test
  builds, `main` is production. Open pull requests against `svil`.
- Build with `bash gradlew assembleDebug` (see
  [BUILD_INSTRUCTIONS.md](BUILD_INSTRUCTIONS.md)); run `bash gradlew test
  lintVitalRelease` before pushing.
- Keep the Osmium-specific parts (pairing, `/api/system/*` calls in
  `SystemAdminActivity`/`UpdatesActivity`/…) consistent with the other two
  front-ends (kiosk `src/pages/Settings.jsx`, web admin
  `admin-webui/src/views/Settings.vue`): there is no shared settings schema,
  so a setting added or hidden in one place has to be mirrored by hand.
- Anything user-visible must exist in English and Italian.
- Releases are cut by tag (`companion-vX.Y.Z`, dev `companion-vX.Y.Z-svilN`) —
  see [RELEASE_PROCESS.md](RELEASE_PROCESS.md).

## Android Studio

Open the `android-companion/` directory as a project (File → Open); the
Gradle wrapper and JDK 17 settings are picked up from there.
