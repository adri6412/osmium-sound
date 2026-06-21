# GitHub Actions Workflows

This directory contains automated workflows for building and releasing the HiFi Media Player Companion Android app.

## 🚀 Workflows

### `build-companion-apk.yml`

Automatically builds and releases the APK when a version tag is pushed.

**Trigger Events**:
- Push of git tag matching `v*.*.*` (e.g., `v2.5.0`)
- Manual trigger via GitHub UI (Workflow Dispatch)

**What it does**:
1. Checks out source code
2. Sets up JDK 17
3. Builds debug APK (for validation)
4. Builds release APK (unsigned)
5. Signs the release APK with your keystore
6. Creates GitHub Release with APK attached
7. Uploads APK as workflow artifact
8. Runs unit tests and lint checks

**Outputs**:
- ✅ Signed release APK
- ✅ GitHub Release with release notes
- ✅ Test reports
- ✅ Lint reports
- ✅ Artifacts available for 90 days

---

## 🔐 Setup Instructions

### Step 1: Generate Signing Keystore

Create a signing key for release builds:

```bash
cd android-companion/HiFiMediaPlayer

# Generate keystore (one-time)
keytool -genkey -v -keystore hifi-media-player-release.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -alias hifi-media-player \
  -dname "CN=Your Name, O=Your Organization, L=City, ST=State, C=Country"
```

**Save the passwords securely!**

### Step 2: Encode Keystore for GitHub Secrets

```bash
cd android-companion/HiFiMediaPlayer

# Encode keystore in base64
base64 -w 0 hifi-media-player-release.keystore > keystore.base64

# Output the base64 string
cat keystore.base64
```

Copy the entire output.

### Step 3: Add GitHub Secrets

Go to your repository settings:

**GitHub → Settings → Secrets and variables → Actions**

Add these secrets:

| Secret Name | Value | Example |
|---|---|---|
| `SIGNING_KEY` | Base64-encoded keystore (from step 2) | `MIIJrAIB...` |
| `KEY_ALIAS` | Alias used in keystore | `hifi-media-player` |
| `KEY_STORE_PASSWORD` | Keystore password | `(your password)` |
| `KEY_PASSWORD` | Key password | `(your password)` |

**⚠️ Important**: Keep these passwords secure! Never commit them to git.

### Step 4: Verify Secrets

To test that secrets are configured correctly:

```bash
# Trigger a manual workflow run
# GitHub → Actions → Build HiFi Media Player Companion APK → Run workflow
```

---

## 📱 Creating a Release

### Method 1: Create Git Tag (Automatic Trigger)

```bash
# From project root
git tag -a v2.5.0 -m "Release version 2.5.0"
git push origin v2.5.0
```

Workflow will automatically:
1. Start building
2. Generate APK
3. Sign APK
4. Create GitHub Release
5. Upload APK
6. Run tests

### Method 2: Manual Trigger

1. Go to **GitHub → Actions**
2. Select **Build HiFi Media Player Companion APK**
3. Click **Run workflow**
4. Workflow runs with latest commit on main branch

---

## 📊 Workflow Details

### Build Job

```
checkout code
    ↓
setup JDK 17
    ↓
build debug APK (validation)
    ↓
build release APK (unsigned)
    ↓
sign release APK (using secrets)
    ↓
create GitHub Release
    ↓
upload artifacts (90 day retention)
```

### Test Job

Runs unit tests on Android code:
- Located in: `android-companion/HiFiMediaPlayer/src/androidTest/`
- Report: `HiFiMediaPlayer/build/reports/tests/`

### Lint Job

Runs Android lint checks:
- Checks code quality and style
- Report: `HiFiMediaPlayer/build/reports/lint/`

---

## 📋 Release Notes Template

When the workflow creates a GitHub Release, it automatically includes:

```markdown
# HiFi Media Player Companion v2.5.0

## Release Notes

### Features
- Desktop-inspired mobile UI
- Dark theme with gold accents
- Tab-based navigation
- Large play/pause control
- Volume control with visual feedback
- Responsive layout for 4"-7" screens

### Build Information
- AGP Version: 8.5.1
- Gradle Version: 8.8
- Compile SDK: 35 (Android 15)
- Target SDK: 35 (Android 15)
- Min SDK: 26 (Android 8.0)

### Installation
1. Download the APK file
2. Enable "Unknown Sources" in Settings → Security
3. Open the APK and install

### Requirements
- Android 8.0 or higher
- Local network connection to HiFi Media Player server
```

