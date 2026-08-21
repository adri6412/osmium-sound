# Osmium Flasher

Desktop app that walks a beta tester through installing Osmium Sound on a mini
PC, end to end. Downloaded from the beta page; it is not part of the appliance
and never runs on the device itself.

Three phases, shown as a stepper across the top:

1. **USB stick** — fetch the current image, verify it, write it to the stick.
2. **Boot** — how to get the mini PC to start from that stick.
3. **Install** — how to drive the on-device installer through to first boot.

Only the first phase is something the app *does*; the other two happen on the
other machine and are instructions. They are in here because stopping at "the
stick is ready" is exactly where people got stranded. Their wording tracks the
install section of `website/beta/manual.html` — change them together.

Doing this from the browser is not possible: WebUSB refuses to claim
mass-storage interfaces, and the File System Access API only reaches mounted
volumes, never a raw block device. Hence a native app.

## Which drives are offered

A Mac once listed its own boot disk as a target: a 4 TB internal NVMe mounted at
`/Volumes/Macintosh_HD`, with drivelist's system flag clear. On macOS the boot
volume sits on a synthesised APFS container, which the detection does not always
recognise, and a virtual machine confuses it further.

`helper/drive-safety.js` therefore inverts the question. Instead of trying to
recognise the disks that must be excluded, it admits only those that positively
look detachable — removable, USB or card — and refuses anything mounted at a
path that belongs to a running system. An internal disk answers to none of
those. Erring towards permissive destroys a computer; erring towards strict
means a stick is not listed and somebody tells us.

Disk images — attached with `hdiutil attach -removable` on macOS, or `losetup`
on Linux — are excluded too, being virtual devices. They are also the only way
to exercise the write path without real hardware, so there is an opt-in:

```sh
OSMIUM_FLASHER_ALLOW_VIRTUAL=1 "/Applications/Osmium Flasher.app/Contents/MacOS/Osmium Flasher"
```

It relaxes that one condition and nothing else: a system disk, or anything
mounted where a system lives, stays refused. There is deliberately no setting
for it in the interface.

The interface and the elevated writer call the same function, and a test asserts
they both still do: by the time the writer runs it holds root and the device path
reached it as an argument, so it re-checks rather than trusting the list.

## Restoring a stick

The welcome screen also offers to put a stick back to factory condition: a
single empty FAT32 partition spanning the whole device. It is there because
writing an installer image leaves the stick carrying the image's own partition
layout — a few megabytes of FAT followed by raw data — which every desktop OS
then reports as damaged or unformatted.

`helper/fat32.js` writes the MBR and the FAT32 volume itself rather than
shelling out, which keeps one code path across all three systems and sidesteps
the fact that Windows' own `diskpart` refuses to make a FAT32 volume larger than
32 GB. It only ever builds a volume from scratch, so clusters are handed out
linearly and there is no free list, no fragmentation and nothing to reclaim —
which is most of what makes a general FAT implementation hard.

It goes through etcher-sdk's `BlockDevice` for the same reason the image path
does: unmounting on Linux and macOS, `diskpart clean` and volume locking on
Windows.

## What the first phase does

1. Reads `https://file.osmiumsound.it/latest.json` to find the current image.
2. Verifies the Ed25519 signature over the `.sha256` sidecar with the OTA public
   key in `assets/ota-pubkey.pem`, then checks the image against the digest that
   sidecar carries. **An unsigned image is refused**, unlike OS OTA bundles where
   an unsigned build merely warns.
3. Downloads to a cache in the app's userData dir, resuming an interrupted
   transfer with a Range request instead of refetching a gigabyte.

   The cache holds **one image at a time**: `prepare()` deletes every other file
   in there before it starts. Reopening the app, or writing a second stick, then
   costs nothing — but a channel that publishes a dev build every few days does
   not quietly leave a gigabyte behind for each one. On Windows that directory is
   `%APPDATA%\Osmium Flasher\images`, on Linux `~/.config/Osmium Flasher/images`,
   and on macOS `~/Library/Application Support/Osmium Flasher/images`.
4. Writes the image raw to the chosen stick and reads it back to verify.

## Layout

