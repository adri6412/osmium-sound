# GitHub Actions Workflows

CI for the whole Osmium Sound repository: appliance releases (OTA bundles),
the install ISO, the Android companion app, Osmium Flasher, the website and
storage housekeeping. Tag/branch conventions and the release channels are in
[TAG_CONVENTIONS.md](TAG_CONVENTIONS.md).

| Workflow | Trigger | Produces |
|---|---|---|
| [`build-ui-ota.yml`](build-ui-ota.yml) | push of a `v*` tag (not `companion-*`); manual | OTA bundles `hifi-ui-`, `hifi-system-`, `hifi-os-` (+ sha256, OS signature), offline dev installer, GitHub Release, OTA manifest on `gh-pages` |
| [`build-iso.yml`](build-iso.yml) | manual (`workflow_dispatch`, tag as input) | `hifi-player-<tag>.iso` + `.sha256` + `.sha256.sig` + `latest.json` (artifact; optionally attached to the Release) |
| [`build-companion-apk.yml`](build-companion-apk.yml) | push of a `companion-v*` tag; manual | signed APK, GitHub Release, unit-test/lint reports, self-hosted F-Droid repos on `gh-pages` |
| [`build-flasher.yml`](build-flasher.yml) | manual | Osmium Flasher binaries (Windows `.exe`, Linux `.run`) as artifacts |
| [`deploy-pages.yml`](deploy-pages.yml) | push to `main` touching `website/**`; manual | pushes `website/` to the `gh-pages` branch (served by Cloudflare Pages as osmiumsound.it) |
| [`cleanup-actions-storage.yml`](cleanup-actions-storage.yml), [`Clean.yml`](Clean.yml) | manual | delete Actions caches / artifacts to free storage |

Helper scripts live in [`../scripts/`](../scripts/): `make-ota-manifest.py`
(OTA manifest for `gh-pages`) and `make-iso-manifest.py` (`latest.json` for
the flasher). The repo-root [`tools/publish-iso.sh`](../../tools/publish-iso.sh)
reproduces the ISO signing + manifest step by hand for an ISO already on disk.

---

## `build-ui-ota.yml` — appliance release (OTA bundles)

**Trigger:** push of any tag matching `v*` whose name does not contain
`companion` (stable `vX.Y.Z`, dev `vX.Y.Z-dev.N`, alpha `vX.Y.Z-dev.N-alphaM`),
or a manual run (artifacts only, no Release).

**Steps, in order:**

1. Node 20 → `npm ci` → `npm run build` + `electron-builder --linux dir`
   (the kiosk, `dist/linux-unpacked`).
2. Builds the web admin (`admin-webui/`, Vue) — it ships inside the **system**
   bundle, not the UI one.
3. Resolves the version (the tag name) and generates `CHANGELOG_RELEASE.md`
   from the commit log since the previous Release (`git log --no-merges`,
   `chore(release)` commits filtered out). This becomes the Release body and
   the "what's new" text shown by the Updates screens.
4. Packages `hifi-ui-<ver>.tar.gz` (+ `.sha256`).
5. Packages `hifi-system-<ver>.tar.gz` (+ `.sha256`): the Python services,
   `/usr/local/sbin` helper scripts, systemd units, `/usr/local/share` data
   (LMS skin assets) and `/opt/hifi-webui/dist`.
6. Runs the Python unit tests (`tests/`, update sequencer + settings).
7. Stages the LMS skin assets into the OS payload, then **shellchecks
   `distro/os-update/apply.sh` + `apply.d/*` and runs the payload twice** in a
   throwaway root: the second run must report `changed=0` and request no reboot
   (the idempotency contract — see `distro/os-update/README.md`).
8. Packages `hifi-os-<ver>.tar.gz` + `.sha256` and **signs the sidecar with
   Ed25519** using the `OTA_SIGNING_KEY` secret → `hifi-os-<ver>.tar.gz.sha256.sig`.
   Without the secret the bundle ships unsigned and every device refuses it.
