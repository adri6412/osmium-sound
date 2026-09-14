// Which of the kernel's input devices count as "a keyboard someone can type
// on". Drives the on-screen keyboard auto-show in the renderer (main.js polls
// this and pushes the verdict over IPC; src/utils/physicalKeyboard.js consumes
// it). Pure Node + sysfs, no Electron dependency, so it can be exercised
// against a fake sysfs tree.
//
// Why not udev's /dev/input/by-id/*-event-kbd symlinks (the previous
// approach): udev tags *any* input device that advertises a full set of
// letter keys as a keyboard (ID_INPUT_KEYBOARD), and that includes things
// nobody can type on:
//   - most USB touchscreen controllers (ILITEK, eGalax, Elo, Weida, the
//     wch.cn/WaveShare-style HDMI panels, ...) are composite HID devices that
//     ship a "keyboard" collection next to the touch digitizer, so a
//     touch-only appliance looked like it had a keyboard plugged in;
//   - the legacy i8042 PS/2 controller on most x86 boards registers an
//     "AT Translated Set 2 keyboard" whether or not anything is connected to
//     it (plenty of boards have no PS/2 port at all — the BIOS/EC USB-legacy
//     emulation still answers the kernel's probe).
// Either one silently suppressed the on-screen keyboard, and on a touch-only
// appliance that means there is no way to type at all.
//
// So instead of "is there any keyboard-class device", the question here is
// "is there a keyboard someone can actually type on": a full-keyboard device
// on a hot-pluggable bus (USB / Bluetooth) whose physical unit is not also a
// touch digitizer. Internal laptop keyboards (i8042 / I2C / SPI) are
// deliberately NOT counted — they're indistinguishable from the phantom AT
// keyboard — the renderer covers them with a "has a real letter key been
// pressed this session" heuristic (src/utils/physicalKeyboard.js). Getting
// that case wrong costs an on-screen keyboard that pops up once and closes
// at the first keystroke; getting the touch-only case wrong costs the
// keyboard entirely.

import { existsSync, readdirSync, readFileSync, realpathSync } from 'fs';
import { basename, dirname, join } from 'path';

// linux/input.h — bus types. Only buses a keyboard gets plugged into.
const BUS_USB = 0x03;
const BUS_BLUETOOTH = 0x05;
const HOTPLUG_BUSES = new Set([BUS_USB, BUS_BLUETOOTH]);

// linux/input-event-codes.h
const BTN_LEFT = 0x110;
const BTN_TOOL_PEN = 0x140;
const BTN_TOOL_FINGER = 0x145;
const BTN_TOUCH = 0x14a;
const BTN_STYLUS = 0x14b;
const ABS_X = 0x00;
const ABS_Y = 0x01;
const ABS_MT_POSITION_X = 0x35;
const ABS_MT_POSITION_Y = 0x36;
const INPUT_PROP_POINTER = 0x00;
const INPUT_PROP_DIRECT = 0x01;

// KEY_ESC (1) .. KEY_D (32), all present: udev's own definition of "a full
// keyboard" (systemd input_id.c → ID_INPUT_KEYBOARD). Bit 0 is KEY_RESERVED.
const FULL_KEYBOARD_MASK = 0xfffffffen;

// sysfs prints capability bitmaps as hex words, one per C `unsigned long`,
// most significant word first, all-zero leading words omitted. The word
// width follows the *reader*: a 32-bit process on a 64-bit kernel gets
// 32-bit words (compat path in input_bits_to_string).
const LONG_BITS = process.arch === 'ia32' || process.arch === 'arm' ? 32 : 64;

const readSysfs = (p) => {
  try {
    return readFileSync(p, 'utf8').trim();
  } catch (_) {
    return null;
  }
};

/** Fold a sysfs bitmap string into one BigInt (bit N = code N). */
export function parseBitmap(text) {
  let bits = 0n;
  if (!text) return bits;
  for (const word of text.split(/\s+/)) {
    if (!/^[0-9a-fA-F]+$/.test(word)) return 0n;
    bits = (bits << BigInt(LONG_BITS)) | BigInt('0x' + word);
  }
  return bits;
}

const hasBit = (bits, n) => ((bits >> BigInt(n)) & 1n) === 1n;

