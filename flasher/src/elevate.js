'use strict';

/**
 * Runs helper/writer.js with root/Administrator rights and relays its progress.
 *
 * Two platform details drive the shape of this module:
 *
 *  1. sudo-prompt buffers the child's stdout rather than streaming it, so the
 *     helper reports through a temp file that we tail here.
 *
 *  2. sudo-prompt's `options.env` only reaches the elevated process on Windows
 *     (written into the elevated .bat) and macOS (exported inside the script
 *     that osascript runs with administrator privileges). On Linux the exports
 *     are emitted *before* pkexec, which then scrubs the environment — so on
 *     POSIX we also inline the assignment into the command itself, where it
 *     runs inside the elevated shell.
 */

const fs = require('fs');
const fsp = require('fs/promises');
const os = require('os');
const path = require('path');
const crypto = require('crypto');

const sudo = require('@vscode/sudo-prompt');

const POLL_MS = 250;

function quote(value) {
  return '"' + String(value).replace(/"/g, '\\"') + '"';
}

/** Tails the helper's JSON-lines progress file, emitting each complete line. */
class ProgressTail {
  constructor(file, onEvent) {
    this.file = file;
    this.onEvent = onEvent;
    this.offset = 0;
    this.pending = '';
    this.last = null;
    this.timer = null;
  }

  start() {
    this.timer = setInterval(() => this.poll(), POLL_MS);
  }

  poll() {
    let size;
    try {
      size = fs.statSync(this.file).size;
    } catch (_) {
      return; // the helper has not created it yet
    }
    if (size <= this.offset) return;

    let chunk;
    try {
      const fd = fs.openSync(this.file, 'r');
      const buf = Buffer.alloc(size - this.offset);
      fs.readSync(fd, buf, 0, buf.length, this.offset);
      fs.closeSync(fd);
      chunk = buf.toString('utf8');
    } catch (_) {
      return;
    }
    this.offset = size;

    // A write may land mid-line; keep the tail until its newline arrives.
    this.pending += chunk;
    const lines = this.pending.split('\n');
    this.pending = lines.pop();

    for (const line of lines) {
      if (!line.trim()) continue;
      let event;
      try {
        event = JSON.parse(line);
      } catch (_) {
        continue;
      }
      this.last = event;
      this.onEvent(event);
    }
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.poll(); // drain whatever landed between the last tick and exit
  }
}

/**
 * @param {object}   opts
 * @param {string}   opts.devicePath  drivelist `device` of the target stick
 * @param {string}   [opts.imagePath] verified image on disk (write mode only)
 * @param {number}   [opts.expectSize] size the GUI verified, re-checked elevated
 * @param {boolean}  [opts.verify]    read back and compare after writing
 * @param {string}   [opts.mode]      'write' (default) or 'restore'
 * @param {string}   [opts.label]     volume label, restore mode only
 * @param {function} opts.onEvent     receives each helper event
 * @returns {Promise<{bytesWritten:number}>}
 */
async function writeElevated({
  devicePath, imagePath, expectSize, verify = true,
  mode = 'write', label = 'OSMIUM', onEvent,
}) {
  const appRoot = path.join(__dirname, '..');
  const helper = path.join(appRoot, 'helper', 'writer.js');

  // In a packaged app the helper is unpacked while the rest stays in the
  // archive; an elevated process cannot execute out of app.asar.
  const helperPath = helper.replace('app.asar' + path.sep, 'app.asar.unpacked' + path.sep);

  const progressFile = path.join(
    os.tmpdir(),
    `osmium-flasher-${crypto.randomBytes(8).toString('hex')}.jsonl`,
  );
  await fsp.writeFile(progressFile, '');

  const argv = [
    quote(process.execPath),
    quote(helperPath),
    '--approot', quote(appRoot),
    '--device', quote(devicePath),
    '--progress', quote(progressFile),
    '--mode', quote(mode),
  ];
  if (mode === 'restore') {
    argv.push('--label', quote(label));
  } else {
    argv.push('--image', quote(imagePath), '--expect-size', String(expectSize || 0));
    if (!verify) argv.push('--no-verify');
  }

  const bare = argv.join(' ');
  const command = process.platform === 'win32' ? bare : `ELECTRON_RUN_AS_NODE=1 ${bare}`;

  const tail = new ProgressTail(progressFile, onEvent);
  tail.start();

  // The helper exits non-zero after reporting a failure, which sudo-prompt
  // surfaces as a generic "Command failed". Its own diagnosis is far more
  // useful, so the elevation error is held back until the progress file has
  // been consulted.
  let elevationError = null;
  try {
    await new Promise((resolve, reject) => {
      sudo.exec(
        command,
        { name: 'Osmium Flasher', env: { ELECTRON_RUN_AS_NODE: '1' } },
        (error, _stdout, stderr) => {
          if (error) {
            const message = String(error.message || error);
            // The polkit/UAC/osascript dialog was dismissed.
            if (/did not grant|User did not grant permission|cancell?ed/i.test(message)) {
              const denied = new Error('elevation refused');
              denied.code = 'EDENIED';
              return reject(denied);
            }
            const failed = new Error(message + (stderr ? ` — ${stderr}` : ''));
            failed.code = 'EELEVATE';
            return reject(failed);
          }
          resolve();
        },
      );
    });
  } catch (err) {
    if (err.code === 'EDENIED') { tail.stop(); throw err; }
    elevationError = err;
  } finally {
    tail.stop();
  }

  const last = tail.last;

  // What the helper said about itself wins over what the shell made of it.
  if (last && last.type === 'error') {
    const err = new Error(last.message);
    err.code = last.code || 'EUNKNOWN';
    err.progressFile = progressFile;
    throw err;
  }
  if (elevationError) {
    // Nothing was reported: the process died before it could say why. Keep the
    // progress file so the failure can still be looked at afterwards.
    elevationError.progressFile = progressFile;
    throw elevationError;
  }
  if (!last) {
    const err = new Error('the writer exited without reporting a result');
    err.code = 'ECRASH';
    err.progressFile = progressFile;
    throw err;
  }
  if (last.type !== 'done') {
    const err = new Error('the writer stopped before finishing');
    err.code = 'EINCOMPLETE';
    err.progressFile = progressFile;
    throw err;
  }

  await fsp.rm(progressFile, { force: true });
  return { bytesWritten: last.bytesWritten };
}

module.exports = { writeElevated };