You can customize this in the workflow file: `.github/workflows/build-companion-apk.yml`

---

## 📥 Downloading APKs

### From GitHub Release

1. Go to **GitHub → Releases**
2. Find the release (e.g., `v2.5.0`)
3. Download the APK under "Assets"

### From Workflow Artifacts

1. Go to **GitHub → Actions**
2. Click the workflow run
3. Scroll to "Artifacts"
4. Download `HiFiMediaPlayer-APK`

---

## 🔧 Troubleshooting

### Workflow fails: "Signing key not found"

**Cause**: `SIGNING_KEY` secret not configured

**Solution**:
1. Follow Step 1-3 above
2. Verify secret is in: Settings → Secrets and variables → Actions
3. Re-run workflow

### Error: "Invalid keystore format"

**Cause**: Base64 encoding error

**Solution**:
```bash
# Re-encode keystore
base64 -w 0 hifi-media-player-release.keystore | pbcopy  # Mac
base64 -w 0 hifi-media-player-release.keystore | xclip   # Linux
# Windows: use Python or online base64 encoder
python -m base64 hifi-media-player-release.keystore
```

### Workflow times out

**Cause**: Gradle download is slow

**Solution**:
- Increase timeout in workflow (edit `.github/workflows/build-companion-apk.yml`)
- Check network connectivity

### APK not signed

**Cause**: Signing failed silently

**Solution**:
1. Verify all 4 secrets are set
2. Check password accuracy (spaces, special chars)
3. Manually build and sign locally first:
   ```bash
   cd android-companion
   ./gradlew assembleRelease
   ```

---

## 🎯 Best Practices

### Version Tags

Use semantic versioning:
- `v2.5.0` - Release version
- `v2.5.1-beta.1` - Beta release
- `v2.5.0-rc.1` - Release candidate

### Release Notes

Update release notes for each version with:
- New features
- Bug fixes
- Breaking changes (if any)
- Upgrade instructions

### Testing Before Release

Before pushing a tag:
```bash
cd android-companion
./gradlew clean assembleDebug    # Build debug
./gradlew test                    # Run tests
./gradlew lint                    # Run lint
```

### Keystore Backup

Keep your keystore file safe:
- ✅ Store in secure location
- ✅ Make encrypted backup
- ✅ Never commit to git
- ❌ Don't lose password
- ❌ Don't share with untrusted sources

If you lose the keystore, you'll need to:
1. Create a new keystore
2. Update secrets in GitHub
3. Update signing config in `build.gradle`
4. Next release will use new key

---

## 📚 Resources

### GitHub Actions
- [Creating workflows](https://docs.github.com/en/actions/quickstart)
- [Secrets and variables](https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions)
- [Release management](https://docs.github.com/en/repositories/releasing-projects-on-github)

### Android Build System
- [Gradle signing](https://developer.android.com/studio/publish/app-signing)
- [Release builds](https://developer.android.com/studio/build#release-variants)
- [Build configuration](https://developer.android.com/studio/build)

### Signing APKs
- [Android official guide](https://developer.android.com/studio/publish/app-signing)
- [Keystore generation](https://developer.android.com/studio/publish/app-signing#generate-key)

---

## 🆘 Support

### Debug Workflow Issues

1. Check workflow run logs: **Actions → Workflow run → Job logs**
2. Look for error messages in the build log
3. Common issues:
   - Missing secrets
   - Invalid JDK version
   - Gradle download timeout
   - Signing key mismatch

### Local Testing

Test the build locally first:
```bash
cd android-companion
./gradlew clean
./gradlew assembleDebug
./gradlew assembleRelease
```

If this works locally, the workflow should work too.

---

## ✅ Checklist for First Release

- [ ] Generate signing keystore (step 1)
- [ ] Encode keystore to base64 (step 2)
- [ ] Add 4 secrets to GitHub (step 3)
- [ ] Test workflow with manual trigger (method 2)
- [ ] Verify APK is signed
- [ ] Verify APK installs on device
- [ ] Push version tag (step method 1)
- [ ] Check GitHub Releases for APK
- [ ] Verify release notes
- [ ] Test APK from release download

---

**Last Updated**: 2026-06-21  
**Workflow Version**: 1.0  
**Maintained By**: HiFi Audio Team
