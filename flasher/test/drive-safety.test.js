'use strict';

/**
 * Which drives may be written to.
 *
 * This is the one part of the app where being wrong destroys something the user
 * cannot get back, so the cases are written from real hardware rather than from
 * the shape of the code. The first is verbatim from a Mac that was offered its
 * own boot disk for erasure: a 4 TB internal NVMe, mounted at
 * /Volumes/Macintosh_HD, with drivelist's system flag clear.
 */

const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const { rejectionReason, isWritableTarget } = require('../helper/drive-safety');

const drive = (props) => ({
  device: '/dev/x', size: 32 * 1024 ** 3, mountpoints: [], ...props,
});

test('a Mac boot disk is refused even with the system flag clear', () => {
  const macBootDisk = drive({
    device: '/dev/disk4',
    description: 'Samsung SSD 990 PRO 4TB Media',
    size: 4 * 1000 ** 4,
    isSystem: false,          // exactly as it was reported
    isRemovable: false,
    isUSB: false,
    isCard: false,
    mountpoints: [{ path: '/Volumes/Macintosh_HD - Data' }, { path: '/Volumes/Macintosh_HD' }],
  });
  assert.equal(rejectionReason(macBootDisk), 'not-removable');
  assert.equal(isWritableTarget(macBootDisk), false);
});

test('drives that can actually be unplugged are allowed', () => {
  for (const [what, d] of [
    ['a USB stick', drive({ isRemovable: true, isUSB: true })],
    ['an external USB SSD', drive({ isRemovable: false, isUSB: true, mountpoints: [{ path: '/media/x' }] })],
    ['an SD card', drive({ isCard: true })],
    ['a removable drive on a bus we cannot identify', drive({ isRemovable: true })],
  ]) {
    assert.equal(rejectionReason(d), null, `${what} should be offered`);
  }
});

test('every way a system disk announces itself is refused', () => {
  for (const [what, d, why] of [
    ['the system flag', drive({ isSystem: true, isRemovable: true, isUSB: true }), 'system'],
    ['a virtual device', drive({ isVirtual: true, isUSB: true }), 'virtual'],
    ['mounted at /', drive({ isRemovable: true, isUSB: true, mountpoints: [{ path: '/' }] }), 'system-mount'],
    ['mounted at /boot', drive({ isUSB: true, mountpoints: [{ path: '/boot' }] }), 'system-mount'],
    ['mounted at C:\\', drive({ isRemovable: true, mountpoints: [{ path: 'C:\\' }] }), 'system-mount'],
    ['macOS data volume', drive({ isUSB: true, mountpoints: [{ path: '/System/Volumes/Data' }] }), 'system-mount'],
    ['an internal disk with no flags at all', drive({}), 'not-removable'],
  ]) {
    assert.equal(rejectionReason(d), why, `${what} should be refused`);
  }
  assert.equal(rejectionReason(null), 'missing');
});

test('a plain string mountpoint is understood as well as an object', () => {
  // drivelist returns objects; being strict about the shape here would mean
  // silently skipping the check on anything that returned strings.
  assert.equal(rejectionReason(drive({ isUSB: true, mountpoints: ['/'] })), 'system-mount');
});

