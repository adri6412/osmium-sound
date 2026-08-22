# Git Tag & Branch Conventions

How tags trigger the GitHub Actions workflows, and how branches map onto the
appliance's OTA release channels. Workflow details are in [README.md](README.md).

## Tag naming

| What | Format | Triggers | Notes |
|---|---|---|---|
| Appliance (kiosk + system + OS OTA bundles) | `v<MAJOR>.<MINOR>.<PATCH>` | `build-ui-ota.yml` | stable → **prod** channel |
| Appliance dev build | `v<MAJOR>.<MINOR>.<PATCH>-dev.<N>` | `build-ui-ota.yml` (prerelease) | **dev** channel |
| Appliance alpha build | `v<MAJOR>.<MINOR>.<PATCH>-dev.<N>-alpha<M>` | `build-ui-ota.yml` (prerelease) | **alpha** channel only |
| Android companion | `companion-v<MAJOR>.<MINOR>.<PATCH>` | `build-companion-apk.yml` | APK + stable F-Droid repo |
| Android companion dev build | `companion-v<MAJOR>.<MINOR>.<PATCH>-svil<N>` | `build-companion-apk.yml` (prerelease) | APK + dev F-Droid repo |
| Install ISO | *(no tag trigger)* | `build-iso.yml` is manual; it takes the appliance tag as an input | ISO attached to that tag's Release |

`build-ui-ota.yml` ignores any tag containing `companion`; `build-companion-apk.yml`
only fires on `companion-v*`. Tag names are case-sensitive.

## Branches & OTA channels

- **`main` = production.** Stable tags `vX.Y.Z` are cut from here. They publish a
  normal GitHub Release, which the appliance sees via `GET /releases/latest`
  (the **prod** channel, `ota/latest-prod.json`).
- **`svil` = development.** Day-to-day work. Prerelease tags `vX.Y.Z-dev.N` are
  cut from here. Because the tag has a hyphen, `build-ui-ota.yml` marks the
  release as a **prerelease**, which `/releases/latest` ignores — so prod
  devices never receive it. A device set to the **dev** channel
  (Settings → Updates) tracks the newest release *including* prereleases
  (`ota/latest-dev.json`).
- **`alpha` = private, ad hoc.** For trying experimental fixes on your own
  device(s) *before* they're ready to be a shared `-dev.N` build. `alpha` is
  the **only** branch releases are tagged from for this channel (a process
  convention, not a CI-enforced gate — the workflow still only looks at the tag
  name). Tag format is **nested on top of the dev build you started from**: if
  `svil` is at `v2.5.21-dev.118`, your first attempt on `alpha` is
  `v2.5.21-dev.118-alpha1`, the next `-alpha2`, etc. `api_server.py`'s dev
  lookup explicitly excludes any tag matching `-alpha\d+$`, so these never
  reach a `dev`-channel device; the manifest goes to `ota/latest-alpha.json`.
  The **alpha** option only appears in Settings on a device where
  `/etc/hifi-player/ota-alpha-unlocked` exists (`hifi-ota-alpha-toggle.sh enable`
  as root — deliberately not reachable via the network API). Once a fix is
  validated on `alpha`, merge/cherry-pick it into `svil` and cut the next real
  `v2.5.21-dev.119` there for the shared dev channel.
- **`gh-pages`** is generated (website, `ota/` manifests, `fdroid/` repos) —
  never edit it by hand.

Promotion: PR `svil` → `main`, then tag a stable `vX.Y.Z` on `main`.

Versioning stays **patch-incremental**: iterate `v2.5.7-dev.1`, `v2.5.7-dev.2`,
… on `svil`, then promote to the stable `v2.5.7` on `main`. Never jump
versions. Before picking the next number, check `gh release list` rather than
`git tag` alone — a tag can exist without a published Release, and tag dates
are not a reliable ordering.

Keep `main` contained in `alpha`/`svil` (`git merge-base --is-ancestor
origin/main origin/alpha`) before cutting a dev/alpha tag, otherwise the next
prerelease silently re-ships whatever `main` removed.

## Release recipes

### Development build (prerelease, dev channel)

```bash
git checkout svil
# ...commit work...
git push origin svil
git tag -a v2.5.21-dev.119 -m "dev build"
git push origin v2.5.21-dev.119   # → build-ui-ota.yml publishes a PRERELEASE
```

### Alpha build (private — own devices only)

```bash
git checkout alpha
git merge svil                 # stay based on the dev build you're testing against
# ...commit your experimental fix...
git push origin alpha
git tag -a v2.5.21-dev.118-alpha1 -m "alpha: try XYZ fix"
git push origin v2.5.21-dev.118-alpha1   # → PRERELEASE, invisible to the dev channel

# on the device you want to test with (root/SSH, once):
hifi-ota-alpha-toggle.sh enable
# now Settings → Updates shows an "Alpha" option — select it and check for updates
```

### Stable appliance release (prod)

```bash
# 1. bump "version" in package.json on main (surgical one-line edit)
# 2. merge svil → main (PR), then:
git checkout main && git pull
git tag -a v2.5.22 -m "Release v2.5.22"
git push origin v2.5.22
# → build-ui-ota.yml builds + signs UI/System/OS bundles, creates the Release,
#   updates ota/latest-prod.json
# 3. optionally: Actions → "Build HiFi Player ISO (manual)" with tag v2.5.22
#    (gh workflow run build-iso.yml --ref v2.5.22 -f tag=v2.5.22), then publish
#    the ISO + sidecars + latest.json to file.osmiumsound.it
```

Release titles are the bare tag (`v2.5.22`), and the body is the auto-generated
`CHANGELOG_RELEASE.md`.

### Companion app release (Android)

```bash
# 1. Update versionCode (+1) and versionName in
#    android-companion/HiFiMediaPlayer/build.gradle — the versionName must
#    match a case in publishTrack(), or every Gradle build fails.
# 2. Test locally
cd android-companion && bash gradlew clean assembleDebug test lintVitalRelease
# 3. Commit, then tag WITH the companion prefix:
git tag -a companion-v1.0.8 -m "companion 1.0.8: ..."
git push origin companion-v1.0.8
# → build-companion-apk.yml builds + signs the APK, creates the Release,
#   and (stable tags only) updates the F-Droid repo.
# Dev builds from svil: companion-v1.0.8-svil1 → prerelease + dev F-Droid repo.
```

## If you make a mistake

```bash
git tag -d companion-v1.0.8              # delete local tag
git push origin :companion-v1.0.8        # delete remote tag
# recreate and push again
```

A deleted Release whose tag still exists can be recreated by re-running the
workflow run for that tag (`gh run rerun <id>`).

## Monitoring

GitHub → Actions → select the workflow → open the run. If a tag didn't trigger
anything, check that it matches the pattern (`v*` vs `companion-v*`), that it
was actually pushed (`git push origin <tag>` — `--tags` pushes everything, avoid
it), and the workflow's `if:` conditions.

---

**Last updated:** 2026-08-22
