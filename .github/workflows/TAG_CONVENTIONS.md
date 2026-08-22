# Git Tag Conventions

This document explains how to use git tags to trigger different GitHub Actions workflows.

## Tag Naming

### Main App (Osmium Sound - Desktop/Electron)
**Format**: `v<MAJOR>.<MINOR>.<PATCH>`

**Examples**:
- `v1.0.0`
- `v1.2.3`
- `v2.5.0`

**Triggers**:
- ✅ `build-ui-ota.yml` - Builds OTA bundles for desktop app
- ❌ `build-companion-apk.yml` - NOT triggered

### Companion App (Osmium Sound Companion - Android)
**Format**: `companion-v<MAJOR>.<MINOR>.<PATCH>`

**Examples**:
- `companion-v2.5.0`
- `companion-v2.5.1`
- `companion-v3.0.0`

**Triggers**:
- ✅ `build-companion-apk.yml` - Builds release APK
- ❌ `build-ui-ota.yml` - NOT triggered

## Branches & OTA channels

- **`main` = production.** Stable tags `vX.Y.Z` are cut from here. They publish a
  normal GitHub Release, which the appliance sees via `GET /releases/latest`
  (the **prod** channel).
- **`svil` = development.** Day-to-day work. Prerelease tags `vX.Y.Z-dev.N` are
  cut from here. Because the tag has a hyphen, `build-ui-ota.yml` marks the
  release as a **prerelease**, which `/releases/latest` ignores — so prod
  devices never receive it. A device set to the **dev** channel
  (Settings → Updates → Sviluppo) tracks the newest release *including*
  prereleases.
- **`alpha` = private, ad hoc.** For trying your own experimental fixes on
  your own device(s) *before* they're ready to be a real, shared `-dev.N`
  build. `alpha` is the **only** branch releases are tagged from for this
  channel (a process convention, not a CI-enforced gate — the workflow still
  only looks at the tag name). Tag format is **nested on top of the dev
  build you started from**: if `svil` is at `v2.5.21-dev.50`, your first
  attempt on `alpha` is `v2.5.21-dev.50-alpha1`, the next `-alpha2`, etc.
  `_fetch_github_api_release`'s `dev` branch explicitly excludes any tag
  matching `-alpha\d+$`, so these never reach a `dev`-channel device. The
  **alpha** option itself only appears in Settings on a device where
  `/etc/hifi-player/ota-alpha-unlocked` has been created by hand (root/SSH,
  `hifi-ota-alpha-toggle.sh enable` — see the script's header; it is
  deliberately not reachable via the network API). Once a fix is validated
  on `alpha`, merge/cherry-pick it into `svil` and cut the next real
  `v2.5.21-dev.51` there for the shared dev channel.

Promotion: PR `svil` → `main`, then tag a stable `vX.Y.Z` on `main`.

Versioning stays patch-incremental: iterate `v2.5.7-dev.1`, `v2.5.7-dev.2`, …
on `svil`, then promote to the stable `v2.5.7` on `main`.

## Release Process

### Development build (prerelease, dev channel)

```bash
git checkout svil
# ...commit work...
git push origin svil
git tag -a v2.5.7-dev.1 -m "dev build"
git push origin v2.5.7-dev.1   # → build-ui-ota.yml publishes a PRERELEASE
```

### Alpha build (private, ad hoc — own devices only)

```bash
git checkout alpha
git merge svil                 # stay based on the dev build you're testing against
# ...commit your experimental fix...
git push origin alpha
git tag -a v2.5.21-dev.50-alpha1 -m "alpha: try XYZ fix"
git push origin v2.5.21-dev.50-alpha1   # → PRERELEASE, invisible to the dev channel

# on the device you want to test with (root/SSH, once):
hifi-ota-alpha-toggle.sh enable
# now Settings → Updates shows an "Alpha" option — select it and check for updates
```

### Main App Release (Desktop/Electron)

