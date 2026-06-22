# OS OTA payload (`hifi-os-<ver>.tar.gz`)

This directory is the **source** of the operating-system OTA bundle. Everything
here is tar'd into `hifi-os-<ver>.tar.gz`, signed, and published as a GitHub
Release asset. On the appliance, `Settings → Aggiornamenti` checks for it and —
**only if the signature verifies** — runs `apply.sh` as root.

## Why a separate channel

| Channel | Asset | What it changes | Verification |
|---|---|---|---|
| UI | `hifi-ui-*.tar.gz` | `/opt/hifi-media-player` (Electron) | sha256 |
| System | `hifi-system-*.tar.gz` | Python API/daemons, helper scripts, units | sha256 |
| **OS** | **`hifi-os-*.tar.gz`** | **arbitrary, via `apply.sh` as root** | **sha256 + Ed25519 signature** |

Because the OS channel executes an arbitrary root script, sha256 alone is not a
security control (it only proves the download wasn't corrupted). The bundle is
therefore **signed with an offline Ed25519 key**; the appliance carries only the
**public** half at `/etc/hifi-player/ota-pubkey.pem` and refuses to apply
anything that doesn't verify against it.

## Bundle layout

| Path | Role |
|---|---|
| [`apply.sh`](apply.sh) | **runner** — sources `lib.sh`, runs every `apply.d/NNNN-*.sh` in order, each in an isolated subshell; writes an audit ledger to `/var/lib/hifi-player/os-migrations`. Don't put OS changes here. |
| [`lib.sh`](lib.sh) | shared POSIX helpers: `ensure_file_content`, `backup_and_edit`, `ensure_pkg`, `mark_changed`, `request_reboot`, … |
| `apply.d/NNNN-*.sh` | the actual migrations, one concern each, run in numeric order |
| `files/` | data shipped with the bundle (e.g. `files/xsession`); migrations read them from `$HIFI_PAYLOAD_DIR/files/…` |

## Authoring an OS update

1. **Add a new** `apply.d/NNNN-*.sh` (next free number) — never edit or delete an
   existing migration. This channel is **cumulative**: the updater only fetches
   the *latest* release and runs it once, so every change ever shipped must still
   be present. Inside the migration:
   - use the `lib.sh` helpers so it is **idempotent** and a **clean no-op** when
     already applied (they only act, and only `mark_changed`, on a real diff);
   - call `request_reboot` **only** after a real change that needs a reboot — the
     payload re-runs on every release, so an unconditional reboot would reboot
     the box on every update;
   - ship any data files under `files/` and read them via `$HIFI_PAYLOAD_DIR`.
2. Bump `OS_VERSION` and tag the repo `vX.Y.Z`. CI **shellchecks** the payload and
   runs an **idempotency test** (apply.sh twice → second run must be
   `changed=0`, no reboot) before it builds, signs, and publishes the bundle
   (see [`.github/workflows/build-ui-ota.yml`](../../.github/workflows/build-ui-ota.yml)).

## Signing key

See [`../ota-keys/README.md`](../ota-keys/README.md) for generating the keypair,
storing the private key as the `OTA_SIGNING_KEY` GitHub secret, and baking the
public key into the image.
