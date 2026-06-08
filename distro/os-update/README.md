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

## Authoring an OS update

1. Edit [`apply.sh`](apply.sh) — make it **idempotent**, exit non-zero on
   failure, and `: > "$HIFI_PAYLOAD_DIR/REBOOT"` if a reboot is required. Ship
   extra files next to it (e.g. `files/foo.conf`) and install them from
   `apply.sh` using `$HIFI_PAYLOAD_DIR`.
2. Bump `OS_VERSION` and tag the repo `vX.Y.Z`. CI builds, signs, and publishes
   the bundle (see [`.github/workflows/build-ui-ota.yml`](../../.github/workflows/build-ui-ota.yml)).

## Signing key

See [`../ota-keys/README.md`](../ota-keys/README.md) for generating the keypair,
storing the private key as the `OTA_SIGNING_KEY` GitHub secret, and baking the
public key into the image.
