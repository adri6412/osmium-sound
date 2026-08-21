'use strict';

/**
 * Manifest lookup, resumable download and trust chain for the installer image.
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
const { Readable } = require('stream');
const { pipeline } = require('stream/promises');

const MANIFEST_URL = 'https://file.osmiumsound.it/latest.json';
const MAX_IMAGE_BYTES = 8 * 1024 * 1024 * 1024; // runaway guard, the ISO is ~1 GB
const MAX_SIDECAR_BYTES = 4096;

class ImageError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
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
    throw new ImageError('EHTTP', `${url}: HTTP ${res.status}`);
  }
  return res;
}

async function fetchText(url, limit = MAX_SIDECAR_BYTES) {
  const res = await fetchOrThrow(url);
  const buf = Buffer.from(await res.arrayBuffer());
  if (buf.length > limit) throw new ImageError('ETOOBIG', `${url}: unexpectedly large`);
  return buf;
}

/** Reads latest.json — same shape as the OTA manifests (tag_name + assets[]). */
async function fetchManifest(url = MANIFEST_URL) {
  const res = await fetchOrThrow(url, { cache: 'no-store' });
  let manifest;
  try {
    manifest = await res.json();
  } catch (err) {
    throw new ImageError('EMANIFEST', `malformed manifest: ${err.message}`);
  }
  const assets = Array.isArray(manifest.assets) ? manifest.assets : [];
  const iso = assets.find((a) => a.name && a.name.endsWith('.iso'));
  if (!iso) throw new ImageError('EMANIFEST', 'manifest lists no .iso asset');

  const byName = (suffix) => assets.find((a) => a.name === iso.name + suffix);
  const sha = byName('.sha256');
  const sig = byName('.sha256.sig');
  if (!sha) throw new ImageError('EMANIFEST', 'manifest lists no .sha256 for the image');

  return {
    version: manifest.tag_name || manifest.name || 'unknown',
    notes: manifest.body || '',
    name: iso.name,
    url: iso.browser_download_url,
    size: Number(iso.size) || 0,
    shaUrl: sha.browser_download_url,
    sigUrl: sig ? sig.browser_download_url : null,
  };
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

/**
 * Full prepare step: manifest → signed digest → download (or reuse cache) →
 * checksum. Throws with a `code` the UI maps to a translated message.
 */
async function prepare(release, cacheDir, publicKeyPath, { onProgress, signal } = {}) {
  const expected = await fetchVerifiedDigest(release, publicKeyPath);
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
  return { file, size, digest: actual };
}

module.exports = {
  ImageError,
  MANIFEST_URL,
  fetchManifest,
  fetchVerifiedDigest,
  download,
  sha256File,
  prepare,
};
