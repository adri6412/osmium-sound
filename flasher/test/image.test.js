'use strict';

/**
 * End-to-end test for the image trust chain, against a real HTTP server that
 * speaks Range requests. Covers the cases that decide whether a tampered or
 * truncated image can reach a user's USB stick.
 *
 *   node --test test/*.test.js
 *
 * Fixtures are signed with a throwaway Ed25519 keypair generated here, not with
 * the production OTA key: that key is gitignored and absent on CI runners, and
 * the logic under test does not care which key it is. The separate
 * "shipped public key" test below closes that gap on machines that do hold the
 * real key, and skips where they do not.
 */

const assert = require('node:assert/strict');
const { test, before, after } = require('node:test');
const crypto = require('node:crypto');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const image = require('../src/image');

const REAL_PRIVATE_KEY = path.join(__dirname, '..', '..', 'distro', 'ota-keys', 'ota-signing-key.pem');
const SHIPPED_PUBLIC_KEY = path.join(__dirname, '..', 'assets', 'ota-pubkey.pem');

const IMAGE_NAME = 'hifi-player-v9.9.9-test.iso';
const IMAGE_BYTES = 3 * 1024 * 1024;

let dir;        // fixture root served over HTTP
let cache;      // download target
let server;
let base;
let payload;
let digest;
let signingKey;   // throwaway private key for the fixtures
let PUBLIC_KEY;   // its public half on disk, standing in for the shipped one

/** Reproduces exactly what `sha256sum file > file.sha256` writes. */
function sidecarFor(name, hex) {
  return Buffer.from(`${hex}  ${name}\n`, 'utf8');
}

function sign(buf) {
  return crypto.sign(null, buf, signingKey);
}

function manifest(overrides = {}) {
  const name = overrides.name || IMAGE_NAME;
  return {
    tag_name: 'v9.9.9-test',
    name: 'v9.9.9-test',
    body: '',
    assets: [
      { name, browser_download_url: `${base}/${name}`, size: payload.length },
      { name: `${name}.sha256`, browser_download_url: `${base}/${overrides.shaFile || name + '.sha256'}`, size: 0 },
      { name: `${name}.sha256.sig`, browser_download_url: `${base}/${overrides.sigFile || name + '.sha256.sig'}`, size: 0 },
    ],
  };
}

before(async () => {
  dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-fixture-'));
  cache = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-cache-'));

  const pair = crypto.generateKeyPairSync('ed25519');
  signingKey = pair.privateKey;
  PUBLIC_KEY = path.join(dir, 'test-pubkey.pem');
  await fsp.writeFile(PUBLIC_KEY, pair.publicKey.export({ type: 'spki', format: 'pem' }));

  payload = crypto.randomBytes(IMAGE_BYTES);
  digest = crypto.createHash('sha256').update(payload).digest('hex');

  await fsp.writeFile(path.join(dir, IMAGE_NAME), payload);

  const good = sidecarFor(IMAGE_NAME, digest);
  await fsp.writeFile(path.join(dir, `${IMAGE_NAME}.sha256`), good);
  await fsp.writeFile(path.join(dir, `${IMAGE_NAME}.sha256.sig`), sign(good));

  // A sidecar whose digest was swapped after signing.
  const tampered = sidecarFor(IMAGE_NAME, 'f'.repeat(64));
  await fsp.writeFile(path.join(dir, 'tampered.sha256'), tampered);
  await fsp.writeFile(path.join(dir, 'tampered.sha256.sig'), sign(good)); // old signature

  // A valid signature — but over a different image's sidecar.
  const otherName = 'hifi-player-v0.0.1-other.iso';
  const other = sidecarFor(otherName, digest);
  await fsp.writeFile(path.join(dir, 'other.sha256'), other);
  await fsp.writeFile(path.join(dir, 'other.sha256.sig'), sign(other));

  server = http.createServer((req, res) => {
    const name = decodeURIComponent(req.url.slice(1));
    const file = path.join(dir, name);
    if (!fs.existsSync(file)) {
      res.writeHead(404).end('nope');
      return;
    }
    const size = fs.statSync(file).size;
    const range = req.headers.range;
    if (range) {
      const start = Number(/bytes=(\d+)-/.exec(range)[1]);
      res.writeHead(206, {
        'Content-Range': `bytes ${start}-${size - 1}/${size}`,
        'Content-Length': size - start,
        'Accept-Ranges': 'bytes',
      });
      fs.createReadStream(file, { start }).pipe(res);
      return;
    }
    res.writeHead(200, { 'Content-Length': size, 'Accept-Ranges': 'bytes' });
    fs.createReadStream(file).pipe(res);
  });

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  await fsp.rm(dir, { recursive: true, force: true });
  await fsp.rm(cache, { recursive: true, force: true });
});

