'use strict';

/**
 * Exercises etcher-sdk's block-device write path with the unaligned buffers the
 * helper substitutes when it runs under Electron.
 *
 * This is the path that aborted the process on Windows: Electron's V8 is built
 * with pointer compression, which forbids external buffers, so
 * @ronomon/direct-io's getAlignedBuffer fails a C assert and takes the process
 * down. The helper replaces it with a plain allocator and turns O_DIRECT off to
 * match. What has to be proven is that the write is still byte-exact.
 *
 * The destination is a BlockDevice pointed at an ordinary file: that is what
 * makes etcher-sdk take the BlockWriteStream path (and call getAlignedBuffer)
 * rather than the plain-file one, without needing a real USB stick or root.
 *
 * Two of BlockDevice's real-hardware steps have to be held back for that trick
 * to work, and neither is what this test is about:
 *   - on macOS and Linux, _open() unmounts the drive first, and a temp file is
 *     not a drive ("Unmount failed, invalid drive");
 *   - on Windows it runs `diskpart clean`, which needs a \\.\PhysicalDriveN
 *     path and throws on anything else. keepOriginal skips it. That guard is
 *     also why this test could never touch a real disk by accident.
 */

const assert = require('node:assert/strict');
const { test } = require('node:test');
const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const IMAGE_BYTES = 8 * 1024 * 1024;
const SLACK = 1024 * 1024;      // the "stick" is bigger than the image, as in real life

test('the image is written byte-exact with unaligned buffers', async () => {
  const directIo = require('@ronomon/direct-io');
  const originalGetAlignedBuffer = directIo.getAlignedBuffer;

  let calls = 0;
  directIo.getAlignedBuffer = (size) => {
    calls += 1;
    return Buffer.alloc(size);   // deliberately NOT aligned
  };

  // Required after the shim is installed: etcher-sdk captures the module object
  // at import time but reads the property per call, so the order still matters
  // for clarity even though either would work.
  const { sourceDestination, multiWrite } = require('etcher-sdk');

  // Reaching into etcher-sdk's internals on purpose: getUnmountDisk is resolved
  // lazily and read per call, so replacing it here keeps _open() from trying to
  // unmount a temp file.
  const lazy = require('etcher-sdk/build/lazy');
  const originalGetUnmountDisk = lazy.getUnmountDisk;
  lazy.getUnmountDisk = () => async () => { /* a temp file has nothing to unmount */ };

  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-write-'));
  try {
    const imagePath = path.join(dir, 'image.img');
    const devicePath = path.join(dir, 'fake-device');
    const payload = crypto.randomBytes(IMAGE_BYTES);
    await fsp.writeFile(imagePath, payload);
    await fsp.writeFile(devicePath, Buffer.alloc(IMAGE_BYTES + SLACK));

    const drive = {
      device: devicePath, raw: devicePath, devicePath,
      size: IMAGE_BYTES + SLACK,
      isSystem: false, isReadOnly: false, isRemovable: true,
      isUSB: true, isCard: false, mountpoints: [],
      blockSize: 512, logicalBlockSize: 512,
      description: 'fake device', displayName: 'fake', busType: 'USB', error: null,
    };

    const failures = [];
    const result = await multiWrite.pipeSourceToDestinations({
      source: new sourceDestination.File({ path: imagePath }),
      destinations: [new sourceDestination.BlockDevice({
        drive, write: true, direct: false, unmountOnSuccess: false,
        keepOriginal: true,   // skip `diskpart clean`, see the note above
      })],
      onFail: (_d, err) => failures.push(err),
      onProgress: () => {},
      verify: true,
    });

    assert.deepEqual(failures.map((e) => e.message), [], 'the write reported failures');
    assert.equal(result.failures.size, 0);
    assert.equal(result.bytesWritten, IMAGE_BYTES);

    assert.ok(calls > 0,
      'getAlignedBuffer was never called — this test is no longer covering the crash path');

    const written = (await fsp.readFile(devicePath)).subarray(0, IMAGE_BYTES);
    assert.equal(
      crypto.createHash('sha256').update(written).digest('hex'),
      crypto.createHash('sha256').update(payload).digest('hex'),
      'the device contents differ from the image',
    );
  } finally {
    directIo.getAlignedBuffer = originalGetAlignedBuffer;
    lazy.getUnmountDisk = originalGetUnmountDisk;
    await fsp.rm(dir, { recursive: true, force: true });
  }
});

test('the helper turns O_DIRECT off exactly when it shims the allocator', () => {
  // The two have to move together: O_DIRECT against unaligned memory fails with
  // EINVAL, and aligned memory is pointless without O_DIRECT.
  const src = fs.readFileSync(path.join(__dirname, '..', 'helper', 'writer.js'), 'utf8');
  assert.match(src, /getAlignedBuffer\s*=\s*\(size\)\s*=>\s*Buffer\.alloc\(size\)/,
    'the unaligned allocator shim is missing');
  assert.match(src, /direct:\s*!underElectron/,
    'O_DIRECT is no longer tied to the same condition as the shim');
});