test('the interface and the elevated writer share one rule', () => {
  // Two copies of this decision would eventually disagree, and the copy that
  // mattered would be whichever one was not updated.
  const list = fs.readFileSync(path.join(__dirname, '..', 'src', 'drives.js'), 'utf8');
  const writer = fs.readFileSync(path.join(__dirname, '..', 'helper', 'writer.js'), 'utf8');

  assert.match(list, /require\('\.\.\/helper\/drive-safety'\)/, 'the drive list must use the shared rule');
  assert.match(list, /isWritableTarget\(drive[,)]/);
  assert.match(writer, /drive-safety/, 'the writer must re-check before writing');
  assert.match(writer, /rejectionReason\(drive[,)]/);

  // Neither may fall back to judging a drive by the system flag alone.
  assert.doesNotMatch(list, /if \(drive\.isSystem\) return;/);
  assert.doesNotMatch(writer, /if \(drive\.isSystem\) die\(/);
});

test('disk images are excluded, and the opt-in relaxes only that', () => {
  // A hdiutil or losetup image is the only way to exercise the write path
  // without real hardware. It is still excluded by default, so that nobody
  // writes an installer to a mounted image by accident.
  const image = drive({ device: '/dev/disk7', isVirtual: true, isRemovable: true });
  assert.equal(rejectionReason(image), 'virtual');
  assert.equal(rejectionReason(image, { allowVirtual: true }), null);

  // The opt-in must not become a way past the checks that matter.
  const cases = [
    ['a virtual system disk', drive({ isVirtual: true, isRemovable: true, isSystem: true }), 'system'],
    ['an image mounted at /', drive({ isVirtual: true, isRemovable: true, mountpoints: [{ path: '/' }] }), 'system-mount'],
    ['an image mounted at C:\\', drive({ isVirtual: true, isUSB: true, mountpoints: [{ path: 'C:\\' }] }), 'system-mount'],
    ['a non-removable image', drive({ isVirtual: true }), 'not-removable'],
  ];
  for (const [what, d, why] of cases) {
    assert.equal(rejectionReason(d, { allowVirtual: true }), why,
      `${what} must stay refused even with virtual drives allowed`);
  }
});

test('the opt-in reaches the elevated writer, which would otherwise refuse', () => {
  // The writer re-checks with the same rule. If the flag stopped at the
  // interface, a drive offered in the list would be rejected at the last
  // moment, which reads as a bug rather than as a policy.
  const elevate = fs.readFileSync(path.join(__dirname, '..', 'src', 'elevate.js'), 'utf8');
  const writer = fs.readFileSync(path.join(__dirname, '..', 'helper', 'writer.js'), 'utf8');

  assert.match(elevate, /OSMIUM_FLASHER_ALLOW_VIRTUAL/, 'the flag must be forwarded');
  assert.match(elevate, /'--allow-virtual'/);
  assert.match(writer, /--allow-virtual/, 'the writer must accept it');
  assert.match(writer, /rejectionReason\(drive, \{ allowVirtual \}\)/);

  // It is passed as an argument, not inherited: sudo-prompt does not carry the
  // environment across on Linux.
  assert.doesNotMatch(writer, /process\.env\.OSMIUM_FLASHER_ALLOW_VIRTUAL/);
});

// ── Through the object the interface is actually handed ─────────────────────
//
// The tests above judge plain drivelist entries, which is what the elevated
// writer receives. The interface receives something else: etcher-sdk's scanner
// emits BlockDevice wrappers. Those forward only seven fields, so every flag
// this rule depends on reads as undefined and the verdicts invert -- a real
// stick is refused as not-removable, and a disk image passes the virtual check
// unnoticed. Entry-shaped fixtures cannot see any of that, which is how the
// drive list came to be empty with every test still green.

const { sourceDestination } = require('etcher-sdk');

const wrap = (props) => new sourceDestination.BlockDevice({
  drive: {
    device: '/dev/sdz', raw: '/dev/sdz', description: 'Test', size: 8 * 1024 ** 3,
    mountpoints: [], blockSize: 512, logicalBlockSize: 512, displayName: 'Test',
    isSystem: false, isRemovable: false, isUSB: false, isCard: false,
    isVirtual: false, isReadOnly: false,
    ...props,
  },
  write: true,
  direct: false,
});

test('a BlockDevice hides the flags the rule depends on', () => {
  // Documents why the unwrapping exists. If etcher-sdk ever forwards these, this
  // test says so rather than leaving the workaround unexplained.
  const device = wrap({ isRemovable: true, isUSB: true, isVirtual: true, isReadOnly: true });
  for (const field of ['isRemovable', 'isUSB', 'isCard', 'isVirtual', 'isReadOnly']) {
    assert.equal(device[field], undefined, `${field} is not forwarded by BlockDevice`);
  }
  assert.equal(device.isSystem, false, 'isSystem is forwarded, which is why it alone appeared to work');
  assert.equal(device.drive.isRemovable, true, 'the real entry is reachable');
});

test('verdicts are the same whether given a wrapper or an entry', () => {
  const cases = [
    ['a USB stick', { isRemovable: true, isUSB: true }, null],
    ['an SD card', { isCard: true }, null],
    ['an internal disk', {}, 'not-removable'],
    ['a system disk', { isSystem: true, isRemovable: true }, 'system'],
    ['a disk image', { isVirtual: true, isRemovable: true }, 'virtual'],
    ['mounted at /', { isRemovable: true, mountpoints: [{ path: '/' }] }, 'system-mount'],
  ];

  for (const [what, props, expected] of cases) {
    assert.equal(rejectionReason(wrap(props)), expected, `${what}, as a wrapper`);
    assert.equal(rejectionReason(drive(props)), expected, `${what}, as an entry`);
  }
});

test('the opt-in still only reaches disk images when given a wrapper', () => {
  assert.equal(rejectionReason(wrap({ isVirtual: true, isRemovable: true }), { allowVirtual: true }), null);
  assert.equal(rejectionReason(wrap({ isVirtual: true, isSystem: true, isRemovable: true }), { allowVirtual: true }), 'system');
});

test('the drive list reads its flags from the entry, not the wrapper', () => {
  // isReadOnly is not forwarded either, so a write-protected stick was being
  // shown as usable.
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'drives.js'), 'utf8');
  assert.match(src, /underlying/, 'describe() must unwrap before reading flags');
  assert.match(src, /const drive = underlying\(wrapper\)/);
});