9. Generates the offline dev installer `hifi-install-<ver>.sh`
   (`distro/dev-installer/install.sh.tmpl`): applies the same bundles over
   SSH, bypassing the rate-limited GitHub REST API during heavy dev iteration.
10. Publishes everything to the GitHub Release for the tag.
    `prerelease: ${{ contains(github.ref_name, '-') }}` — any tag with a hyphen
    (`-dev.N`, `-alphaM`) is a **prerelease**, which `/releases/latest` ignores,
    so prod devices never see it.
11. Builds the OTA manifest (`ota/latest-prod.json` for a stable tag,
    `ota/latest-dev.json` / `latest-alpha.json` for prereleases — see
    `make-ota-manifest.py`) and pushes it to the `gh-pages` branch under
    `ota/` with `keep_files: true` (so the website and the F-Droid repos on the
    same branch are untouched). Devices read it from the Cloudflare Pages
    origin first and fall back to the GitHub REST API.

**Secrets:** `OTA_SIGNING_KEY` (Ed25519 private key PEM, see
`distro/ota-keys/README.md`), `GITHUB_TOKEN` (automatic).

---

## `build-iso.yml` — install ISO (manual)

Runs inside a `debian:bookworm` container (live-build/debootstrap) and builds
the **trixie** appliance image by default.

**Inputs:** `tag` (required, e.g. `v2.5.21`), `make_release` (default true:
create the tag if missing and attach the ISO to its Release — prerelease when
the tag has a hyphen), `lyrion_url` (override the Lyrion `.deb` URL),
`suite` (default `trixie`).

**Steps:** build the kiosk and the web admin → `distro/build-distro.sh --app-dir … --app-version <tag> --suite <suite>` as root → `hifi-player-<tag>.iso` → sha256 + **Ed25519 signature of the `.sha256` sidecar** (same key as the OS channel) → `latest.json` (`make-iso-manifest.py`, the manifest Osmium Flasher polls) → artifact `hifi-player-iso-<tag>` → optional Release upload.

The ISO itself is **not** served from GitHub to end users: the published image,
its sidecars and `latest.json` are uploaded to **file.osmiumsound.it** (the
flasher reads `https://file.osmiumsound.it/latest.json`). `tools/publish-iso.sh`
produces that exact set of files by hand when needed.

> ⚠️ `gh workflow run build-iso.yml` needs an explicit `--ref <tag-or-branch>`;
> without it the run builds from `main` regardless of the `tag` input.

**Secrets:** `OTA_SIGNING_KEY`, `GITHUB_TOKEN`.

---

## `build-companion-apk.yml` — Android companion

**Trigger:** push of a `companion-v*` tag (stable `companion-vX.Y.Z`, dev
`companion-vX.Y.Z-svilN`), or manual.

**Jobs:**

- **build** — JDK 17, decodes the keystore from `SIGNING_KEY`, builds and
  signs the release APK (`KEY_ALIAS`, `KEY_STORE_PASSWORD`, `KEY_PASSWORD`),
  derives the version from the tag, creates the GitHub Release (prerelease for
  `-svil`/`-beta` tags) with the APK attached, uploads the APK as an artifact.
- **test** / **lint** — `gradlew test` and `gradlew lint`, reports uploaded as
  artifacts.
- **fdroid-repo** — only for **stable** tags (`!contains(ref, '-svil') &&
  !contains(ref, '-beta')`): installs `fdroidserver`, fetches the current repo
  state from `gh-pages`, adds the new APK, signs the index with the dedicated
  repo keystore (`FDROID_REPO_KEYSTORE`, `FDROID_REPO_KEYSTORE_PASSWORD` —
  separate from the APK signing key), publishes `fdroid/repo` back to
  `gh-pages` (`keep_files`). Public URL: `https://osmiumsound.it/fdroid/repo`.
