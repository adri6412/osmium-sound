'use strict';

/**
 * Manifest lookup, resumable download and trust chain for the images.
 *
 * Two channels, each with its own manifest next to the files: production
 * (latest.json, stable) and development (latest-dev.json, the newest work).
 * Each may carry two images: the installer ISO, which puts Osmium Sound on the
 * PC's internal disk, and the ready-to-boot USB image (.img.xz), which runs
 * Osmium Sound from the stick itself.
 *
 * The trust chain mirrors the one the appliance already uses for OS updates
 * (distro/config/includes.chroot/usr/local/sbin/hifi-os-update.sh): the small
 * `.sha256` sidecar is what carries the Ed25519 signature, and the image is then
 * checked against the digest inside that signed sidecar. Verifying the sidecar
 * first is what makes the digest itself trustworthy.
 */

const crypto = require('crypto');
const fs = require('fs');
const fsp = require('fs/promises');
const path = require('path');
const { Readable, Transform } = require('stream');
const { pipeline } = require('stream/promises');

const MANIFEST_URL = 'https://file.osmiumsound.it/latest.json';
const MANIFEST_URLS = {
  prod: MANIFEST_URL,
  dev: 'https://file.osmiumsound.it/latest-dev.json',
};
// What each kind of image is called in a manifest.
const KIND_SUFFIX = { iso: '.iso', usb: '.img.xz' };
const MAX_IMAGE_BYTES = 8 * 1024 * 1024 * 1024; // runaway guard, both images are ~1 GB
const MAX_SIDECAR_BYTES = 4096;

class ImageError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    if (status) this.status = status;
  }
}

async function fetchOrThrow(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    throw new ImageError('ENET', `${url}: ${err.message}`);
  }
  if (!res.ok && res.status !== 206) {
    throw new ImageError('EHTTP', `${url}: HTTP ${res.status}`, res.status);
  }
  return res;
}

async function fetchText(url, limit = MAX_SIDECAR_BYTES) {
  const res = await fetchOrThrow(url);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length > limit) throw new ImageError('ETOOBIG', `${url}: unexpectedly large`);
  return buf;
}

/**
 * One image of a manifest, with its sidecars, or null when the manifest does
 * not carry that kind. A listed image without its .sha256 is a broken
 * manifest, not a missing image.
 */
function releaseOf(manifest, kind) {
  const assets = Array.isArray(manifest.assets) ? manifest.assets : [];
  const file = assets.find((a) => a.name && a.name.endsWith(KIND_SUFFIX[kind]));
  if (!file) return null;

  const byName = (suffix) => assets.find((a) => a.name === file.name + suffix);
  const sha = byName('.sha256');
  const sig = byName('.sha256.sig');
  if (!sha) throw new ImageError('EMANIFEST', `manifest lists no .sha256 for ${file.name}`);

  return {
    kind,
    version: manifest.tag_name || manifest.name || 'unknown',
    notes: manifest.body || '',
    name: file.name,
    url: file.browser_download_url,
    size: Number(file.size) || 0,
    // The USB image is compressed: what has to fit on the stick is the disk
    // it unpacks to. Absent from older manifests, so it may be 0.
    rawSize: Number(file.raw_size) || 0,
    shaUrl: sha.browser_download_url,
    sigUrl: sig ? sig.browser_download_url : null,
  };
}

async function readManifest(url) {
  const res = await fetchOrThrow(url, { cache: 'no-store' });
  try {
    return await res.json();
  } catch (err) {
    throw new ImageError('EMANIFEST', `malformed manifest: ${err.message}`);
  }
}

/** Reads a manifest — same shape as the OTA manifests (tag_name + assets[]). */
async function fetchManifest(url = MANIFEST_URL, kind = 'iso') {
  const release = releaseOf(await readManifest(url), kind);
  if (!release) throw new ImageError('EMANIFEST', `manifest lists no ${KIND_SUFFIX[kind]} asset`);
  return release;
}

/**
 * Both channels, each with whichever images it carries:
 *   { prod: { ok, version, iso, usb }, dev: { ok, version, iso, usb } }
 * A channel that cannot be read is { ok: false, code }; one whose manifest is
 * not published at all (no development build out yet) answers ENOTYET rather
 * than an error.
 */
