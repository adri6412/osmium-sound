'use strict';

/**
 * Minimal MBR + FAT32 writer.
 *
 * Enough to turn a USB stick into a single empty FAT32 volume, and to populate
 * it with a directory tree. It is deliberately write-once: the volume is always
 * built from scratch, so clusters are handed out linearly and there is no free
 * list to consult, no fragmentation, and nothing to reclaim. That removes most
 * of what makes a general FAT implementation hard.
 *
 * Field layouts follow Microsoft's FAT specification; the offsets in the
 * comments are the ones from that document, so they can be checked against it.
 */

const SECTOR = 512;
const PARTITION_START = 2048;   // 1 MiB in, the usual alignment for flash media
const RESERVED_SECTORS = 32;
const NUM_FATS = 2;
const ROOT_CLUSTER = 2;
const MEDIA_DESCRIPTOR = 0xf8;
const FAT32_MIN_CLUSTERS = 65525;   // below this it would have to be FAT16

const ATTR_READ_ONLY = 0x01;
const ATTR_HIDDEN = 0x02;
const ATTR_SYSTEM = 0x04;
const ATTR_VOLUME_ID = 0x08;
const ATTR_DIRECTORY = 0x10;
const ATTR_ARCHIVE = 0x20;
const ATTR_LONG_NAME = ATTR_READ_ONLY | ATTR_HIDDEN | ATTR_SYSTEM | ATTR_VOLUME_ID;

/**
 * Cluster size by volume size, following the table Windows itself uses. Bigger
 * clusters waste space on small files but keep the FAT small enough to write
 * quickly — a 32 GB stick with 4 KB clusters would need a 64 MB FAT.
 */
function sectorsPerClusterFor(partitionSectors) {
  const bytes = partitionSectors * SECTOR;
  const GB = 1024 * 1024 * 1024;
  if (bytes <= 8 * GB) return 8;        // 4 KiB
  if (bytes <= 16 * GB) return 16;      // 8 KiB
  if (bytes <= 32 * GB) return 32;      // 16 KiB
  return 64;                            // 32 KiB
}

function computeGeometry(deviceSectors) {
  if (deviceSectors <= PARTITION_START + 1024) {
    throw new Error('device is too small for a FAT32 volume');
  }
  const partitionSectors = deviceSectors - PARTITION_START;
  const sectorsPerCluster = sectorsPerClusterFor(partitionSectors);

  // FAT size, straight from the reference implementation in the FAT spec.
  const tmp1 = partitionSectors - RESERVED_SECTORS;
  const tmp2 = Math.floor((256 * sectorsPerCluster + NUM_FATS) / 2);
  const fatSectors = Math.ceil(tmp1 / tmp2);

  const dataSectors = partitionSectors - RESERVED_SECTORS - NUM_FATS * fatSectors;
  const clusterCount = Math.floor(dataSectors / sectorsPerCluster);
  if (clusterCount < FAT32_MIN_CLUSTERS) {
    throw new Error(`volume yields ${clusterCount} clusters, too few for FAT32`);
  }

  return {
    deviceSectors,
    partitionStart: PARTITION_START,
    partitionSectors,
    sectorsPerCluster,
    clusterBytes: sectorsPerCluster * SECTOR,
    reservedSectors: RESERVED_SECTORS,
    numFats: NUM_FATS,
    fatSectors,
    clusterCount,
    // Absolute LBA, i.e. counted from the start of the device, not the volume.
    fatStart: PARTITION_START + RESERVED_SECTORS,
    dataStart: PARTITION_START + RESERVED_SECTORS + NUM_FATS * fatSectors,
  };
}

/** CHS triple for an LBA, saturating at the classic (1023, 254, 63) ceiling. */
function chs(lba) {
  const HEADS = 255;
  const SECTORS = 63;
  let c = Math.floor(lba / (HEADS * SECTORS));
  let h = Math.floor(lba / SECTORS) % HEADS;
  let s = (lba % SECTORS) + 1;
  if (c > 1023) { c = 1023; h = 254; s = 63; }
  return [h, ((c >> 2) & 0xc0) | s, c & 0xff];
}

