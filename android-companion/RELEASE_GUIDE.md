# HiFi Media Player Companion - Release Guide

## Quick Start for Releases

This guide explains how to create releases that automatically generate signed APKs via GitHub Actions.

---

## 📱 Making a Release

### Step 1: Update Version

Update the version in `HiFiMediaPlayer/build.gradle`:

```gradle
android {
    defaultConfig {
        versionCode 159      // Increment by 1
        versionName "2.5.0"  // Update version
    }
}
```

### Step 2: Test Build

Test the build locally before releasing:

```bash
./gradlew clean
./gradlew assembleDebug       # Test debug build
./gradlew test                # Run tests
./gradlew lint                # Run lint
```

### Step 3: Create Git Tag

From the project root:

```bash
# Create annotated tag
git tag -a v2.5.0 -m "HiFi Media Player Companion v2.5.0

- Desktop-inspired UI
- Dark theme with gold accents
- Tab-based navigation
- Large play/pause control
- Compatible with Android 8.0+"

# Push tag to GitHub
git push origin v2.5.0
```

### Step 4: Watch Workflow

The GitHub Actions workflow will automatically:

1. ✅ Check out code
2. ✅ Build APK
3. ✅ Sign APK (using secrets)
4. ✅ Create GitHub Release
5. ✅ Upload APK to Release
6. ✅ Run tests and lint

**Monitor progress**: GitHub → Actions → Build HiFi Media Player Companion APK

### Step 5: Verify Release

1. Go to **GitHub → Releases**
2. Find the new release (e.g., `v2.5.0`)
3. Verify APK is attached
4. Review release notes
5. Download and test APK

---

## 🔐 Prerequisites (One-Time Setup)

### 1. Generate Signing Key

```bash
cd android-companion/HiFiMediaPlayer

# Generate keystore
keytool -genkey -v -keystore hifi-media-player-release.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias hifi-media-player
```

**Save passwords:**
```
Keystore password: [save this]
Key password:      [save this]
Alias:             hifi-media-player
```

### 2. Add GitHub Secrets

Encode keystore:
```bash
cd android-companion/HiFiMediaPlayer
base64 -w 0 hifi-media-player-release.keystore > keystore.b64
cat keystore.b64
```

Go to: **GitHub → Settings → Secrets and variables → Actions**

Add these secrets:
- `SIGNING_KEY` = (base64 output from above)
- `KEY_ALIAS` = `hifi-media-player`
- `KEY_STORE_PASSWORD` = (keystore password)
- `KEY_PASSWORD` = (key password)

**Never commit the keystore file or passwords to git!**

---

## 🚀 Full Release Workflow

```bash
# 1. Update version in build.gradle
#    versionCode → +1
#    versionName → "2.5.0"

# 2. Test locally
./gradlew clean assembleDebug
./gradlew test
./gradlew lint

# 3. Commit changes (if any)
git add -A
git commit -m "chore(release): bump version to 2.5.0"
git push origin main

# 4. Create and push tag
git tag -a v2.5.0 -m "Release v2.5.0"
git push origin v2.5.0

# 5. GitHub Actions automatically:
#    - Builds APK
#    - Signs APK
#    - Creates Release
#    - Uploads APK

# 6. Monitor at: GitHub → Actions
# 7. Verify at: GitHub → Releases
```

---

## 📝 Version Numbering

Use semantic versioning:

```
v[MAJOR].[MINOR].[PATCH]

v2.5.0    = Release (MAJOR.MINOR.PATCH)
v2.5.1    = Bug fix (patch)
v2.6.0    = New features (minor)
v3.0.0    = Breaking changes (major)

v2.5.0-beta.1    = Beta release
v2.5.0-rc.1      = Release candidate
```

---

## 🎯 Release Checklist

### Before Release
- [ ] Update version in `build.gradle`
- [ ] Build and test locally: `./gradlew clean assembleDebug`
- [ ] Run tests: `./gradlew test`
- [ ] Run lint: `./gradlew lint`
- [ ] Update CHANGELOG (optional)
- [ ] Review changes since last release

### During Release
- [ ] Create git tag: `git tag -a v2.5.0 -m "..."`
- [ ] Push tag: `git push origin v2.5.0`
- [ ] Monitor GitHub Actions workflow
- [ ] Wait for workflow completion (2-3 min)

### After Release
- [ ] Verify GitHub Release is created
- [ ] Check APK is attached to release
- [ ] Review release notes
- [ ] Download and test APK on device
- [ ] Mark as latest on GitHub (if applicable)
- [ ] Share release link with team

