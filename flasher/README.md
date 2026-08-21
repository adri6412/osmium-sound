# Osmium Flasher

Desktop app that writes the Osmium Sound installer image to a USB stick.
Downloaded by beta testers from the beta page; it is not part of the appliance
and never runs on the device itself.

Doing this from the browser is not possible: WebUSB refuses to claim
mass-storage interfaces, and the File System Access API only reaches mounted
volumes, never a raw block device. Hence a native app.

## What it does

1. Reads `https://file.osmiumsound.it/latest.json` to find the current image.
2. Verifies the Ed25519 signature over the `.sha256` sidecar with the OTA public
   key in `assets/ota-pubkey.pem`, then checks the image against the digest that
   sidecar carries. **An unsigned image is refused**, unlike OS OTA bundles where
   an unsigned build merely warns.
3. Downloads to a cache in the app's userData dir, resuming an interrupted
   transfer with a Range request instead of refetching a gigabyte.
4. Writes the image raw to the chosen stick and reads it back to verify.

## Layout

| Path | Role |
|---|---|
| `src/main.js` | Electron main: IPC, orchestration. Never elevated. |
| `src/image.js` | Manifest, download/resume, signature and checksum. |
| `src/drives.js` | Removable-drive discovery; system disks excluded at the adapter. |
| `src/elevate.js` | Spawns the helper with sudo-prompt, tails its progress file. |
| `helper/writer.js` | Runs as root/Administrator; the only code that touches the device. |
| `src/renderer.js` | UI and the en/it dictionary. No Node access. |

The GUI stays unprivileged for its whole life — only `helper/writer.js` is
elevated, and it is spawned on Electron's own binary via `ELECTRON_RUN_AS_NODE`
so the native addons keep the right ABI.

### Two platform traps, already handled

- **sudo-prompt buffers stdout** rather than streaming it, so progress travels
  through a temp JSON-lines file that the GUI tails. Do not "simplify" this back
  to stdout.
- **sudo-prompt's `options.env` does not reach the elevated process on Linux**:
  it emits the exports *before* `pkexec`, which then scrubs the environment. On
  POSIX the variable is therefore also inlined into the command itself. Windows
  and macOS put the exports inside the elevated script, so they are fine.

And one that dictated the packaging: the Linux build is a **tar.gz, not an
AppImage**. An AppImage is mounted over FUSE by the unprivileged user, and FUSE
denies access to every other user — root included — unless `user_allow_other` is
set in `/etc/fuse.conf`. `pkexec` could never reach the helper inside the mount.

## Development

```sh
npm install
npm start          # run the app
npm test           # trust chain + UI checks, no display needed
```

`npm test` is hermetic: the trust-chain fixtures are signed with a throwaway
Ed25519 keypair generated at run time, so the suite is green on CI and on a
fresh clone alike. One further test signs with the real
`distro/ota-keys/ota-signing-key.pem` and checks the result against the shipped
`assets/ota-pubkey.pem` — that is what would catch the two drifting apart, which
would make the flasher refuse every release. It skips wherever that key is
absent, which is everywhere except a maintainer's machine.

### Testing a write without a USB stick

```sh
truncate -s 8G /tmp/fake-usb.img
sudo losetup -f --show /tmp/fake-usb.img        # → /dev/loopN
# select /dev/loopN in the app, then:
cmp -n $(stat -c%s image.iso) /tmp/fake-usb.img image.iso   # must be silent
qemu-system-x86_64 -bios /usr/share/OVMF/OVMF_CODE.fd \
  -drive file=/tmp/fake-usb.img,format=raw -m 2048          # must reach the boot menu
```

Note that a loop device is not removable, so it only appears in the list if you
temporarily flip `includeVirtualDrives` in `src/drives.js`.

## Releasing

1. Bump `version` in `package.json`.
2. Actions → **Build Osmium Flasher (manual)** → Run workflow.
   Pass `--ref` explicitly if dispatching from the CLI: without it, `gh` builds
   from `main` regardless of what you meant.
3. Download the four artifacts (win-x64, mac-arm64, mac-x64, linux-x86_64).
4. Upload them to `file.osmiumsound.it`, alongside the ISO.
5. Update the filenames in `website/beta/index.html` — they are versioned, so a
   new flasher version means four new URLs.

The binaries are unsigned. The beta page carries the per-OS instructions for the
resulting warnings; if signing is ever added, those instructions have to go.
