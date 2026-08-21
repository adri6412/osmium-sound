'use strict';

/**
 * Structural checks on the MBR + FAT32 writer used by the restore mode.
 *
 * The volume is written by hand, field by field, so a transposed offset or a
 * miscounted FAT would produce something that looks plausible and mounts
 * nowhere. These assertions read the bytes back at the offsets given in
 * Microsoft's FAT specification, independently of the constants the writer used.
 */

const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

const fat32 = require('../helper/fat32');

const GB = 1024 * 1024 * 1024;

test('geometry stays within what FAT32 allows, at every stick size', () => {
  for (const gb of [1, 4, 8, 16, 32, 64, 128, 256]) {
    const geo = fat32.computeGeometry(Math.floor((gb * GB) / 512));

    assert.ok(geo.clusterCount >= 65525,
      `${gb} GB yields ${geo.clusterCount} clusters, below the FAT32 minimum`);
    assert.ok(geo.clusterCount < 0x0ffffff5,
      `${gb} GB exceeds the FAT32 cluster ceiling`);

    // Every cluster must be addressable by the FAT we sized.
    const entriesPerFat = (geo.fatSectors * 512) / 4;
    assert.ok(entriesPerFat >= geo.clusterCount + 2,
      `${gb} GB: FAT holds ${entriesPerFat} entries for ${geo.clusterCount} clusters`);

    // Data must start on a cluster boundary relative to the volume.
    const dataOffset = geo.dataStart - geo.partitionStart;
    assert.equal((dataOffset - geo.reservedSectors - geo.numFats * geo.fatSectors), 0);
    assert.ok([8, 16, 32, 64].includes(geo.sectorsPerCluster));
  }
});

test('a device too small to hold a FAT32 volume is refused', () => {
  assert.throws(() => fat32.computeGeometry(100), /too small/);
  // 64 MB cannot reach 65525 clusters at the smallest cluster size we use.
  assert.throws(() => fat32.computeGeometry((64 * 1024 * 1024) / 512), /too few/);
});

test('the written volume matches the on-disk layout FAT32 defines', async () => {
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-fat-'));
  const image = path.join(dir, 'stick.img');
  const SIZE = 2 * GB;

  try {
    const fd = fs.openSync(image, 'w');
    fs.ftruncateSync(fd, SIZE);                     // sparse: nothing is allocated yet
    const geo = fat32.computeGeometry(SIZE / 512);

    await fat32.writeEmptyVolume(
      async (buf, offset) => { fs.writeSync(fd, buf, 0, buf.length, offset); },
      geo,
      { label: 'OSMIUM', volumeId: 0x12345678 },
    );
    fs.closeSync(fd);

    const read = (offset, length) => {
      const buf = Buffer.alloc(length);
      const f = fs.openSync(image, 'r');
      fs.readSync(f, buf, 0, length, offset);
      fs.closeSync(f);
      return buf;
    };

    // ── MBR ──
    const mbr = read(0, 512);
    assert.equal(mbr.readUInt16LE(0x1fe), 0xaa55, 'MBR signature');
    assert.equal(mbr[0x1be + 4], 0x0c, 'partition type must be FAT32 LBA');
    assert.equal(mbr.readUInt32LE(0x1be + 8), geo.partitionStart);
    assert.equal(mbr.readUInt32LE(0x1be + 12), geo.partitionSectors);
    // The partition must not claim sectors past the end of the device.
    assert.ok(geo.partitionStart + geo.partitionSectors <= SIZE / 512);

    // ── boot sector, and its backup at +6 ──
    const boot = read(geo.partitionStart * 512, 512);
    assert.equal(boot.readUInt16LE(0x1fe), 0xaa55, 'boot sector signature');
    assert.equal(boot.readUInt16LE(0x0b), 512, 'bytes per sector');
    assert.equal(boot[0x0d], geo.sectorsPerCluster);
    assert.equal(boot.readUInt16LE(0x0e), geo.reservedSectors);
    assert.equal(boot[0x10], geo.numFats);
    assert.equal(boot.readUInt16LE(0x11), 0, 'FAT32 has no fixed root directory');
    assert.equal(boot.readUInt16LE(0x13), 0, 'total sectors 16 must defer to the 32-bit field');
    assert.equal(boot.readUInt16LE(0x16), 0, 'FAT size 16 must defer to the 32-bit field');
    assert.equal(boot.readUInt32LE(0x20), geo.partitionSectors);
    assert.equal(boot.readUInt32LE(0x24), geo.fatSectors);
    assert.equal(boot.readUInt32LE(0x2c), 2, 'root directory cluster');
    assert.equal(boot.readUInt16LE(0x30), 1, 'FSInfo sector');
    assert.equal(boot.readUInt16LE(0x32), 6, 'backup boot sector');
    assert.equal(boot.readUInt32LE(0x1c), geo.partitionStart, 'hidden sectors');
    assert.equal(boot.subarray(0x52, 0x5a).toString('ascii'), 'FAT32   ');
    assert.equal(boot.subarray(0x47, 0x52).toString('ascii'), 'OSMIUM     ');

    const backup = read((geo.partitionStart + 6) * 512, 512);
    assert.ok(backup.equals(boot), 'the backup boot sector must be identical');

    // ── FSInfo ──
    const info = read((geo.partitionStart + 1) * 512, 512);
    assert.equal(info.readUInt32LE(0x000), 0x41615252);
    assert.equal(info.readUInt32LE(0x1e4), 0x61417272);
    assert.equal(info.readUInt32LE(0x1fc), 0xaa550000);

    // ── both FATs ──
    for (let i = 0; i < geo.numFats; i += 1) {
      const at = (geo.fatStart + i * geo.fatSectors) * 512;
      const table = read(at, 16);
      assert.equal(table.readUInt32LE(0) & 0x0fffffff, 0x0ffffff8, `FAT ${i} media descriptor`);
      assert.equal(table.readUInt32LE(4), 0x0fffffff, `FAT ${i} end-of-chain marker`);
      assert.equal(table.readUInt32LE(8), 0x0fffffff, `FAT ${i} root directory chain`);
      assert.equal(table.readUInt32LE(12), 0, `FAT ${i} cluster 3 must be free`);
    }

    // ── root directory holds the volume label and nothing else ──
    const root = read(geo.dataStart * 512, 64);
    assert.equal(root.subarray(0, 11).toString('ascii'), 'OSMIUM     ');
    assert.equal(root[11] & fat32.ATTR_VOLUME_ID, fat32.ATTR_VOLUME_ID);
    assert.equal(root[32], 0, 'nothing must follow the label entry');
  } finally {
    await fsp.rm(dir, { recursive: true, force: true });
  }
});