---

## 🔍 Troubleshooting

### Workflow failed

**Check logs**:
1. GitHub → Actions
2. Click the failed workflow
3. Click the job name
4. Scroll to see error message

**Common issues**:

| Error | Solution |
|-------|----------|
| "Signing key not found" | Check secrets are set in GitHub Settings |
| "Invalid keystore format" | Re-encode keystore to base64 |
| "JDK not found" | Workflow should auto-install, check logs |
| "Gradle download timeout" | Retry manually or check network |

### APK not signed

Verify all 4 secrets exist:
```bash
# GitHub Settings → Secrets and variables → Actions
# Should have:
✓ SIGNING_KEY
✓ KEY_ALIAS
✓ KEY_STORE_PASSWORD
✓ KEY_PASSWORD
```

### Can't download APK from release

1. Workflow might still be running (check Actions)
2. Scroll down on Release page to "Assets"
3. If still missing, manually re-run workflow

---

## 📊 What Gets Released

### Signed APK
- **File**: `HiFiMediaPlayer-v2.5.0-release-signed.apk`
- **Size**: ~15-20 MB
- **Installation**: Direct install on Android 8.0+
- **Signature**: Signed with your keystore

### Release Assets
- ✅ Signed APK
- ✅ Release notes
- ✅ Build info
- ✅ Installation instructions

### Artifacts
- ✅ Test reports
- ✅ Lint reports
- ✅ Available for 90 days

---

## 🎓 Understanding the Workflow

### What Happens Automatically

1. **Tag Push Triggers Workflow**
   ```
   git push origin v2.5.0
           ↓
   GitHub detects tag matching v*.*.*
           ↓
   Workflow starts
   ```

2. **Build Process**
   ```
   Checkout code
       ↓
   Setup JDK 17
       ↓
   Build debug APK (validation)
       ↓
   Build release APK
       ↓
   Sign with keystore
       ↓
   Create Release + upload APK
   ```

3. **Parallel Jobs**
   ```
   Build (main)  →  Run tests  
                 →  Run lint
   ```

4. **Release Creation**
   ```
   GitHub Release created
       ↓
   APK attached as asset
       ↓
   Release notes populated
       ↓
   Available for download
   ```

---

## 🏁 Manual Release Process (if needed)

If automated workflow fails, you can manually build and sign:

```bash
cd android-companion

# Build release APK
./gradlew assembleRelease

# Manually sign (if needed)
jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 \
  -keystore HiFiMediaPlayer/hifi-media-player-release.keystore \
  HiFiMediaPlayer/build/outputs/apk/release/HiFiMediaPlayer-release-unsigned.apk \
  hifi-media-player

# Then upload manually to GitHub Release
# GitHub → Releases → Create Release → Upload APK
```

---

## 💡 Tips & Best Practices

### Naming Conventions
- Tags: `v2.5.0` (always start with 'v')
- Branch: `main` (default)
- Release notes: Clear, concise, user-focused

### Testing
- Always test locally first
- Test on real device (4"-7" screens)
- Test network connection to server
- Verify all controls respond

### Documentation
- Update CHANGELOG for major releases
- Include known issues in release notes
- Document breaking changes clearly
- Provide upgrade instructions if needed

### Cadence
- **Patch releases** (v2.5.1): Weekly (bug fixes)
- **Minor releases** (v2.6.0): Monthly (features)
- **Major releases** (v3.0.0): Quarterly (major changes)

---

## 📚 Additional Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [GitHub Releases Guide](https://docs.github.com/en/repositories/releasing-projects-on-github)
- [Android Signing Guide](https://developer.android.com/studio/publish/app-signing)
- [Semantic Versioning](https://semver.org/)

---

## ❓ FAQ

**Q: How long does a release take?**
A: 2-3 minutes from tag push to release completion

**Q: Can I automate beta releases?**
A: Yes, modify workflow to trigger on `v*-beta*` tags

**Q: What if the workflow fails?**
A: Check error logs in GitHub Actions, fix issue, re-run workflow

**Q: Can I release manually without GitHub Actions?**
A: Yes, but automated process is recommended

**Q: Where are old releases stored?**
A: GitHub Releases tab (kept indefinitely)

**Q: Can I delete a release?**
A: Yes, but tag remains in git history

---

**Last Updated**: 2026-06-21  
**Version**: 1.0  
**Status**: Ready for production releases