function buildMbr(geo, diskSignature) {
  const mbr = Buffer.alloc(SECTOR);

  // Windows identifies a disk by this signature and treats a zeroed one as an
  // uninitialised disk, offering to initialise it rather than reading the
  // partition. Every real formatter writes one.
  mbr.writeUInt32LE((diskSignature >>> 0) || 0xa1b2c3d4, 0x1b8);

  const p = 0x1be;                       // first partition entry

  mbr[p] = 0x00;                         // not marked active: UEFI does not care
  const [h1, s1, c1] = chs(geo.partitionStart);
  mbr[p + 1] = h1; mbr[p + 2] = s1; mbr[p + 3] = c1;

  // 0x0C = FAT32 with LBA addressing, what USB installers conventionally use.
  mbr[p + 4] = 0x0c;

  const [h2, s2, c2] = chs(geo.partitionStart + geo.partitionSectors - 1);
  mbr[p + 5] = h2; mbr[p + 6] = s2; mbr[p + 7] = c2;

  mbr.writeUInt32LE(geo.partitionStart, p + 8);
  mbr.writeUInt32LE(geo.partitionSectors, p + 12);
  mbr.writeUInt16LE(0xaa55, 0x1fe);
  return mbr;
}

/** Volume labels live in the boot sector as 11 padded, upper-case bytes. */
function padLabel(label) {
  const clean = (label || 'NO NAME').toUpperCase().replace(/[^A-Z0-9 _-]/g, '');
  return Buffer.from(clean.padEnd(11, ' ').slice(0, 11), 'ascii');
}

function buildBootSector(geo, { label, volumeId }) {
  const bs = Buffer.alloc(SECTOR);
  bs[0] = 0xeb; bs[1] = 0x58; bs[2] = 0x90;              // jmp short + nop
  bs.write('MSWIN4.1', 0x03, 8, 'ascii');                 // OEM name

  bs.writeUInt16LE(SECTOR, 0x0b);                         // bytes per sector
  bs[0x0d] = geo.sectorsPerCluster;
  bs.writeUInt16LE(geo.reservedSectors, 0x0e);
  bs[0x10] = geo.numFats;
  bs.writeUInt16LE(0, 0x11);                              // root entries: FAT32 = 0
  bs.writeUInt16LE(0, 0x13);                              // total sectors 16: unused
  bs[0x15] = MEDIA_DESCRIPTOR;
  bs.writeUInt16LE(0, 0x16);                              // FAT size 16: unused
  bs.writeUInt16LE(63, 0x18);                             // sectors per track
  bs.writeUInt16LE(255, 0x1a);                            // heads
  bs.writeUInt32LE(geo.partitionStart, 0x1c);             // hidden sectors
  bs.writeUInt32LE(geo.partitionSectors, 0x20);

  bs.writeUInt32LE(geo.fatSectors, 0x24);
  bs.writeUInt16LE(0, 0x28);                              // ext flags: FATs mirrored
  bs.writeUInt16LE(0, 0x2a);                              // filesystem version
  bs.writeUInt32LE(ROOT_CLUSTER, 0x2c);
  bs.writeUInt16LE(1, 0x30);                              // FSInfo sector
  bs.writeUInt16LE(6, 0x32);                              // backup boot sector

  bs[0x40] = 0x80;                                        // drive number
  bs[0x42] = 0x29;                                        // extended boot signature
  bs.writeUInt32LE(volumeId >>> 0, 0x43);
  padLabel(label).copy(bs, 0x47);
  bs.write('FAT32   ', 0x52, 8, 'ascii');

  bs.writeUInt16LE(0xaa55, 0x1fe);
  return bs;
}

