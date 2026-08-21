'use strict';

/**
 * Decides whether a drive may be offered as a target.
 *
 * Shared by the drive list in the interface and by the elevated helper, which
 * re-checks immediately before writing. Keeping one copy is the point: a rule
 * that held in the list but not in the writer would be no rule at all.
 *
 * The flag drivelist sets for system disks is not enough on its own. A Mac
 * reported its boot disk — a 4 TB internal NVMe mounted at /Volumes/Macintosh_HD
 * — with that flag clear, and the drive was duly offered for erasure. On macOS
 * the boot volume lives on a synthesised APFS container, which the detection
 * does not always recognise, and a virtual machine confuses it further.
 *
 * So the test is inverted: rather than trying to recognise the disks that must
 * be excluded, only those that positively look detachable are allowed through.
 * An internal system disk reports none of removable, USB or card. Getting this
 * wrong in the permissive direction destroys someone's computer; getting it
 * wrong in the strict direction means a stick is not listed, and they tell us.
 */

// Paths that only ever belong to a running operating system.
const SYSTEM_MOUNTPOINTS = [
  '/',
  '/boot',
  '/boot/efi',
  '/System/Volumes/Data',
  'C:\\',
];

function mountpointPaths(drive) {
  return (drive.mountpoints || [])
    .map((m) => (typeof m === 'string' ? m : m && m.path))
    .filter(Boolean);
}

/**
 * @returns {null|string} null when the drive may be written to, otherwise a
 *          short reason code explaining why it was rejected.
 */
function rejectionReason(drive, options = {}) {
  if (!drive) return 'missing';

  // These two are never relaxed, whatever the caller asks for.
  if (drive.isSystem) return 'system';

  // Disk images attached with hdiutil or losetup are virtual devices, and are
  // excluded so that nobody writes an installer to one by accident. They are
  // also the only way to exercise the write path without real hardware, hence
  // the opt-in — which relaxes this condition and nothing else.
  if (drive.isVirtual && !options.allowVirtual) return 'virtual';

  const mounts = mountpointPaths(drive);
  if (mounts.some((p) => SYSTEM_MOUNTPOINTS.includes(p))) return 'system-mount';

  // The positive test. Anything that cannot be unplugged is not a USB stick,
  // whatever the other flags claim.
  if (!(drive.isRemovable || drive.isUSB || drive.isCard)) return 'not-removable';

  return null;
}

const isWritableTarget = (drive, options) => rejectionReason(drive, options) === null;

/** Reads the opt-in from the environment; there is deliberately no UI for it. */
const virtualDrivesAllowed = () => process.env.OSMIUM_FLASHER_ALLOW_VIRTUAL === '1';

module.exports = {
  SYSTEM_MOUNTPOINTS, mountpointPaths, rejectionReason, isWritableTarget,
  virtualDrivesAllowed,
};
