# Releasing the Osmium Sound Companion

Releases are built and published by CI (`.github/workflows/build-companion-apk.yml`)
from git tags. There is no Play Store or Amazon Appstore upload.

## 1. Bump the version

Edit `HiFiMediaPlayer/build.gradle`:

```gradle
versionCode 24        // previous + 1
versionName "1.0.8"   // must match a case in publishTrack() below
```

`publishTrack()` (same file) whitelists the accepted `versionName` formats
(`X.Y.Z` → production track, `X.Y.Z-beta-N` → beta). An unknown format fails
every Gradle build, so extend it first if you need a new scheme.

## 2. Release notes

Edit `HiFiMediaPlayer/src/main/res/xml/changelog_master.xml` (the in-app
"what's new" dialog, ckChangeLog) and, if you keep them, regenerate the
derived files:

```bash
bash gradlew generateWhatsNew   # → src/main/play/release-notes/…/default.txt
bash gradlew generateNews       # → docs/NEWS.md
```

## 3. Test

```bash
cd android-companion
bash gradlew clean assembleDebug test lintVitalRelease
```

Install the debug build on a phone, pair with an appliance (QR from Settings),
check playback and the *Osmium Sound* settings screens.

## 4. Commit and tag

Commit the version bump (message style `companion 1.0.8: …`), then tag **with
the `companion-` prefix** — the appliance workflow ignores these tags and the
companion workflow only reacts to them:

```bash
# dev build from svil → prerelease + dev F-Droid repo
git tag -a companion-v1.0.8-svil1 -m "companion 1.0.8-svil1: ..."
git push origin companion-v1.0.8-svil1

# stable release (from main) → Release + stable F-Droid repo
git tag -a companion-v1.0.8 -m "companion 1.0.8: ..."
git push origin companion-v1.0.8
```

Push the tag explicitly (`git push origin <tag>`), never `git push --tags`.

## 5. What CI does

1. Builds and signs the release APK with the `SIGNING_KEY` keystore.
2. Creates the GitHub Release (title = the tag; prerelease for `-svil`/`-beta`
   tags) with the APK attached; runs unit tests and lint.
3. Stable tags only: updates the self-hosted F-Droid repo
   (`https://osmiumsound.it/fdroid/repo`, index signed with the separate
   `FDROID_REPO_KEYSTORE`); `-svilN` tags update the dev repo
   (`https://osmiumsound.it/fdroid/dev/repo`).

Details and secrets: [`.github/workflows/README.md`](../.github/workflows/README.md),
tag/branch rules: [`TAG_CONVENTIONS.md`](../.github/workflows/TAG_CONVENTIONS.md).

## If something went wrong

Delete the tag (`git tag -d …`, `git push origin :…`), fix, re-tag. A Release
deleted by hand while the tag still exists can be recreated with
`gh run rerun <run-id>` of the original workflow run.