test('the helper dispatches on mode before it needs an image', () => {
  // A restore carries no --image. When the dispatch to restore() was missing,
  // the helper fell through to the image path and died on `new File({path:
  // undefined})` — reported as a write failure, pointing nowhere near the cause.
  const src = fs.readFileSync(path.join(__dirname, '..', 'helper', 'writer.js'), 'utf8');

  const dispatch = src.search(/if \(mode === 'restore'\)/);
  const usesImage = src.search(/new sourceDestination\.File\(/);
  assert.ok(dispatch !== -1, 'the restore branch is missing');
  assert.ok(usesImage !== -1, 'the image source is missing');
  assert.ok(dispatch < usesImage,
    'restore must be dispatched before the image path is entered');

  assert.match(src, /async function restore\(/, 'restore() itself is missing');
  assert.match(src, /if \(mode !== 'write'\)/,
    'an unhandled mode must be rejected rather than falling through');
});

test('the partition table is the last thing written', async () => {
  // Windows mounts a volume as soon as a partition table points at one. If the
  // MBR went down first, it could mount the stick while the FAT was still being
  // zeroed, cache an inconsistent view, and write its own stale metadata back
  // over ours — which is what left a freshly restored stick unreadable.
  const geo = fat32.computeGeometry((2 * GB) / 512);

  const offsets = [];
  await fat32.writeEmptyVolume(async (buf, offset) => { offsets.push(offset); }, geo, {});

  assert.equal(offsets[offsets.length - 1], 0,
    'the MBR must be written last, after everything it points at');
  assert.ok(offsets.filter((o) => o === 0).length === 1, 'the MBR is written once');

  // And the boot sector must follow the FAT it describes.
  const bootAt = geo.partitionStart * 512;
  const firstFatAt = geo.fatStart * 512;
  assert.ok(offsets.indexOf(firstFatAt) < offsets.indexOf(bootAt),
    'the FAT must be in place before the boot sector advertises it');
});

test('the MBR carries a non-zero disk signature', async () => {
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-sig-'));
  try {
    const image = path.join(dir, 'stick.img');
    const fd = fs.openSync(image, 'w');
    fs.ftruncateSync(fd, 2 * GB);
    const geo = fat32.computeGeometry((2 * GB) / 512);
    await fat32.writeEmptyVolume(
      async (buf, offset) => { fs.writeSync(fd, buf, 0, buf.length, offset); },
      geo, { label: 'OSMIUM', diskSignature: 0xdeadbeef },
    );
    fs.closeSync(fd);

    const mbr = Buffer.alloc(512);
    const f = fs.openSync(image, 'r');
    fs.readSync(f, mbr, 0, 512, 0);
    fs.closeSync(f);

    assert.equal(mbr.readUInt32LE(0x1b8), 0xdeadbeef, 'disk signature');
    // A zero signature is what makes Windows offer to initialise the disk.
    assert.notEqual(mbr.readUInt32LE(0x1b8), 0);
  } finally {
    await fsp.rm(dir, { recursive: true, force: true });
  }
});
