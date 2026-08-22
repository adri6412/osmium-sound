'use strict';

/**
 * etcher-sdk depends on file-type ^16 — whose ASF parser can spin forever on
 * a malformed file (GHSA-5v7r-6r5c-r473) — and uses it the way 16 was used:
 * `const ft = require('file-type'); await ft.fromStream(stream)`.
 *
 * Every fixed release of file-type is ESM-only and renamed its exports, so
 * package.json's `overrides` point "file-type" here instead: the names
 * etcher-sdk calls, backed by the current release (a direct dependency of the flasher, so npm dedupes etcher-sdk onto it, which
 * carries file-type 21 under the alias
 * file-type-upstream so the override cannot loop back onto itself). Loaded
 * lazily, so the ESM graph is only pulled in when a type is actually sniffed.
 */

let upstream = null;
const load = () => (upstream ||= import('file-type-upstream'));

async function fromStream(stream) {
  return (await load()).fileTypeFromStream(stream);
}

async function fromBuffer(buffer) {
  return (await load()).fileTypeFromBuffer(buffer);
}

async function fromFile(path) {
  return (await load()).fileTypeFromFile(path);
}

async function fromTokenizer(tokenizer) {
  return (await load()).fileTypeFromTokenizer(tokenizer);
}

module.exports = { fromStream, fromBuffer, fromFile, fromTokenizer };
