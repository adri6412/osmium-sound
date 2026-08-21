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
