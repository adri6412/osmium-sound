# OS OTA payload (`hifi-os-<ver>.tar.gz`)

This directory is the **source** of the operating-system OTA bundle. Everything
here is tar'd into `hifi-os-<ver>.tar.gz`, signed, and published as a GitHub
Release asset by `.github/workflows/build-ui-ota.yml`. On the appliance,
`Settings → Updates` checks for it and — **only if the signature verifies** —
runs `apply.sh` as root.

## Why a separate channel

| Channel | Asset | What it changes | Verification |
|---|---|---|---|
| UI | `hifi-ui-*.tar.gz` | `/opt/hifi-media-player` (Electron kiosk) | sha256 |
| System | `hifi-system-*.tar.gz` | Python API/daemons (`/usr/local/bin`), helper scripts (`/usr/local/sbin`), systemd units, `/usr/local/share` (LMS skin assets), `/opt/hifi-webui` | sha256 |
| **OS** | **`hifi-os-*.tar.gz`** | **arbitrary, via `apply.sh` as root** | **sha256 + Ed25519 signature** |
| Lyrion | (downloads server) | Lyrion Music Server `.deb` | version match |

Because the OS channel executes an arbitrary root script, sha256 alone is not a
security control (it only proves the download wasn't corrupted). The bundle is
therefore **signed with an offline Ed25519 key**; the appliance carries only the
**public** half at `/etc/hifi-player/ota-pubkey.pem` and refuses to apply
anything that doesn't verify against it. `hifi-os-update.sh` additionally pins
HTTPS, bounds download sizes, validates the sha256/version arguments, extracts
into a private `mktemp -d` under `/var/tmp` with `umask 077`, strips
ownership/permissions on extraction and runs `apply.sh` under `env -i` — see
[ARCHITECTURE.md → OS channel](../../ARCHITECTURE.md#os-channel--why-its-signed).

## Bundle layout

| Path | Role |
|---|---|
| [`apply.sh`](apply.sh) | **runner** — sources `lib.sh`, runs every `apply.d/NNNN-*.sh` in order, each in an isolated subshell; fail-fast; writes an audit ledger to `/var/lib/hifi-player/os-migrations`. Don't put OS changes here. |
| [`lib.sh`](lib.sh) | shared POSIX helpers: `ensure_file_content`, `backup_and_edit` (validator + automatic restore), `ensure_pkg`, `mark_changed`, `request_reboot`, … |
| `apply.d/NNNN-*.sh` | the actual migrations, one concern each, run in numeric order (currently 0001 → 0052) |
| `files/` | data shipped with the bundle, read by migrations via `$HIFI_PAYLOAD_DIR/files/…`: `xsession` (X11 kiosk session), `kiosk-wayland-session` / `kiosk-wayland-launch` / `hifi-kiosk-wayland.desktop` (Wayland kiosk), `kiosk-session-select` + `hifi-kiosk-session.service` (Wayland-vs-X11 choice), `hifi-player-tmpfiles.conf`, `hifi-fix-efi-boot.sh`, `logo.png`. These are the **single source of truth** — `build-distro.sh` injects the very same files into new images. |
| `OS_VERSION` | version marker written to `/etc/hifi-player/OS_VERSION` by the updater (the tag is what the device compares against) |

## How it is applied on the device

`hifi-os-update.sh` (and likewise `hifi-ota-update.sh` / `hifi-system-update.sh`)
has three subcommands:

- `stage <url> <sha256> [<sig_url>] <version>` — download + verify into a
  persistent dir under `/var/lib/hifi-player/update/staged/<channel>/<version>`;
  never touches the running system.
- `apply <staged_dir> <version>` — run an already-verified payload. Used by the
  combined "Update now": `hifi-update-stage-runner.sh` stages every channel
  live, creates `/system-update` and reboots; `hifi-update-apply-runner.sh`
  then runs inside `system-update.target` (nothing else from the app stack is
  started) and applies system → os → ui in one pass, with progress on the
  Plymouth splash. The reboot marker is ignored here — the isolated session
  reboots exactly once at the end.
- `full …` — the original single-shot download+verify+apply, still used by the
  single-component `/os_update/apply` endpoint; honours the `REBOOT` marker
  only after `OS_VERSION` is written.

`OS_VERSION` is written only after **every** migration succeeded; a failed or
interrupted run leaves the old version in place and the next attempt re-runs
the whole payload from the top — which is safe because every migration is
idempotent.

## Authoring an OS update

1. **Add a new** `apply.d/NNNN-*.sh` (next free number) — never edit or delete an
   existing migration. This channel is **cumulative**: the updater only fetches
   the *latest* release and runs it once, so every change ever shipped must still
   be present and a device can jump from any old version to the newest in one
   pass. Inside the migration:
   - use the `lib.sh` helpers so it is **idempotent** and a **clean no-op** when
     already applied (they only act, and only `mark_changed`, on a real diff);
   - call `request_reboot` **only** after a real change that needs a reboot — the
     payload re-runs on every release, so an unconditional reboot would reboot
     the box on every update;
   - ship any data files under `files/` and read them via `$HIFI_PAYLOAD_DIR`;
   - **never touch the bootloader** (`grub-install`, shim, Secure Boot) from
     here — on a headless fleet that can leave a unit at the `grub>` prompt
     with no way back in (`0010-secure-boot.sh` is deliberately a no-op).
2. **Undoing a shipped change:** a shipped migration can be neither deleted nor
   left fighting the removal. Empty the old one into a documented **tombstone**
   and add a new, presence-gated removal migration (e.g. `0044-beta-agent.sh`
   → `0052-remove-beta-agent.sh`). Many migrations are tombstones already.
3. **A System-bundle change that must reach devices on the very next update**
   (e.g. a new install path in `hifi-system-update.sh`, which re-execs its
   *old* copy) goes through an OS migration as the bridge — `0048-lms-skin-assets.sh`
   is the worked example.
4. Tag the repo `vX.Y.Z[-dev.N[-alphaM]]`. CI **shellchecks** the payload and
   runs an **idempotency test** (apply.sh twice → second run must be
   `changed=0`, no reboot) before it builds, signs, and publishes the bundle
   (see [`.github/workflows/build-ui-ota.yml`](../../.github/workflows/build-ui-ota.yml)).

## Signing key

See [`../ota-keys/README.md`](../ota-keys/README.md) for generating the keypair,
storing the private key as the `OTA_SIGNING_KEY` GitHub secret, baking the
public key into the image, and enrolling a different key on a running device.
