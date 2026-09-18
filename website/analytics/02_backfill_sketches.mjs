// Step 2 of 3 — builds the unique-visitor sketches for the days the beacon
// already counted, and emits them as UPDATE statements.
//
// It works because site_events.visitor_id is already a hash of that day's salt
// plus the address and the user-agent: distinct hashes within a day are
// distinct visitors within that day, which is exactly what the sketch holds.
// It is the same number the live code would have written, not an estimate made
// up after the fact. Nothing before the beacon can be reconstructed this way,
// and it is not attempted: those days keep their page counts and have no
// unique-visitor sketch.
//
// Run it twice and nothing breaks: an UPDATE writes the whole sketch.
//
//   PAGES="SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, e.path AS key, e.visitor_id AS visitor
//          FROM site_events e JOIN site_sessions s ON s.id = e.session_id
//          WHERE e.name = 'pageview' AND s.reason IS NULL AND e.path IS NOT NULL
//          GROUP BY 1, 2, 3"
//   npx wrangler d1 execute osmium-downloads --remote --json --command "$PAGES" > /tmp/pages.json
//   node website/analytics/02_backfill_sketches.mjs --table site_daily /tmp/pages.json > /tmp/pages.sql
//   npx wrangler d1 execute osmium-downloads --remote --file=/tmp/pages.sql
//
//   FILES="SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, e.target AS key, e.visitor_id AS visitor
//          FROM site_events e JOIN site_sessions s ON s.id = e.session_id
//          WHERE e.name = 'download' AND s.reason IS NULL AND e.target IS NOT NULL
//          GROUP BY 1, 2, 3"
//   npx wrangler d1 execute osmium-downloads --remote --json --command "$FILES" > /tmp/files.json
//   node website/analytics/02_backfill_sketches.mjs --table downloads_daily /tmp/files.json > /tmp/files.sql
//   npx wrangler d1 execute osmium-downloads --remote --file=/tmp/files.sql
//
// A big export can go over wrangler's command size; if it does, split the
// query by month with an extra WHERE and run the three steps per month.

import { readFileSync } from "node:fs";
import { add, empty, serialize } from "../functions/_lib/hll.js";

const TABLES = {
  site_daily: {
    keyCol: "path",
    sketchCol: "visitors_hll",
    countCol: "views",
    extra: "",
    columns: "path",
    totalKey: "'*'",
  },
  // Only the click half of downloads_daily comes from the beacon; the files
  // served by the worker never had a visitor hash to rebuild from.
  downloads_daily: {
    keyCol: "file",
    sketchCol: "downloaders_hll",
    countCol: "hits",
    extra: " AND kind = 'click'",
    columns: "file, kind",
    totalKey: "'*', 'click'",
  },
};

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

// wrangler --json prints [{ results: [...] }]; a hand-made file may be either
// that, a single object, or a bare array of rows.
function rowsOf(parsed) {
  if (Array.isArray(parsed) && parsed.length && parsed[0]?.results) {
    return parsed.flatMap((entry) => entry.results || []);
  }
  if (parsed?.results) return parsed.results;
  if (Array.isArray(parsed)) return parsed;
  fail("no rows found in the input: expected wrangler --json output");
}

function hexBlob(bytes) {
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const args = process.argv.slice(2);
const tableIndex = args.indexOf("--table");
if (tableIndex === -1 || !args[tableIndex + 1]) fail("usage: 02_backfill_sketches.mjs --table <site_daily|downloads_daily> <rows.json>");
const table = args[tableIndex + 1];
const spec = TABLES[table];
if (!spec) fail(`unknown table ${table}`);
const input = args.filter((a, i) => i !== tableIndex && i !== tableIndex + 1)[0];
if (!input) fail("missing the JSON file with the exported rows");

const rows = rowsOf(JSON.parse(readFileSync(input, "utf8")));
const sketches = new Map();
const totals = new Map(); // one sketch per day, merged across keys: the "*" row
let skipped = 0;

for (const row of rows) {
  const day = row.day;
  const key = row.key;
  const visitor = row.visitor;
  if (!day || key === null || key === undefined || typeof visitor !== "string" || visitor.length < 8) {
    skipped++;
    continue;
  }
  const id = JSON.stringify([day, key]);
  let sketch = sketches.get(id);
  if (!sketch) {
    sketch = empty();
    sketches.set(id, sketch);
  }
  // The first four bytes of the visitor hash, the same ones the live code
  // folds in. parseInt of eight hex digits is always a 32-bit value.
  const hash = parseInt(visitor.slice(0, 8), 16);
  add(sketch, hash);

  let total = totals.get(day);
  if (!total) {
    total = empty();
    totals.set(day, total);
  }
  add(total, hash);
}

const out = [
  `-- ${sketches.size} sketches for ${table}, built from ${rows.length - skipped} distinct visitor-days`,
  `-- plus ${totals.size} day totals, the "*" rows the dashboard reads`,
];
for (const [id, sketch] of sketches) {
  const [day, key] = JSON.parse(id);
  const quoted = key.replace(/'/g, "''");
  out.push(
    `UPDATE ${table} SET ${spec.sketchCol} = X'${hexBlob(serialize(sketch))}' ` +
      `WHERE day = '${day}' AND ${spec.keyCol} = '${quoted}'${spec.extra};`
  );
}
// The "*" rows do not exist yet: step 1 only wrote the keys that had counts.
for (const [day, sketch] of totals) {
  out.push(
    `INSERT INTO ${table} (day, ${spec.columns}, ${spec.countCol}, ${spec.sketchCol}) ` +
      `VALUES ('${day}', ${spec.totalKey}, 0, X'${hexBlob(serialize(sketch))}') ` +
      `ON CONFLICT(day, ${spec.columns}) DO UPDATE SET ${spec.sketchCol} = excluded.${spec.sketchCol};`
  );
}
process.stdout.write(`${out.join("\n")}\n`);
process.stderr.write(`${sketches.size} sketches and ${totals.size} day totals, ${skipped} rows skipped\n`);
