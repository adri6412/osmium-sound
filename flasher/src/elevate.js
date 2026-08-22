'use strict';

/**
 * Runs helper/writer.js with root/Administrator rights and relays its progress.
 *
 * Elevation is not unconditional: when the target is already writable as we
 * are, the helper is spawned as an ordinary child process instead. See
 * writableAsIs() for when that happens and why it matters.
 *
 * Two platform details drive the shape of the elevated path:
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
const { spawn } = require('child_process');

const sudo = require('@vscode/sudo-prompt');

const POLL_MS = 250;

/**
 * Quotes one argument for the elevated command line, per platform.
 *
 * POSIX: single quotes, with an embedded single quote spliced in as '\''.
 * On Linux sudo-prompt then wraps the whole line in `/bin/bash -c "…"`, so
 * a shell reads it twice; the outer pass still expands $, ` and \ inside
 * its double quotes, so those are escaped for it here (it escapes the "
 * itself). On macOS the line goes into a script file and is read once.
 *
 * Windows: sudo-prompt writes the line into a .bat, cmd runs it, and
 * Electron's C runtime splits the arguments again: \" for a quote, a run of
 * backslashes doubled only where it precedes a quote or the end, and % as
 * %% so cmd does not take it for a variable.
 */
function quote(value) {
  const s = String(value);
  if (process.platform === 'win32') return quoteWindows(s);
  const single = "'" + s.replace(/'/g, "'\\''") + "'";
  return process.platform === 'linux' ? single.replace(/[\\$`]/g, '\\$&') : single;
}

function quoteWindows(s) {
  let out = '"';
  let backslashes = 0;
  for (const ch of s) {
    if (ch === '\\') { backslashes += 1; continue; }
    if (ch === '"') {
      out += '\\'.repeat(backslashes * 2 + 1) + '"';
    } else {
      out += '\\'.repeat(backslashes) + (ch === '%' ? '%%' : ch);
    }
    backslashes = 0;
  }
  return out + '\\'.repeat(backslashes * 2) + '"';
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
 * The device nodes etcher-sdk will actually open for this drive.
 *
 * On macOS the write goes through the character device, /dev/rdiskN, while the
 * block device is what gets unmounted; both have to be ours for the
 * unprivileged path to be safe to take. Elsewhere the two names coincide.
 */
function deviceNodes(devicePath) {
  const raw = devicePath.replace(/^(\/dev\/)(disk\d+)$/, '$1r$2');
  return raw === devicePath ? [devicePath] : [raw, devicePath];
}

/**
 * Whether the target can be opened for writing without elevating first.
 *
 * Normally it cannot: a stick plugged into macOS is root:operator 0640, and a
 * Linux block device is root:disk. But `hdiutil attach` hands the device nodes
 * of a disk image to the account that attached it, which is exactly the
 * testing path the README describes — and it is also true wherever a system
 * grants the console user its removable devices outright.
 *
 * Elevating regardless puts a password prompt in front of a write that does
 * not need one, and on a machine whose user is not an administrator that
 * prompt cannot be satisfied at all: the dialog asks for an administrator's
 * credentials, not the user's own. Probing first turns that dead end into a
 * write that simply works.
 *
 * A refusal here is never reported as an error — it only means the elevated
 * path is used, which is what happened before this check existed. That
 * includes EBUSY from a mounted volume, where elevating is the right answer
 * anyway: the helper unmounts before it writes.
 */
function writableAsIs(devicePath) {
  if (process.platform === 'win32') return false;
  return deviceNodes(devicePath).every((node) => {
    let fd;
    try {
      fd = fs.openSync(node, fs.constants.O_WRONLY);
    } catch (_) {
      return false;
    }
    fs.closeSync(fd);
    return true;
  });
}

/**
 * Runs the helper as an ordinary child process, for when no rights are needed.
 *
 * Unlike sudo-prompt this takes a real argument vector, so nothing has to be
 * quoted into a shell. Progress still travels through the file the caller
 * tails: the helper does not know which way it was started.
 */
function runDirect(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      env: Object.assign({}, process.env, { ELECTRON_RUN_AS_NODE: '1' }),
      stdio: ['ignore', 'ignore', 'pipe'],
    });
    let stderr = '';
    child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
    child.on('error', reject);
    child.on('close', (status) => {
      if (status === 0) return resolve();
      const err = new Error(
        `the writer exited with status ${status}` + (stderr ? ` \u2014 ${stderr.trim()}` : ''),
      );
      err.code = 'EHELPER';
      reject(err);
    });
  });
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

  // Kept unquoted: the direct path needs a real argument vector, and the
  // elevated one is quoted into a command line out of the same list below.
  const args = [
    helperPath,
    '--approot', appRoot,
    '--device', devicePath,
    '--progress', progressFile,
    '--mode', mode,
  ];
  if (process.env.OSMIUM_FLASHER_ALLOW_VIRTUAL === '1') args.push('--allow-virtual');
  if (mode === 'restore') {
    args.push('--label', label);
  } else {
    args.push('--image', imagePath, '--expect-size', String(expectSize || 0));
    if (!verify) args.push('--no-verify');
  }

  const bare = [quote(process.execPath)]
    .concat(args.map((a) => (a.startsWith('--') ? a : quote(a))))
    .join(' ');
  const command = process.platform === 'win32' ? bare : `ELECTRON_RUN_AS_NODE=1 ${bare}`;

  // Decided before anything is written, and reported so the interface does not
  // announce a password prompt that is never going to appear.
  const elevated = !writableAsIs(devicePath);
  onEvent({ type: 'elevation', elevated });

  const tail = new ProgressTail(progressFile, onEvent);
  tail.start();

  // The helper exits non-zero after reporting a failure, which sudo-prompt
  // surfaces as a generic "Command failed". Its own diagnosis is far more
  // useful, so the elevation error is held back until the progress file has
  // been consulted.
  let elevationError = null;
  try {
    if (!elevated) {
      await runDirect(args);
    } else {
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
    }
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
