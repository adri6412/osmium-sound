#!/usr/bin/env node
'use strict';

/**
 * Elevated write helper for Osmium Flasher.
 *
 * Runs as a plain Node script on Electron's own binary (ELECTRON_RUN_AS_NODE=1),
 * spawned through sudo-prompt so it holds root/Administrator while the GUI stays
 * unprivileged. It never draws anything.
 *
 * sudo-prompt buffers the child's stdout instead of streaming it, so progress
 * cannot travel that way: every event is appended as one JSON line to the file
 * given by --progress, which the GUI tails. The final line is always either
 * {"type":"done"} or {"type":"error"} — the GUI treats a missing final line as
 * a crash.
 *
 * Usage:
 *   writer.js --approot <dir> --device <path> --image <file>
 *             --progress <file> [--expect-size <bytes>] [--no-verify]
 */

const fs = require('fs');
const path = require('path');

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  return i === -1 || i === process.argv.length - 1 ? fallback : process.argv[i + 1];
}

const appRoot = arg('approot');
const devicePath = arg('device');
const imagePath = arg('image');
const progressPath = arg('progress');
const expectSize = Number(arg('expect-size', '0'));
const verify = !process.argv.includes('--no-verify');

// ── progress channel ───────────────────────────────────────────────────────
// Opened once and appended to; the GUI only ever parses whole lines, so a
// partially flushed tail is simply ignored until the newline lands.
let progressFd = null;
try {
  if (progressPath) progressFd = fs.openSync(progressPath, 'a');
} catch (_) {
  /* if we cannot report progress we still perform the write */
}

function emit(event) {
  if (progressFd === null) return;
  try {
    fs.writeSync(progressFd, JSON.stringify(event) + '\n');
  } catch (_) {
    /* never let a reporting failure abort a write in flight */
  }
}

function die(code, message) {
  emit({ type: 'error', code, message: String(message) });
  if (progressFd !== null) {
    try { fs.closeSync(progressFd); } catch (_) { /* ignore */ }
  }
  process.exit(1);
}

// ── etcher-sdk lives inside app.asar, which this file does not ─────────────
// The helper is unpacked to app.asar.unpacked/helper/, so walking up from here
// never reaches app.asar/node_modules. The GUI passes the app root explicitly.
function loadDep(name) {
  if (appRoot) {
    try {
      return require(path.join(appRoot, 'node_modules', name));
    } catch (_) {
      /* fall through to normal resolution */
    }
  }
  return require(name);
}

async function main() {
  if (!devicePath) die('EARGS', 'missing --device');
  if (!imagePath) die('EARGS', 'missing --image');

  let stat;
  try {
    stat = fs.statSync(imagePath);
  } catch (_) {
    die('ENOIMAGE', 'image file not found: ' + imagePath);
  }
  if (expectSize && stat.size !== expectSize) {
    die('ESIZE', 'image size changed under us: expected ' + expectSize + ', found ' + stat.size);
  }

  // Electron's V8 is built with pointer compression, which forbids external
  // buffers: napi_create_external_buffer always fails there. @ronomon/direct-io
  // asserts on that failure and aborts the process outright -- a C assert, not a
  // JS exception, so it cannot be probed for and must be pre-empted.
  //
  // Aligned memory is only ever needed for O_DIRECT, so we drop both together:
  // plain buffers here, and direct: false on the destination below. The cost is
  // that writes go through the OS cache instead of straight to the device.
  const directIo = loadDep('@ronomon/direct-io');
  const underElectron = Boolean(process.versions.electron);
  if (underElectron) {
    directIo.getAlignedBuffer = (size) => Buffer.alloc(size);
  }

  const sdk = loadDep('etcher-sdk');
  const { sourceDestination, multiWrite } = sdk;
  const { list } = loadDep('drivelist');

  // Re-enumerate under elevation and re-check the target. The GUI already
  // filtered system drives, but between its scan and this write the user may
  // have swapped sticks, and /dev/sdb is not a stable name.
  let drives;
  try {
    drives = await list();
  } catch (err) {
    die('ESCAN', 'could not enumerate drives: ' + err.message);
  }

  const drive = drives.find((d) => d.device === devicePath || d.raw === devicePath);
  if (!drive) die('EGONE', 'the selected drive is no longer connected');
  if (drive.isSystem) die('ESYSTEM', 'refusing to write to a system drive');
  if (drive.isReadOnly) die('EREADONLY', 'the selected drive is write-protected');
  if (drive.size && drive.size < stat.size) {
    die('ETOOSMALL', 'the drive is smaller than the image');
  }

  emit({ type: 'stage', stage: 'starting', device: drive.device, size: drive.size });

  const source = new sourceDestination.File({ path: imagePath });
  const destination = new sourceDestination.BlockDevice({
    drive,
    unmountOnSuccess: true,
    write: true,
    // Must stay in step with the getAlignedBuffer shim above: O_DIRECT with
    // unaligned memory fails with EINVAL. Exclusive locking of the device
    // (O_EXCL / O_EXLOCK) is unaffected and still applies.
    direct: !underElectron,
  });

  const failures = [];
  let result;
  try {
    result = await multiWrite.pipeSourceToDestinations({
      source,
      destinations: [destination],
      onFail: (_dest, error) => failures.push(error),
      onProgress: (progress) => {
        emit({
          type: 'progress',
          stage: progress.type,           // 'flashing' | 'verifying' | 'finished'
          position: progress.position,
          bytes: progress.bytes,
          size: progress.size,
          percentage: progress.percentage,
          speed: progress.speed,
          averageSpeed: progress.averageSpeed,
          eta: progress.eta,
        });
      },
      verify,
    });
  } catch (err) {
    die('EWRITE', err && err.message ? err.message : err);
  }

  if (failures.length > 0) {
    die('EWRITE', failures.map((e) => e.message).join('; '));
  }
  if (result && result.failures && result.failures.size > 0) {
    const msgs = [];
    result.failures.forEach((err) => msgs.push(err.message));
    die('EWRITE', msgs.join('; '));
  }

  emit({ type: 'done', bytesWritten: result ? result.bytesWritten : stat.size });
  if (progressFd !== null) {
    try { fs.closeSync(progressFd); } catch (_) { /* ignore */ }
  }
  process.exit(0);
}

main().catch((err) => die('EUNEXPECTED', err && err.stack ? err.stack : err));
