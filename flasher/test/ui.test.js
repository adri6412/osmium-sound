'use strict';

/**
 * Static checks on the UI that a headless environment can still make.
 *
 * The bilingual one matters beyond tidiness: every user-visible string in this
 * project has to exist in both English and Italian, and a missing key here
 * silently renders as the raw key name at run time.
 */

const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');

const SRC = path.join(__dirname, '..', 'src');
const html = fs.readFileSync(path.join(SRC, 'index.html'), 'utf8');
const renderer = fs.readFileSync(path.join(SRC, 'renderer.js'), 'utf8');

function dictionary(lang) {
  const block = new RegExp(`\\n  ${lang}: \\{([\\s\\S]*?)\\n  \\},`).exec(renderer);
  assert.ok(block, `no ${lang} block found in renderer.js`);
  return new Set([...block[1].matchAll(/^\s*'([^']+)':/gm)].map((m) => m[1]));
}

test('every string exists in both English and Italian', () => {
  const en = dictionary('en');
  const it = dictionary('it');

  const missingIt = [...en].filter((k) => !it.has(k));
  const missingEn = [...it].filter((k) => !en.has(k));

  assert.deepEqual(missingIt, [], `keys missing from the Italian dictionary: ${missingIt}`);
  assert.deepEqual(missingEn, [], `keys missing from the English dictionary: ${missingEn}`);
  assert.ok(en.size > 20, 'the dictionary looks suspiciously small');
});

test('every data-i18n key in the markup is translated', () => {
  const en = dictionary('en');
  const used = [...html.matchAll(/data-i18n="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(used.length > 0, 'no data-i18n attributes found');
  const unknown = used.filter((k) => !en.has(k));
  assert.deepEqual(unknown, [], `markup references untranslated keys: ${unknown}`);
});

test('every element the renderer looks up exists in the markup', () => {
  const ids = new Set([...html.matchAll(/id="([^"]+)"/g)].map((m) => m[1]));
  const looked = [...renderer.matchAll(/\$\('([^']+)'\)/g)].map((m) => m[1]);
  const missing = [...new Set(looked)].filter((id) => !ids.has(id));
  assert.deepEqual(missing, [], `renderer.js queries ids absent from index.html: ${missing}`);
});

test('every screen the flow switches to exists in the markup', () => {
  const screens = [...renderer.matchAll(/show\('([a-z]+)'\)/g)].map((m) => m[1]);
  const ids = new Set([...html.matchAll(/id="(screen[A-Za-z]+)"/g)].map((m) => m[1]));
  const missing = [...new Set(screens)]
    .map((s) => 'screen' + s[0].toUpperCase() + s.slice(1))
    .filter((id) => !ids.has(id));
  assert.deepEqual(missing, [], `flow shows screens that do not exist: ${missing}`);
});

test('the support address is the project one, not a personal mailbox', () => {
  assert.ok(/support@osmiumsound\.it/.test(renderer), 'support address missing');
  assert.ok(!/gmail\.com/.test(renderer), 'a personal address leaked into the UI');
});

test('the renderer never reaches for Node directly', () => {
  // contextIsolation is on; anything here would be a real bug, not a style nit.
  assert.ok(!/\brequire\(/.test(renderer), 'renderer.js must go through the preload bridge');
});

test('the [hidden] attribute is not defeated by a layout rule', () => {
  // Several elements are shown and hidden purely through the `hidden`
  // attribute, and the UA rule that implements it has zero specificity: a
  // single `label.check { display: flex }` is enough to pin one permanently
  // on screen. The explicit guard is what keeps that from happening.
  const css = fs.readFileSync(path.join(SRC, 'style.css'), 'utf8');
  const guard = /\[hidden\]\s*\{[^}]*display:\s*none\s*!important/.test(css);
  assert.ok(guard, 'style.css must force [hidden] { display: none !important }');

  // And the guard has to come before the rules it neutralises.
  const guardAt = css.search(/\[hidden\]\s*\{/);
  const firstDisplay = css.search(/^[^@\n]*\{[^}]*display:/m);
  assert.ok(guardAt <= firstDisplay || firstDisplay === -1,
    'the [hidden] guard must precede the layout rules');
});

test('every screen belongs to a wizard phase', () => {
  // The stepper is driven by PHASE_OF; a screen missing from it would leave the
  // phase indicator stuck on whatever was highlighted before.
  const screens = [...html.matchAll(/id="screen([A-Za-z]+)"/g)]
    .map((m) => m[1][0].toLowerCase() + m[1].slice(1));

  const phaseOf = /const PHASE_OF = \{([\s\S]*?)\};/.exec(renderer);
  assert.ok(phaseOf, 'PHASE_OF not found in renderer.js');
  const mapped = new Set([...phaseOf[1].matchAll(/(\w+):\s*'(\w+)'/g)].map((m) => m[1]));

  // The error screen deliberately keeps whichever phase was already showing.
  const unmapped = screens.filter((s) => s !== 'error' && !mapped.has(s));
  assert.deepEqual(unmapped, [], `screens with no phase: ${unmapped}`);

  const order = /const PHASE_ORDER = \[([^\]]*)\]/.exec(renderer);
  assert.ok(order, 'PHASE_ORDER not found');
  const phases = new Set([...order[1].matchAll(/'(\w+)'/g)].map((m) => m[1]));

  const markupPhases = [...html.matchAll(/data-phase="(\w+)"/g)].map((m) => m[1]);
  assert.ok(markupPhases.length > 0, 'the stepper has no steps');
  const strays = markupPhases.filter((p) => !phases.has(p));
  assert.deepEqual(strays, [], `stepper steps absent from PHASE_ORDER: ${strays}`);
});

test('the markup is well formed and every screen is closed', () => {
  // A stray or unclosed tag would swallow the rest of the wizard silently.
  const opens = (html.match(/<section class="screen/g) || []).length;
  const closes = (html.match(/<\/section>/g) || []).length;
  assert.equal(opens, closes, 'unbalanced <section> tags');

  for (const tag of ['div', 'ol', 'ul', 'nav', 'footer', 'main', 'header']) {
    const o = (html.match(new RegExp(`<${tag}[\\s>]`, 'g')) || []).length;
    const c = (html.match(new RegExp(`</${tag}>`, 'g')) || []).length;
    assert.equal(o, c, `unbalanced <${tag}> tags: ${o} open, ${c} closed`);
  }
});

test('the app icons are square and large enough for every target', () => {
  // electron-builder derives the Windows .ico and the macOS .icns from
  // build/icon.png, and refuses anything under 256 and 512 respectively. A
  // non-square source is silently distorted rather than rejected.
  const png = (file) => {
    const buf = fs.readFileSync(file);
    assert.ok(buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])),
      `${file} is not a PNG`);
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
  };

  const master = png(path.join(__dirname, '..', 'build', 'icon.png'));
  assert.equal(master.width, master.height, 'build/icon.png must be square');
  assert.ok(master.width >= 512, `build/icon.png is ${master.width}px, macOS needs 512+`);

  const window = png(path.join(__dirname, '..', 'assets', 'icon.png'));
  assert.equal(window.width, window.height, 'assets/icon.png must be square');
  assert.ok(window.width >= 256, `assets/icon.png is ${window.width}px`);
});

test('every platform points at the icon, and the window sets its own', () => {
  const yml = fs.readFileSync(path.join(__dirname, '..', 'electron-builder.yml'), 'utf8');
  assert.equal((yml.match(/^\s+icon: build\/icon\.png$/gm) || []).length, 3,
    'win, linux and mac must each declare the icon');

  const main = fs.readFileSync(path.join(__dirname, '..', 'src', 'main.js'), 'utf8');
  assert.match(main, /icon: path\.join\(__dirname, '\.\.', 'assets', 'icon\.png'\)/,
    'the BrowserWindow icon is missing — Linux would show a blank window icon');
});

test('the macOS build is ad-hoc signed, not left unsigned', () => {
  // electron-builder treats these very differently: '-' is an ad-hoc signature,
  // null skips signing altogether. An entirely unsigned arm64 bundle is refused
  // by the kernel outright rather than merely warned about, which is how a
  // downloaded copy came to report itself as damaged.
  const yml = fs.readFileSync(path.join(__dirname, '..', 'electron-builder.yml'), 'utf8');
  assert.match(yml, /^\s+identity: "-"$/m, 'mac.identity must be "-" (ad-hoc)');
  assert.doesNotMatch(yml, /^\s+identity: null$/m, 'identity: null skips signing entirely');
});

test('a macOS permission refusal is not reported as a bad USB stick', () => {
  // TCC refuses raw disk access with EPERM even to root. Folding that into the
  // generic write failure told people to go and find another stick, which is
  // the one thing that cannot help.
  const src = fs.readFileSync(path.join(__dirname, '..', 'helper', 'writer.js'), 'utf8');
  const body = /function writeErrorCode\(errors\) \{[\s\S]*?\n\}/.exec(src);
  assert.ok(body, 'writeErrorCode is missing');

  const build = (platform) => new Function('process', `${body[0]}; return writeErrorCode;`)({ platform });

  const onMac = build('darwin');
  assert.equal(onMac([new Error("EPERM: operation not permitted, open '/dev/rdisk5'")]), 'EPERM_MACOS');
  assert.equal(onMac([new Error('operation not permitted')]), 'EPERM_MACOS');
  assert.equal(onMac([new Error('EIO: i/o error')]), 'EWRITE');
  assert.equal(onMac([]), 'EWRITE');

  // The same message elsewhere means something else entirely, so it keeps the
  // generic advice.
  assert.equal(build('linux')([new Error('EPERM: operation not permitted')]), 'EWRITE');
  assert.equal(build('win32')([new Error('EPERM: operation not permitted')]), 'EWRITE');

  const renderer = fs.readFileSync(path.join(__dirname, '..', 'src', 'renderer.js'), 'utf8');
  assert.equal((renderer.match(/'err\.EPERM_MACOS':/g) || []).length, 2,
    'the explanation must exist in both languages');
});

test('the writability probe looks at every node the write will open', () => {
  // On macOS the write goes to the character device while the block device is
  // what gets unmounted, so checking only the name we were handed would let an
  // unprivileged write start and then fail halfway.
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'elevate.js'), 'utf8');
  const deviceNodes = new Function(`${/function deviceNodes[\s\S]*?\n\}/.exec(src)[0]}; return deviceNodes;`)();

  assert.deepEqual(deviceNodes('/dev/disk5'), ['/dev/rdisk5', '/dev/disk5']);
  assert.deepEqual(deviceNodes('/dev/disk12'), ['/dev/rdisk12', '/dev/disk12']);
  assert.deepEqual(deviceNodes('/dev/sdb'), ['/dev/sdb'], 'elsewhere the two names coincide');
  assert.deepEqual(deviceNodes('\\\\.\\PhysicalDrive4'), ['\\\\.\\PhysicalDrive4']);
  // Not a whole-disk name: nothing to rewrite.
  assert.deepEqual(deviceNodes('/dev/disk5s1'), ['/dev/disk5s1']);
});

test('elevation is skipped only when the device is already writable', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'elevate.js'), 'utf8');
  const build = (platform) => new Function('process', 'fs',
    `${/function deviceNodes[\s\S]*?\n\}/.exec(src)[0]}
     ${/function writableAsIs[\s\S]*?\n\}/.exec(src)[0]}
     return writableAsIs;`)({ platform }, fs);

  const posix = build('linux');
  assert.equal(posix('/dev/null'), true, 'a writable node needs no elevation');
  assert.equal(posix('/dev/nonexistent-device'), false, 'an unopenable node must elevate');

  // Windows has no equivalent check to make, and must always elevate.
  assert.equal(build('win32')('\\\\.\\PhysicalDrive4'), false);
});

test('the interface is told which way the write will go', () => {
  // Otherwise it announces a password prompt that never arrives.
  const elevate = fs.readFileSync(path.join(__dirname, '..', 'src', 'elevate.js'), 'utf8');
  assert.match(elevate, /onEvent\(\{ type: 'elevation', elevated \}\)/);

  const renderer = fs.readFileSync(path.join(__dirname, '..', 'src', 'renderer.js'), 'utf8');
  assert.match(renderer, /event\.type === 'elevation'/, 'the renderer must consume it');
  assert.equal((renderer.match(/'work\.leadDirect':/g) || []).length, 2,
    'both languages need the wording for the unelevated case');
});