```bash
# 1. Update version in src or main app
# Update package.json or VERSION file

# 2. Commit changes
git add -A
git commit -m "chore(release): v1.2.3"
git push origin main

# 3. Create and push tag (NO COMPANION PREFIX)
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3

# 4. GitHub Actions automatically:
#    - Runs build-ui-ota.yml
#    - Builds UI and OS OTA bundles
#    - Creates GitHub Release
#    - Attaches OTA bundles
```

### Companion App Release (Android)

```bash
# 1. Update version in HiFiMediaPlayer/build.gradle
# versionCode += 1
# versionName = "2.5.1"

# 2. Test locally
./gradlew clean assembleDebug
./gradlew test

# 3. Commit changes
cd android-companion
git add HiFiMediaPlayer/build.gradle
git commit -m "chore(release): v2.5.1"
git push origin main

# 4. Create and push tag (WITH COMPANION PREFIX!)
git tag -a companion-v2.5.1 -m "Osmium Sound Companion v2.5.1 - Release notes..."
git push origin companion-v2.5.1

# 5. GitHub Actions automatically:
#    - Runs build-companion-apk.yml
#    - Builds release APK
#    - Signs with keystore
#    - Creates GitHub Release
#    - Attaches APK
```

## Workflow Isolation

### build-deb.yml
- **Trigger**: Push of tag matching `v*`
- **Condition**: Skip if tag contains `companion`
- **Result**: Builds .deb package and publishes to GitHub Release
- **Artifact retention**: Tag releases: published to Release; manual runs: 7 days

### build-ui-ota.yml
- **Trigger**: Push of tag matching `v*`
- **Condition**: Skip if tag contains `companion`
- **Result**: Builds desktop app OTA bundles

### build-companion-apk.yml
- **Trigger**: Push of tag matching `companion-v*`
- **Condition**: Must start with `companion-` prefix
- **Result**: Builds Android APK

### build-iso.yml
- **Trigger**: Manual (`workflow_dispatch`)
- **No automatic triggers**

## Tag History Reference

```
v1.0.0          → Desktop app v1.0.0
v1.0.1          → Desktop app v1.0.1
v1.1.0          → Desktop app v1.1.0
companion-v2.5.0 → Companion app v2.5.0
companion-v2.5.1 → Companion app v2.5.1
v2.0.0          → Desktop app v2.0.0
companion-v3.0.0 → Companion app v3.0.0
```

## Important Notes

1. **Always use correct prefix**: 
   - Main app: no prefix (`v1.2.3`)
   - Companion app: with prefix (`companion-v2.5.0`)

2. **Tag naming is case-sensitive**: 
   - `companion-v2.5.0` ✅
   - `Companion-v2.5.0` ❌
   - `companion-V2.5.0` ❌

3. **Release notes in tag message**:
   ```bash
   git tag -a companion-v2.5.0 -m "Release notes here..."
   ```

4. **If you make a mistake**:
   ```bash
   # Delete local tag
   git tag -d companion-v2.5.0
   
   # Delete remote tag
   git push origin :companion-v2.5.0
   
   # Recreate tag
   git tag -a companion-v2.5.0 -m "..."
   git push origin companion-v2.5.0
   ```

## Monitoring Workflows

Watch workflow progress:
1. GitHub → Actions
2. Select the workflow
3. Click the run
4. View logs in real-time

## Troubleshooting

**Problem**: Wrong workflow triggered
- **Solution**: Check tag name - must have correct prefix

**Problem**: Workflow didn't trigger
- **Solution**: Verify tag matches pattern (`v*` or `companion-v*`)

**Problem**: Tag created but workflow didn't start
- **Solution**: 
  1. Check tag matches pattern
  2. Wait 5-10 seconds (GitHub queue)
  3. Refresh Actions page
  4. Check workflow's `if:` condition

---

**Last Updated**: 2026-06-21  
**Version**: 1.0