- **fdroid-dev-repo** — only for `-svilN` tags: same, into `fdroid/dev/repo`
  (`https://osmiumsound.it/fdroid/dev/repo`), mirroring the app metadata from
  the stable repo.

The Gradle `publishTrack()` helper in `HiFiMediaPlayer/build.gradle` validates
the `versionName` format (`X.Y.Z`, `X.Y.Z-beta-N`, …) — an unexpected format
fails **every** Gradle build, so add a case there before inventing a new scheme.

**Secrets:** `SIGNING_KEY` (base64 keystore), `KEY_ALIAS`, `KEY_STORE_PASSWORD`,
`KEY_PASSWORD`, `FDROID_REPO_KEYSTORE`, `FDROID_REPO_KEYSTORE_PASSWORD`,
`GITHUB_TOKEN`.

### One-time keystore setup

```bash
# APK signing key (once)
keytool -genkey -v -keystore osmium-companion-release.keystore \
  -keyalg RSA -keysize 2048 -validity 10000 -alias hifi-media-player
base64 -w 0 osmium-companion-release.keystore   # → SIGNING_KEY secret
```

Add `SIGNING_KEY`, `KEY_ALIAS`, `KEY_STORE_PASSWORD`, `KEY_PASSWORD` under
**Settings → Secrets and variables → Actions**. The F-Droid index key is a
separate PKCS12 keystore (alias `osmium-sound-fdroid`) stored as
`FDROID_REPO_KEYSTORE` (base64) + `FDROID_REPO_KEYSTORE_PASSWORD`; the
workflow appends the password to a checked-out copy of `fdroid/config.yml`
right before `fdroid update` (fdroidserver reads it only from that file — never
commit the mutated file).

---

## `build-flasher.yml` — Osmium Flasher (manual)

Builds the desktop USB writer from `flasher/` on a matrix of `ubuntu-latest`
(→ self-extracting `Osmium-Flasher-<ver>-linux-x86_64.run`, wrapped by
`flasher/build/make-selfextract.sh`) and `windows-latest` (→ `.exe`), Node 22,
after `npm test`. Optional input `version` stamps `package.json` before
building. macOS is configured in `electron-builder.yml` but disabled in CI until
the app is notarized. Artifacts (14-day retention) are uploaded by hand to
file.osmiumsound.it; the binaries are unsigned.

---

## `deploy-pages.yml` — website

On push to `main` touching `website/**` (or manual), pushes the contents of
`website/` to the `gh-pages` branch (`keep_files: true`, so `ota/` and
`fdroid/` published there by the other workflows survive). The public site
**osmiumsound.it** is served by Cloudflare Pages watching that branch —
GitHub Pages itself is not in the loop. Changes on `svil`/`alpha` alone never
deploy.

---

## Housekeeping

`cleanup-actions-storage.yml` (inputs to choose what to delete) and the older
`Clean.yml` delete Actions caches and artifacts when storage fills up. Manual
only.

---

## Troubleshooting

- **A release shows no OS signature / devices refuse the OS update** — the
  `OTA_SIGNING_KEY` secret is missing or doesn't match the public key baked
  into the image (`distro/ota-keys/ota-pubkey.pem`).
- **A device doesn't see a release just published** — the OTA manifest on the
  Pages origin is CDN-cached for ~10 minutes; the device falls back to the
  GitHub API only when the manifest is unreachable, not when it is stale.
- **`gh pr merge` fails on a PR that touches `.github/workflows/*`** — the
  local `gh` token lacks the `workflow` scope: `gh auth refresh -s workflow`.
- **Retrying a failed Pages/OTA deploy** — delete the leftover duplicate
  `github-pages` artifacts of the failed run before re-running, or the redeploy
  fails again.
- **Companion build fails at configuration time** — check `versionName`
  against `publishTrack()`; and when removing a base string, remove it from
  every `values-XX/strings.xml` too (`lintVitalRelease` fails only on release
  builds).

---

**Last updated:** 2026-08-22