// Mirrors the touchscreen branch of udev's input_id classification closely
// enough: a direct-input digitizer (touchscreen, pen display), or — for
// single-touch controllers old enough to predate INPUT_PROP_DIRECT —
// absolute X/Y plus BTN_TOUCH without any of the things that make it a
// touchpad (BTN_TOOL_FINGER), an indirect tablet (pen/stylus) or an absolute
// mouse (BTN_LEFT).
function isTouchDigitizer(key, abs, props) {
  if (hasBit(props, INPUT_PROP_DIRECT)) return true;
  if (hasBit(props, INPUT_PROP_POINTER)) return false;
  const hasAbsXY = hasBit(abs, ABS_X) && hasBit(abs, ABS_Y);
  const hasMtXY = hasBit(abs, ABS_MT_POSITION_X) && hasBit(abs, ABS_MT_POSITION_Y);
  if (!hasAbsXY && !hasMtXY) return false;
  if (!hasBit(key, BTN_TOUCH)) return false;
  if (hasBit(key, BTN_TOOL_FINGER) || hasBit(key, BTN_TOOL_PEN) || hasBit(key, BTN_STYLUS)) return false;
  if (hasBit(key, BTN_LEFT)) return false;
  return true;
}

// The physical thing an input device belongs to. A composite USB device
// (touch controller with a keyboard collection, keyboard+touchpad combo, a
// wireless receiver) fans out into several input devices — possibly across
// several USB interfaces — that all hang off one USB *device* directory (the
// one carrying idVendor; interfaces carry bInterfaceNumber instead). For
// Bluetooth the equivalent is the hciN:NNN connection node. Anything else
// (serio, platform, ...) is its own unit.
function physicalUnit(inputDir) {
  let dev;
  try {
    dev = realpathSync(join(inputDir, 'device'));
  } catch (_) {
    return inputDir;
  }
  for (let d = dev; d.length > 1 && d !== '/sys'; d = dirname(d)) {
    if (existsSync(join(d, 'idVendor'))) return d;
    if (/^hci\d+:\d+$/.test(basename(d))) return d;
  }
  return dev;
}

/**
 * Every input device the kernel currently has, with the bits this module
 * cares about. `sysfsRoot` is overridable for tests.
 */
export function listInputDevices(sysfsRoot = '/sys/class/input') {
  let entries;
  try {
    entries = readdirSync(sysfsRoot);
  } catch (_) {
    return []; // no sysfs, e.g. a dev build off-target
  }
  const devices = [];
  for (const entry of entries) {
    if (!/^input\d+$/.test(entry)) continue;
    const dir = join(sysfsRoot, entry);
    const key = parseBitmap(readSysfs(join(dir, 'capabilities/key')));
    const abs = parseBitmap(readSysfs(join(dir, 'capabilities/abs')));
    const props = parseBitmap(readSysfs(join(dir, 'properties')));
    devices.push({
      name: readSysfs(join(dir, 'name')) || entry,
      bustype: parseInt(readSysfs(join(dir, 'id/bustype')) || '0', 16),
      isKeyboard: (key & FULL_KEYBOARD_MASK) === FULL_KEYBOARD_MASK,
      isTouch: isTouchDigitizer(key, abs, props),
      unit: physicalUnit(dir)
    });
  }
  return devices;
}

/** Is there a keyboard someone can type on? See the header comment. */
export function hasTypableKeyboard(devices = listInputDevices()) {
  const touchUnits = new Set(devices.filter((d) => d.isTouch).map((d) => d.unit));
  return devices.some(
    (d) => d.isKeyboard && HOTPLUG_BUSES.has(d.bustype) && !touchUnits.has(d.unit)
  );
}

/** One-line, log-friendly rendering of a device list (with the verdict's inputs). */
export function describeInputDevices(devices) {
  if (!devices.length) return '(no input devices)';
  const touchUnits = new Set(devices.filter((d) => d.isTouch).map((d) => d.unit));
  return devices
    .map((d) => {
      const tags = [`bus=0x${d.bustype.toString(16).padStart(2, '0')}`];
      if (d.isKeyboard) tags.push('kbd');
      if (d.isTouch) tags.push('touch');
      if (d.isKeyboard && HOTPLUG_BUSES.has(d.bustype) && !touchUnits.has(d.unit)) tags.push('TYPABLE');
      else if (d.isKeyboard && touchUnits.has(d.unit)) tags.push('touch-unit');
      return `${d.name} [${tags.join(' ')}]`;
    })
    .join('; ');
}
