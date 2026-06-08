# OTA signing keys

The OS OTA channel (`hifi-os-*.tar.gz`) runs an arbitrary root script on the
appliance, so every bundle must be **signed**. This is an Ed25519 keypair:

- **private key** — held only in CI as the GitHub secret `OTA_SIGNING_KEY`,
  plus an offline backup. It signs the bundle's sha256 sidecar at release time.
- **public key** — baked into the image at
  `/etc/hifi-player/ota-pubkey.pem`. The appliance verifies every OS bundle
  against it and refuses to apply anything that doesn't match.

## One-time setup

```sh
cd distro/ota-keys
./gen-ota-key.sh

# bake the public key into the image
cp ota-pubkey.pem ../config/includes.chroot/etc/hifi-player/ota-pubkey.pem

# give CI the private key
gh secret set OTA_SIGNING_KEY < ota-signing-key.pem
```

Rebuild the ISO so installed devices carry the public key. The **private key**
(`ota-signing-key.pem`) is git-ignored — keep it offline and never commit it.

## How verification works on the device

`/usr/local/sbin/hifi-os-update.sh`:

1. downloads `hifi-os-<ver>.tar.gz` and the detached signature
   `hifi-os-<ver>.tar.gz.sha256.sig`;
2. reconstructs the signed sha256 sidecar and verifies the signature with
   `openssl pkeyutl -verify` against `ota-pubkey.pem` → **authenticity**;
3. checks the tarball's sha256 against that signed digest → **integrity**;
4. only then extracts and runs `apply.sh`.

If the public key is missing, `openssl` is unavailable, or the signature fails,
the update is rejected and `apply.sh` never runs.

## Owning the trust root on a running device (no re-image)

Baking the key at build time is the convenient path, but it is **not** the only
one: the device owner can point the OTA channel at their *own* signing key at
runtime, so a fork/self-hoster is never locked into anyone else's key. On the
device, as root:

```sh
# from a file, a URL, or stdin
hifi-ota-enroll-key.sh /path/to/my-ota-pubkey.pem
hifi-ota-enroll-key.sh https://example.org/my-ota-pubkey.pem
cat my-ota-pubkey.pem | hifi-ota-enroll-key.sh -
```

It validates the key is a real Ed25519 public key, backs up the previous one to
`ota-pubkey.pem.bak`, installs it atomically, and prints a fingerprint. From
then on the device only trusts OS bundles signed with the matching private key.

This is intentionally a **root-only, local** command (console / SSH) and is
**not** exposed over the network API: whoever can set the trust root can
authorise arbitrary signed root scripts, so it must require physical/root access
— not a request any LAN client can make. This is what keeps the design
verified-but-not-tivoised: the owner controls the trust root, the device isn't
locked, yet the auto-update path is still authenticated.

## Key rotation

If the private key leaks or is lost: run `gen-ota-key.sh` again (after deleting
the old `ota-signing-key.pem`), update the `OTA_SIGNING_KEY` secret, copy the new
public key into the image, and ship a new ISO. Devices still on the old image
will only trust bundles signed with the old key until they're re-imaged.