test('parses a manifest into a release', async () => {
  await fsp.writeFile(path.join(dir, 'latest.json'), JSON.stringify(manifest()));
  const release = await image.fetchManifest(`${base}/latest.json`);
  assert.equal(release.name, IMAGE_NAME);
  assert.equal(release.version, 'v9.9.9-test');
  assert.ok(release.sigUrl, 'the signature asset must be picked up');
});

test('accepts a correctly signed sidecar and returns its digest', async () => {
  const release = await image.fetchManifest(`${base}/latest.json`);
  assert.equal(await image.fetchVerifiedDigest(release, PUBLIC_KEY), digest);
});

test('downloads, checksums and caches the image', async () => {
  const release = await image.fetchManifest(`${base}/latest.json`);
  const result = await image.prepare(release, cache, PUBLIC_KEY, {});
  assert.equal(result.digest, digest);
  assert.equal(result.size, IMAGE_BYTES);
  assert.ok(fs.existsSync(path.join(cache, IMAGE_NAME)));
});

test('resumes a partial download instead of restarting it', async () => {
  const resumeCache = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-resume-'));
  const half = Math.floor(IMAGE_BYTES / 2);
  await fsp.writeFile(path.join(resumeCache, `${IMAGE_NAME}.part`), payload.subarray(0, half));

  const release = await image.fetchManifest(`${base}/latest.json`);
  let firstReceived = null;
  const result = await image.prepare(release, resumeCache, PUBLIC_KEY, {
    onProgress: (p) => {
      if (p.phase === 'downloading' && firstReceived === null) firstReceived = p.received;
    },
  });

  assert.equal(result.digest, digest, 'a resumed file must still hash correctly');
  assert.ok(firstReceived > half, `progress should start past the resume point, got ${firstReceived}`);
  await fsp.rm(resumeCache, { recursive: true, force: true });
});

test('refuses a sidecar whose digest was altered after signing', async () => {
  const m = manifest({ shaFile: 'tampered.sha256', sigFile: 'tampered.sha256.sig' });
  await fsp.writeFile(path.join(dir, 'tampered.json'), JSON.stringify(m));
  const release = await image.fetchManifest(`${base}/tampered.json`);
  await assert.rejects(
    () => image.fetchVerifiedDigest(release, PUBLIC_KEY),
    (err) => err.code === 'EBADSIG',
  );
});

test('refuses a valid signature that belongs to a different image', async () => {
  const m = manifest({ shaFile: 'other.sha256', sigFile: 'other.sha256.sig' });
  await fsp.writeFile(path.join(dir, 'other.json'), JSON.stringify(m));
  const release = await image.fetchManifest(`${base}/other.json`);
  await assert.rejects(
    () => image.fetchVerifiedDigest(release, PUBLIC_KEY),
    (err) => err.code === 'ENAMEMISMATCH',
  );
});

test('refuses a release with no signature at all', async () => {
  const m = manifest();
  m.assets = m.assets.filter((a) => !a.name.endsWith('.sig'));
  await fsp.writeFile(path.join(dir, 'unsigned.json'), JSON.stringify(m));
  const release = await image.fetchManifest(`${base}/unsigned.json`);
  await assert.rejects(
    () => image.fetchVerifiedDigest(release, PUBLIC_KEY),
    (err) => err.code === 'ENOSIG',
  );
});

test('discards a corrupt download instead of caching it', async () => {
  const badCache = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-bad-'));
  const corruptName = 'corrupt.iso';
  const corrupt = crypto.randomBytes(1024);
  await fsp.writeFile(path.join(dir, corruptName), corrupt);

  // Sidecar signs the *expected* digest; the served bytes are something else.
  const sidecar = sidecarFor(corruptName, digest);
  await fsp.writeFile(path.join(dir, `${corruptName}.sha256`), sidecar);
  await fsp.writeFile(path.join(dir, `${corruptName}.sha256.sig`), sign(sidecar));

  const release = {
    name: corruptName,
    url: `${base}/${corruptName}`,
    size: corrupt.length,
    shaUrl: `${base}/${corruptName}.sha256`,
    sigUrl: `${base}/${corruptName}.sha256.sig`,
  };

  await assert.rejects(
    () => image.prepare(release, badCache, PUBLIC_KEY, {}),
    (err) => err.code === 'EBADSUM',
  );
  assert.equal(fs.existsSync(path.join(badCache, corruptName)), false,
    'a corrupt image must not be left in the cache');
  await fsp.rm(badCache, { recursive: true, force: true });
});