async function fetchCatalog(urls = MANIFEST_URLS) {
  const entries = await Promise.all(Object.entries(urls).map(async ([channel, url]) => {
    try {
      const manifest = await readManifest(url);
      const iso = releaseOf(manifest, 'iso');
      const usb = releaseOf(manifest, 'usb');
      if (!iso && !usb) throw new ImageError('EMANIFEST', 'manifest lists no image');
      return [channel, {
        ok: true, version: manifest.tag_name || manifest.name || 'unknown', iso, usb,
      }];
    } catch (err) {
      const missing = err.code === 'EHTTP' && (err.status === 404 || err.status === 403);
      return [channel, {
        ok: false, code: missing ? 'ENOTYET' : err.code || 'EUNKNOWN', message: err.message,
      }];
    }
  }));
  return Object.fromEntries(entries);
}

/**
 * Verifies the detached Ed25519 signature over the raw bytes of the `.sha256`
 * sidecar and returns the digest it contains. An image whose sidecar is not
 * signed by our key is refused outright — an unsigned build is a tampered build
 * as far as the flasher is concerned.
 */
async function fetchVerifiedDigest(release, publicKeyPath) {
  const sidecar = await fetchText(release.shaUrl);

  if (!release.sigUrl) {
    throw new ImageError('ENOSIG', 'the release carries no .sha256.sig signature');
  }
  const signature = await fetchText(release.sigUrl);

  const publicKey = crypto.createPublicKey(await fsp.readFile(publicKeyPath));
  // Ed25519 is a one-shot algorithm: null algorithm, whole message.
  if (!crypto.verify(null, sidecar, publicKey, signature)) {
    throw new ImageError('EBADSIG', 'signature does not match — refusing the image');
  }

  const text = sidecar.toString('utf8').trim();
  const match = text.match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
  if (!match) throw new ImageError('EBADSHA', 'malformed .sha256 sidecar');

  const [, digest, signedName] = match;
  if (path.basename(signedName.trim()) !== release.name) {
    // Guards against a valid signature for a *different* image being replayed.
    throw new ImageError('ENAMEMISMATCH', `sidecar signs "${signedName.trim()}", not "${release.name}"`);
  }
  return digest.toLowerCase();
}

async function sha256File(file, onProgress, signal) {
  const hash = crypto.createHash('sha256');
  const stream = fs.createReadStream(file, { highWaterMark: 4 * 1024 * 1024 });
  let read = 0;
  for await (const chunk of stream) {
    if (signal && signal.aborted) throw new ImageError('ECANCELLED', 'cancelled');
    hash.update(chunk);
    read += chunk.length;
    if (onProgress) onProgress(read);
  }
  return hash.digest('hex');
}

/**
 * Downloads the image into the cache directory, resuming a previous partial
 * download when the server allows it. Returns the path of the verified file.
 *
 * A 1 GB re-download over a flaky line is exactly the failure the beta testers
 * hit, hence the `.part` file and the Range request.
 */
async function download(release, cacheDir, { onProgress, signal } = {}) {
  await fsp.mkdir(cacheDir, { recursive: true });
  const target = path.join(cacheDir, release.name);
  const part = target + '.part';

  if (fs.existsSync(target)) return target;

  let start = 0;
  try {
    start = (await fsp.stat(part)).size;
  } catch (_) {
    start = 0;
  }
  if (release.size && start > release.size) {
    await fsp.rm(part, { force: true });
    start = 0;
  }

  if (!release.size || start < release.size) {
    const headers = start > 0 ? { Range: `bytes=${start}-` } : {};
    const res = await fetchOrThrow(release.url, { headers, signal, cache: 'no-store' });

    // A server that ignores our Range hands back the whole file: restart cleanly
    // rather than appending a second copy onto the tail of the first.
    if (start > 0 && res.status !== 206) {
      await fsp.rm(part, { force: true });
      start = 0;
    }

    const total = release.size || Number(res.headers.get('content-length')) + start || 0;
    if (total > MAX_IMAGE_BYTES) throw new ImageError('ETOOBIG', 'image exceeds the size guard');

    let received = start;
    const sink = fs.createWriteStream(part, { flags: start > 0 ? 'a' : 'w' });
    const source = Readable.fromWeb(res.body);
    source.on('data', (chunk) => {
      received += chunk.length;
      if (onProgress) onProgress({ phase: 'downloading', received, total });
    });

    try {
      await pipeline(source, sink);
    } catch (err) {
      if (signal && signal.aborted) throw new ImageError('ECANCELLED', 'cancelled');
      throw new ImageError('ENET', `download interrupted: ${err.message}`);
    }
  }

  await fsp.rename(part, target);
  return target;
}

