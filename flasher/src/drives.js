'use strict';

/**
 * Removable-drive discovery.
 *
 * Runs unprivileged in the main process: enumerating drives needs no rights,
 * only writing to them does. System drives are excluded at the adapter level so
 * the user's boot disk is never even offered.
 */

const { scanner } = require('etcher-sdk');
const { isWritableTarget, virtualDrivesAllowed, underlying } = require('../helper/drive-safety');

// Above this, a "USB stick" is almost certainly an external hard drive the user
// did not mean to erase. Such drives are still listed, but flagged so the UI can
// demand a second, explicit confirmation.
const OVERSIZE_BYTES = 256 * 1024 * 1024 * 1024;

function describe(wrapper) {
  // Same unwrapping as the safety rule: read the flags from the drivelist entry
  // rather than from the BlockDevice, which does not forward them. Taking them
  // from the wrapper left isReadOnly undefined, so a write-protected stick was
  // offered as if it were fine.
  const drive = underlying(wrapper);
  return {
    device: drive.device,
    raw: drive.raw,
    displayName: drive.displayName || drive.device,
    description: drive.description || '',
    size: drive.size || 0,
    isReadOnly: Boolean(drive.isReadOnly),
    isUSB: Boolean(drive.isUSB),
    isCard: Boolean(drive.isCard),
    mountpoints: (drive.mountpoints || []).map((m) => m.path),
    oversize: Boolean(drive.size && drive.size > OVERSIZE_BYTES),
  };
}

class DriveWatcher {
  constructor(onChange) {
    this.onChange = onChange;
    this.drives = new Map();

    this.adapter = new scanner.adapters.BlockDeviceAdapter({
      // Note: these are getter *functions*, not booleans.
      includeSystemDrives: () => false,
      includeVirtualDrives: virtualDrivesAllowed,
      unmountOnSuccess: true,
      write: true,
      direct: true,
    });
    this.scanner = new scanner.Scanner([this.adapter]);

    this.scanner.on('attach', (drive) => {
      // The adapter is asked not to report system drives, but that flag has been
      // seen clear on a Mac's own boot disk, so the decision is made here too --
      // by the same rule the elevated writer applies before it writes.
      if (!isWritableTarget(drive, { allowVirtual: virtualDrivesAllowed() })) return;
      this.drives.set(drive.device, drive);
      this.emit();
    });
    this.scanner.on('detach', (drive) => {
      this.drives.delete(drive.device);
      this.emit();
    });
    this.scanner.on('error', () => {
      /* a failed scan pass is transient; the next one recovers */
    });
  }

  emit() {
    const list = [...this.drives.values()].map(describe);
    list.sort((a, b) => a.device.localeCompare(b.device));
    this.onChange(list);
  }

  start() {
    this.scanner.start();
    this.emit();
  }

  stop() {
    try {
      this.scanner.stop();
    } catch (_) {
      /* ignore */
    }
  }
}

module.exports = { DriveWatcher, OVERSIZE_BYTES };