// Runs only where the production private key is present (a maintainer's
// machine, never CI). It is the one check that ties this app to the real OTA
// key: if assets/ota-pubkey.pem ever drifts from the key the workflow signs
// with, every release would be refused by the flasher, and this catches it.
test('the shipped public key matches the real OTA signing key', (t) => {
  if (!fs.existsSync(REAL_PRIVATE_KEY)) {
    t.skip('production signing key not present on this machine');
    return;
  }
  const sidecar = sidecarFor(IMAGE_NAME, digest);
  const realKey = crypto.createPrivateKey(fs.readFileSync(REAL_PRIVATE_KEY));
  const signature = crypto.sign(null, sidecar, realKey);
  const shipped = crypto.createPublicKey(fs.readFileSync(SHIPPED_PUBLIC_KEY));
  assert.ok(
    crypto.verify(null, sidecar, shipped, signature),
    'assets/ota-pubkey.pem does not correspond to distro/ota-keys/ota-signing-key.pem',
  );
});

test('the cache keeps only the image in use', async () => {
  const cacheDir = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-prune-'));
  try {
    // What an appliance owner's cache looks like after a few dev releases.
    await fsp.writeFile(path.join(cacheDir, 'hifi-player-v2.5.21-dev.112.iso'), 'old');
    await fsp.writeFile(path.join(cacheDir, 'hifi-player-v2.5.21-dev.113.iso'), 'older');
    await fsp.writeFile(path.join(cacheDir, IMAGE_NAME), 'current');
    await fsp.writeFile(path.join(cacheDir, `${IMAGE_NAME}.part`), 'resuming');

    const removed = await image.pruneCache(cacheDir, IMAGE_NAME);

    const left = (await fsp.readdir(cacheDir)).sort();
    assert.deepEqual(left, [IMAGE_NAME, `${IMAGE_NAME}.part`].sort(),
      'only the current image and its partial download may survive');
    assert.equal(removed.length, 2);
  } finally {
    await fsp.rm(cacheDir, { recursive: true, force: true });
  }
});

test('pruning an empty or missing cache is harmless', async () => {
  assert.deepEqual(await image.pruneCache(path.join(os.tmpdir(), 'osmium-does-not-exist'), 'x'), []);
});

test('preparing an image clears out earlier ones', async () => {
  // The point of the cache is that reopening the app does not refetch a
  // gigabyte; the point of pruning is that it does not accumulate one per
  // release either.
  const cacheDir = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-prune2-'));
  try {
    const stale = path.join(cacheDir, 'hifi-player-v2.5.21-dev.001.iso');
    await fsp.writeFile(stale, Buffer.alloc(4096));

    const release = await image.fetchManifest(`${base}/latest.json`);
    const result = await image.prepare(release, cacheDir, PUBLIC_KEY, {});

    assert.equal(result.digest, digest);
    assert.equal(fs.existsSync(stale), false, 'the older image should be gone');
    assert.deepEqual(await fsp.readdir(cacheDir), [IMAGE_NAME]);
  } finally {
    await fsp.rm(cacheDir, { recursive: true, force: true });
  }
});

test('a cached image is reused instead of downloaded again', async () => {
  const cacheDir = await fsp.mkdtemp(path.join(os.tmpdir(), 'osmium-reuse-'));
  try {
    await fsp.writeFile(path.join(cacheDir, IMAGE_NAME), payload);

    const release = await image.fetchManifest(`${base}/latest.json`);
    let downloaded = false;
    const result = await image.prepare(release, cacheDir, PUBLIC_KEY, {
      onProgress: (p) => { if (p.phase === 'downloading') downloaded = true; },
    });

    assert.equal(result.digest, digest);
    assert.equal(downloaded, false, 'a complete cached image must not be refetched');
  } finally {
    await fsp.rm(cacheDir, { recursive: true, force: true });
  }
});