/** Where an .img.xz is unpacked to: the same name without .xz. */
function unpackedName(name) {
  return name.replace(/\.xz$/i, '');
}

/**
 * Unpacks a verified .img.xz next to itself and returns the raw image.
 *
 * Done here, before the write, and not by etcher-sdk while it writes: its
 * on-the-fly XzSource put the system 16 MiB off its place on a slow
 * destination (alpha27's image, 3.2 GB onto a file standing in for a stick:
 * the stream itself hashed right, the device did not, and the verify pass
 * refused it). Unpacked first, the USB image takes the same write path as the
 * ISO, the one with the field record.
 *
 * xz carries its own CRC64 per block, so a damaged archive fails here; the
 * archive itself was checked against the signed digest just before.
 */
async function unpack(xzFile, { onProgress, signal, total = 0 } = {}) {
  // Loaded on demand: a native addon, only needed for the USB image.
  const lzma = require('lzma-native');
  const target = unpackedName(xzFile);
  const part = target + '.part';
  await fsp.rm(target, { force: true });

  let done = 0;
  const count = new Transform({
    transform(chunk, _enc, cb) {
      done += chunk.length;
      if (onProgress) onProgress({ phase: 'unpacking', received: done, total });
      cb(null, chunk);
    },
  });
  try {
    await pipeline(
      fs.createReadStream(xzFile, { highWaterMark: 4 * 1024 * 1024 }),
      lzma.createDecompressor(),
      count,
      fs.createWriteStream(part),
      { signal },
    );
  } catch (err) {
    await fsp.rm(part, { force: true });
    if (signal && signal.aborted) throw new ImageError('ECANCELLED', 'cancelled');
    if (err.code === 'ENOSPC') throw new ImageError('ENOSPACE', 'not enough free space to unpack the image');
    throw new ImageError('EIMAGE', `the image could not be unpacked: ${err.message}`);
  }
  await fsp.rename(part, target);
  return target;
}

/**
 * Drops every cached image except the one about to be used.
 *
 * Images are kept so that reopening the app, or writing a second stick, does not
 * mean fetching a gigabyte again. Keeping *all* of them is another matter: each
 * dev release would leave another gigabyte behind for good, on a channel that
 * publishes often. Exactly one is kept, along with its partial download.
 */
async function pruneCache(cacheDir, keepName) {
  let entries;
  try {
    entries = await fsp.readdir(cacheDir);
  } catch (_) {
    return [];                       // nothing cached yet
  }
  // An .img.xz comes with the raw image unpacked from it.
  const raw = unpackedName(keepName);
  const keep = new Set([keepName, `${keepName}.part`, raw, `${raw}.part`]);
  const removed = [];
  for (const name of entries) {
    if (keep.has(name)) continue;
    try {
      await fsp.rm(path.join(cacheDir, name), { force: true, recursive: true });
      removed.push(name);
    } catch (_) {
      /* a file we cannot remove is not worth failing the write over */
    }
  }
  return removed;
}

/**
 * Full prepare step: manifest → signed digest → download (or reuse cache) →
 * checksum → for the USB image, unpack. Throws with a `code` the UI maps to a
 * translated message.
 */
async function prepare(release, cacheDir, publicKeyPath, { onProgress, signal } = {}) {
  const expected = await fetchVerifiedDigest(release, publicKeyPath);
  await pruneCache(cacheDir, release.name);
  const file = await download(release, cacheDir, { onProgress, signal });

  const size = (await fsp.stat(file)).size;
  const actual = await sha256File(
    file,
    (read) => onProgress && onProgress({ phase: 'checking', received: read, total: size }),
    signal,
  );

  if (actual !== expected) {
    // A corrupt cache must not be sticky: drop it so the next run refetches.
    await fsp.rm(file, { force: true });
    throw new ImageError('EBADSUM', 'the downloaded image is corrupt — it has been discarded');
  }
  if (!/\.xz$/i.test(release.name)) return { file, size, digest: actual };

  // Unpacked every time rather than trusted from an earlier run: the archive
  // is what the signature vouches for, not a file left lying in the cache.
  const raw = await unpack(file, { onProgress, signal, total: release.rawSize || 0 });
  return { file: raw, size: (await fsp.stat(raw)).size, digest: actual };
}

module.exports = {
  ImageError,
  MANIFEST_URL,
  MANIFEST_URLS,
  fetchManifest,
  fetchCatalog,
  fetchVerifiedDigest,
  pruneCache,
  unpack,
  download,
  sha256File,
  prepare,
};