function buildFsInfo(freeClusters, nextFree) {
  const fs = Buffer.alloc(SECTOR);
  fs.writeUInt32LE(0x41615252, 0x000);                    // "RRaA"
  fs.writeUInt32LE(0x61417272, 0x1e4);                    // "rrAa"
  fs.writeUInt32LE(freeClusters >>> 0, 0x1e8);
  fs.writeUInt32LE(nextFree >>> 0, 0x1ec);
  fs.writeUInt32LE(0xaa550000, 0x1fc);
  return fs;
}

/**
 * Writes an empty MBR + FAT32 volume.
 *
 * @param {(buf: Buffer, byteOffset: number) => Promise<void>} writeAt
 * @param {object} geo      from computeGeometry()
 * @param {object} [opts]   { label, volumeId, onProgress }
 */
async function writeEmptyVolume(writeAt, geo, opts = {}) {
  const label = opts.label || 'OSMIUM';
  const volumeId = opts.volumeId >>> 0 || 0x4f534d55;
  const onProgress = opts.onProgress || (() => {});

  const sectorAt = (lba) => lba * SECTOR;

  // Order matters, and not for tidiness. Windows mounts a volume the moment a
  // valid partition table points at one, so stamping the MBR first would let it
  // mount the stick while the FAT is still being zeroed — it would then cache an
  // inconsistent view and write its own stale metadata back over ours. The
  // partition table therefore goes in last, once everything it points at is
  // already on the device. etcher-sdk withholds the first 64 KB during an image
  // write for exactly this reason.

  // The FAT has to be zeroed rather than merely stamped: whatever the stick held
  // before would otherwise read as a live cluster chain.
  const CHUNK_SECTORS = 2048;                                  // 1 MiB at a time
  const zeros = Buffer.alloc(CHUNK_SECTORS * SECTOR);
  const first = Buffer.alloc(SECTOR);
  first.writeUInt32LE(0x0ffffff8, 0);                          // media descriptor
  first.writeUInt32LE(0x0fffffff, 4);                          // end of chain
  first.writeUInt32LE(0x0fffffff, 8);                          // root dir, cluster 2

  for (let fat = 0; fat < geo.numFats; fat += 1) {
    const start = geo.fatStart + fat * geo.fatSectors;
    for (let done = 0; done < geo.fatSectors; done += CHUNK_SECTORS) {
      const count = Math.min(CHUNK_SECTORS, geo.fatSectors - done);
      await writeAt(zeros.subarray(0, count * SECTOR), sectorAt(start + done));
      onProgress({ phase: 'formatting', done: done + count, total: geo.fatSectors * geo.numFats });
    }
    await writeAt(first, sectorAt(start));
  }

  // Clear the root directory cluster, then name the volume inside it as well:
  // some tools read the label from here rather than from the boot sector.
  const rootCluster = Buffer.alloc(geo.clusterBytes);
  const entry = padLabel(label);
  entry.copy(rootCluster, 0);
  rootCluster[11] = ATTR_VOLUME_ID;
  await writeAt(rootCluster, sectorAt(geo.dataStart));

  // Now the volume itself: boot sector, its backup, and the free-space hints.
  const boot = buildBootSector(geo, { label, volumeId });
  await writeAt(boot, sectorAt(geo.partitionStart));
  await writeAt(boot, sectorAt(geo.partitionStart + 6));

  // The root directory already holds one cluster.
  const fsInfo = buildFsInfo(geo.clusterCount - 1, ROOT_CLUSTER + 1);
  await writeAt(fsInfo, sectorAt(geo.partitionStart + 1));
  await writeAt(fsInfo, sectorAt(geo.partitionStart + 7));

  // Only now does the stick become mountable.
  await writeAt(buildMbr(geo, opts.diskSignature), 0);
}

module.exports = {
  writeEmptyVolume,
  SECTOR,
  PARTITION_START,
  ROOT_CLUSTER,
  ATTR_DIRECTORY,
  ATTR_ARCHIVE,
  ATTR_VOLUME_ID,
  ATTR_LONG_NAME,
  computeGeometry,
  buildMbr,
  buildBootSector,
  buildFsInfo,
  padLabel,
};