| Path | Role |
|---|---|
| `src/main.js` | Electron main: IPC, orchestration. Never elevated. |
| `src/image.js` | Manifest, download/resume, signature and checksum. |
| `src/drives.js` | Removable-drive discovery. |
| `helper/drive-safety.js` | Which drives may be written to. Shared with the writer. |
| `src/elevate.js` | Spawns the helper with sudo-prompt, tails its progress file. |
| `helper/writer.js` | Runs as root/Administrator; the only code that touches the device. |
| `src/renderer.js` | UI and the en/it dictionary. No Node access. |

The GUI stays unprivileged for its whole life — only `helper/writer.js` is
elevated, and it is spawned on Electron's own binary via `ELECTRON_RUN_AS_NODE`
so the native addons keep the right ABI.

### Three platform traps, already handled

- **sudo-prompt buffers stdout** rather than streaming it, so progress travels
  through a temp JSON-lines file that the GUI tails. Do not "simplify" this back
  to stdout.
- **sudo-prompt's `options.env` does not reach the elevated process on Linux**:
  it emits the exports *before* `pkexec`, which then scrubs the environment. On
  POSIX the variable is therefore also inlined into the command itself. Windows
  and macOS put the exports inside the elevated script, so they are fine.

- **Electron forbids external buffers**, because its V8 is built with pointer
  compression: `napi_create_external_buffer` always fails there. That is the only
  way to hand aligned memory to JS, so `@ronomon/direct-io`'s `getAlignedBuffer`
  cannot work — and it reacts with a C `assert`, killing the process rather than
  throwing something catchable. The helper therefore replaces the allocator with
  a plain one and passes `direct: false`, since aligned memory exists only to
  serve `O_DIRECT`. Both must change together: `O_DIRECT` against unaligned
  memory fails with `EINVAL`.

  The consequence is real and worth knowing: **writes go through the OS cache**
  rather than straight to the device, so the read-back verification is less
  independent than it looks — it will catch a truncated or failed write, but a
  stick that lies about what it stored can hide behind the cache. Restoring
  `O_DIRECT` means running the helper on a real Node binary instead of Electron,
  which in turn means shipping one, plus a second copy of the native modules
  built for it: `mountutils` is V8/NAN-based, not N-API, so a single build cannot
  serve both runtimes.

And one that dictated the packaging: the Linux build is a **self-extracting
`.run`, not an AppImage**. An AppImage is mounted over FUSE by the unprivileged
user, and FUSE denies access to every other user — root included — unless
`user_allow_other` is set in `/etc/fuse.conf`, so `pkexec` could never reach the
helper inside the mount. `build/make-selfextract.sh` wraps electron-builder's
tarball into one executable that unpacks into `~/.cache/osmium-flasher/<version>`
on first run and launches from there — a single file to download, but real files
on disk for the elevated helper to reach.

## Dependencies, and the noise `npm ci` prints

There are two runtime dependencies: `@vscode/sudo-prompt` and `etcher-sdk`.
Every deprecation warning you see on install comes from the second one's tree
(`inflight`, `rimraf`, old `glob`, `partitioninfo`, `file-disk`, `blockmap`,
`boolean`, `prebuild-install`) — none is ours to bump, and etcher-sdk is what
buys us Windows volume locking and safe drive enumeration.

`npm audit` reports two moderate advisories, both `file-type` (an infinite loop
on malformed ASF input). They cannot be overridden away: etcher-sdk requires
`file-type ^16` with CommonJS `require`, and the fixed line is ESM-only from v17
on, so forcing it breaks the import. What limits the exposure is that the image
is Ed25519-verified *before* etcher-sdk is handed anything. The one path where
the input is not verified is "use an image already on this computer", where the
worst case is the app hanging on a file the user chose themselves.

Two advisories that did apply were removed with an override:
`follow-redirects` (header leak across redirects) is pinned to `^1.16.0`. Note
it was never reachable either — downloads go through Node's `fetch` in
`src/image.js`, and etcher-sdk only ever sees a local `File`, never its HTTP or
S3 sources. The `usb` override is a separate matter; see the native-modules
notes above.

`npm ci` also warns that it is "skipping integrity check for git dependency"
for `unbzip2-stream`. That one is pinned to commit `4a54f56a` in the lockfile,
so the content is fixed regardless of what the branch does.

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
