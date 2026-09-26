// Checks the site's aggregate-only analytics. Run by hand from the repository
// root, no dependencies:
//
//   node tests/test-site-analytics.mjs
//
// Four things, in order:
//   1. the HyperLogLog sketch counts, merges and survives a round trip;
//   2. the bot rules still say what they said (traffic.js is shared
//      byte-for-byte with osmium-iso-tracker and was not touched here);
//   3. no INSERT in the site's functions names a column about a person;
//   4. the migration really produces the counters it promises, against a
//      throwaway copy of the old schema;
//   5. the Ko-fi webhook keeps a public supporter's name and nothing else.

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";

import { add, count, empty, merge, serialize, deserialize } from "../website/functions/_lib/hll.js";
import { classify, parseUA } from "../website/functions/_lib/traffic.js";
import { CHECK, CLICK, DOWNLOADS_DAILY, SERVED, SITE_DAILY } from "../website/functions/_lib/counters.js";
import { utcDay, weekStart } from "../website/functions/_lib/visitor.js";
import { MAX_NAMES, cleanName } from "../website/functions/_lib/supporters.js";
import { onRequestPost as kofiWebhook } from "../website/functions/api/kofi.js";
import { onRequestGet as supportersList } from "../website/functions/api/supporters.js";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
let failures = 0;
let checks = 0;

function check(name, ok, detail = "") {
  checks++;
  if (ok) {
    console.log(`  ok   ${name}${detail ? ` — ${detail}` : ""}`);
  } else {
    failures++;
    console.log(`  FAIL ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

function section(title) {
  console.log(`\n${title}`);
}

// The same 32 bits the live code folds in: the head of a SHA-256.
function hash32(value) {
  return createHash("sha256").update(String(value)).digest().readUInt32BE(0);
}

function sketchOf(values) {
  const sketch = empty();
  for (const value of values) add(sketch, hash32(value));
  return sketch;
}

function range(n, prefix) {
  return Array.from({ length: n }, (_, i) => `${prefix}${i}`);
}

// ------------------------------------------------------------------ 1. hll

section("HyperLogLog");

check("an empty sketch counts zero", count(empty()) === 0, String(count(empty())));

for (const [n, tolerance] of [[10, 0.01], [1000, 0.02], [100000, 0.05]]) {
  const estimate = count(sketchOf(range(n, "visitor-")));
  const error = Math.abs(estimate - n) / n;
  check(
    `${n} distinct visitors within ${(tolerance * 100).toFixed(0)}%`,
    error <= tolerance,
    `counted ${estimate}, off by ${(error * 100).toFixed(2)}%`
  );
}

check(
  "the same visitor a thousand times is one visitor",
  count(sketchOf(Array(1000).fill("the-same-person"))) === 1
);

{
  const a = sketchOf(range(500, "a-"));
  const b = sketchOf(range(500, "b-"));
  const c = sketchOf(range(500, "c-"));
  const same = (x, y) => Buffer.from(x).equals(Buffer.from(y));
  check("merge is commutative", same(merge(a, b), merge(b, a)));
  check("merge is associative", same(merge(merge(a, b), c), merge(a, merge(b, c))));
  check(
    "merging three days of 500 counts 1500",
    Math.abs(count(merge(merge(a, b), c)) - 1500) / 1500 <= 0.03,
    `counted ${count(merge(merge(a, b), c))}`
  );
  const overlap = merge(a, sketchOf(range(500, "a-")));
  check("merging a day with itself changes nothing", same(overlap, a));
}

{
  const sketch = sketchOf(range(2000, "round-trip-"));
  const stored = serialize(sketch);
  check("a serialized sketch is 4096 bytes", stored.length === 4096, `${stored.length} bytes`);
  // What D1 hands back for a BLOB: a detached ArrayBuffer, not our array.
  const back = deserialize(stored.buffer.slice(stored.byteOffset, stored.byteOffset + stored.byteLength));
  check("serialize then deserialize keeps the count", count(back) === count(sketch));
  check("serialize then deserialize keeps every register", Buffer.from(back).equals(Buffer.from(sketch)));
  check("a plain array of bytes reads back too", count(deserialize([...stored])) === count(sketch));
  check("a missing column is an empty sketch", count(deserialize(null)) === 0);
  let threw = false;
  try {
    deserialize(new Uint8Array(10));
  } catch {
    threw = true;
  }
  check("a sketch of the wrong size is refused", threw);
}

// ------------------------------------------------- 2. the bot rules, unchanged

section("Traffic classification (traffic.js untouched)");

// The browser versions here are deliberately far in the future: the outdated
// browser rule derives what it expects from today's date, so a realistic
// version number would turn this table into a test that fails on its own in a
// few years. The cases that must come back with a reason are date-independent.
const CHROME = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/300.0.0.0 Safari/537.36";
const CASES = [
  [{ userAgent: "", asn: null, asOrg: null }, "ua_bot", "no user-agent at all"],
  [{ userAgent: CHROME, asn: null, asOrg: null }, null, "a browser on an unknown network"],
  [{ userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", asn: null, asOrg: "Vodafone Italia" }, null, "Safari on a phone"],
  [{ userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/300.0.0.0 Safari/537.36", asn: null, asOrg: null }, "ua_forged", "AppleWebKit without KHTML"],
  [{ userAgent: "curl/8.5.0", asn: null, asOrg: null }, "ua_bot", "curl"],
  [{ userAgent: "python-requests/2.31.0", asn: null, asOrg: null }, "ua_bot", "python-requests"],
  [{ userAgent: "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", asn: null, asOrg: null }, "ua_bot", "Googlebot"],
  [{ userAgent: "F-Droid", asn: null, asOrg: null }, "ua_bot", "the F-Droid client"],
  [{ userAgent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36", asn: null, asOrg: null }, "ua_old", "Chrome 91 in 2026"],
  [{ userAgent: "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1)", asn: null, asOrg: null }, "ua_old", "Internet Explorer"],
  [{ userAgent: CHROME, asn: 16509, asOrg: "Amazon.com, Inc." }, "datacenter", "a browser from AWS"],
  [{ userAgent: CHROME, asn: 424242, asOrg: "Hetzner Online GmbH" }, "datacenter", "a network named like a host"],
  [{ userAgent: CHROME, asn: 12874, asOrg: "Fastweb SpA" }, null, "Fastweb is not Fastly"],
  [{ userAgent: CHROME, asn: 16591, asOrg: "Google Fiber Inc." }, null, "Google Fiber is an ISP"],
  [{ userAgent: "osmiumsound/2.5.25", asn: null, asOrg: null }, null, "the appliance itself"],
];

for (const [input, expected, label] of CASES) {
  const actual = classify(input);
  check(`${label} -> ${expected === null ? "counted" : expected}`, actual === expected, actual === expected ? "" : `got ${actual}`);
}

check("parseUA still answers in Italian", parseUA("curl/8.5.0").browser === "Programma" && parseUA("").browser === "Altro");
check("the appliance keeps its own name", parseUA("osmiumsound/2.5.25").browser === "Apparecchio Osmium");

// ------------------------------------------------ 2b. the week-long salt key

section("The weekly salt key");

{
  // 2026-09-17 is a Thursday; its week began on Monday the 14th.
  const thursday = Date.UTC(2026, 8, 17, 9, 0, 0);
  check("a Thursday belongs to its Monday", weekStart(thursday) === "week-2026-09-14", weekStart(thursday));
  check("the Monday itself is its own start", weekStart(Date.UTC(2026, 8, 14, 0, 0, 1)) === "week-2026-09-14");
  check(
    "Sunday belongs to the week that has just ended, not the next one",
    weekStart(Date.UTC(2026, 8, 20, 23, 59, 0)) === "week-2026-09-14",
    weekStart(Date.UTC(2026, 8, 20, 23, 59, 0))
  );
  check("the next Monday starts a new week", weekStart(Date.UTC(2026, 8, 21, 0, 0, 1)) === "week-2026-09-21");
  check(
    "week keys sort in time order, across a year boundary too",
    weekStart(Date.UTC(2026, 11, 28)) < weekStart(Date.UTC(2027, 0, 4)),
    `${weekStart(Date.UTC(2026, 11, 28))} < ${weekStart(Date.UTC(2027, 0, 4))}`
  );
  // One salt at a time now: the cleanup keeps the current week's key and
  // deletes every other row, day-keyed leftovers included.
  check(
    "a week key never looks like a day key",
    weekStart(Date.UTC(2020, 0, 1)) !== utcDay(Date.UTC(2020, 0, 1)) &&
      weekStart(Date.UTC(2020, 0, 1)).startsWith("week-"),
    weekStart(Date.UTC(2020, 0, 1))
  );
}

// --------------------------------------- 3. no personal column in any INSERT

section("What the functions write");

const FORBIDDEN = ["ip", "user_agent", "visitor_id", "referrer", "city", "region", "screen_w", "http_proto", "email"];
const ALLOWED_TABLES = ["site_daily", "downloads_daily", "site_breakdown", "site_drops", "site_salts"];
// The one table that holds something about a person, on purpose: the names
// supporters left public on Ko-fi, which the home page shows. It may hold
// exactly these columns — no email, no message, no amount.
const PUBLISHED_TABLES = { kofi_supporters: ["message_id", "name", "ts"] };

function jsFiles(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...jsFiles(path));
    else if (entry.name.endsWith(".js")) out.push(path);
  }
  return out;
}

const inserts = [];
for (const file of jsFiles(join(ROOT, "website", "functions"))) {
  const source = readFileSync(file, "utf8");
  for (const match of source.matchAll(/INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+(?:\$\{\w+\}|\w+)\s*\(([^)]*)\)/gi)) {
    const table = match[0].match(/INTO\s+(\S+)/i)[1];
    const columns = match[1].split(",").map((c) => c.trim().replace(/^\$\{.*\}$/, "").toLowerCase());
    inserts.push({ file: file.slice(ROOT.length), table, columns });
  }
}

check("the functions do write something", inserts.length > 0, `${inserts.length} INSERT statements`);
for (const insert of inserts) {
  const bad = insert.columns.filter((c) => FORBIDDEN.includes(c));
  check(
    `${insert.file}: INSERT INTO ${insert.table} has no column about a person`,
    bad.length === 0,
    bad.length ? `found ${bad.join(", ")}` : insert.columns.filter(Boolean).join(", ")
  );
}
// Two of them name their table through a constant, so check the constants too:
// they carry the column names that the INSERT text cannot show.
const named = [...new Set(inserts.map((i) => i.table).filter((t) => !t.startsWith("${")))];
check(
  "every INSERT that names a table names an aggregate one, or the supporters list",
  named.every((t) => ALLOWED_TABLES.includes(t) || t in PUBLISHED_TABLES),
  named.join(", ")
);
for (const insert of inserts.filter((i) => i.table in PUBLISHED_TABLES)) {
  const want = PUBLISHED_TABLES[insert.table];
  check(
    `${insert.file}: ${insert.table} gets exactly ${want.join(", ")}`,
    insert.columns.length === want.length && want.every((c) => insert.columns.includes(c)),
    insert.columns.join(", ")
  );
}
for (const spec of [SITE_DAILY, DOWNLOADS_DAILY]) {
  const columns = [...spec.keyCols, spec.countCol, spec.sketchCol];
  check(
    `the ${spec.table} counter is keyed on ${columns.join(", ")}`,
    ALLOWED_TABLES.includes(spec.table) && !columns.some((c) => FORBIDDEN.includes(c))
  );
}
for (const spec of [SITE_DAILY, DOWNLOADS_DAILY]) {
  const columns = [...spec.keyCols, spec.countCol, spec.sketchCol];
}

// --------------------------------------------------- 4. the migration itself

section("Migration against a throwaway copy of the old schema");

const LEGACY_SCHEMA = `
CREATE TABLE page_views (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL, user_agent TEXT,
  path TEXT NOT NULL, country TEXT, is_bot INTEGER DEFAULT 0, is_dc INTEGER DEFAULT 0, asn INTEGER,
  as_org TEXT, request_count INTEGER DEFAULT 1, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL);
CREATE TABLE site_visits (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT NOT NULL, user_agent TEXT,
  country TEXT, is_bot INTEGER DEFAULT 0, is_dc INTEGER DEFAULT 0, asn INTEGER, as_org TEXT,
  browser_confirmed INTEGER DEFAULT 0, page_count INTEGER DEFAULT 1, first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL);
CREATE TABLE site_sessions (id TEXT PRIMARY KEY, visitor_id TEXT NOT NULL, started INTEGER NOT NULL,
  last_seen INTEGER NOT NULL, pageviews INTEGER NOT NULL DEFAULT 0, goals INTEGER NOT NULL DEFAULT 0,
  engaged_ms INTEGER NOT NULL DEFAULT 0, max_scroll INTEGER NOT NULL DEFAULT 0,
  interacted INTEGER NOT NULL DEFAULT 0, entry_path TEXT, exit_path TEXT, referrer TEXT, source TEXT,
  channel TEXT, utm_medium TEXT, utm_campaign TEXT, country TEXT, region TEXT, city TEXT, browser TEXT,
  os TEXT, device TEXT, screen_w INTEGER, lang TEXT, asn INTEGER, as_org TEXT, http_proto TEXT, reason TEXT);
CREATE TABLE site_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, name TEXT NOT NULL,
  session_id TEXT NOT NULL, visitor_id TEXT NOT NULL, page_id TEXT, path TEXT, target TEXT,
  engaged_ms INTEGER NOT NULL DEFAULT 0, scroll INTEGER NOT NULL DEFAULT 0, interacted INTEGER NOT NULL DEFAULT 0);
`;

const DAY_BEACON = Date.UTC(2026, 8, 10, 12, 0, 0); // 2026-09-10, the beacon era
const DAY_LOG = Date.UTC(2026, 8, 1, 12, 0, 0); // 2026-09-01, before it

const db = new DatabaseSync(":memory:");
db.exec(LEGACY_SCHEMA);

const visitorA = createHash("sha256").update("A").digest("hex").slice(0, 32);
const visitorB = createHash("sha256").update("B").digest("hex").slice(0, 32);

const session = db.prepare(
  `INSERT INTO site_sessions (id, visitor_id, started, last_seen, pageviews, country, browser, os, source, channel, asn, as_org, reason)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
);
session.run("s1", visitorA, DAY_BEACON, DAY_BEACON, 2, "IT", "Firefox", "Linux", "Google", "Ricerca", 3269, "Telecom Italia", null);
session.run("s2", visitorB, DAY_BEACON, DAY_BEACON, 1, "DE", "Chrome", "Windows", null, "Diretto", 3320, "Deutsche Telekom", null);
session.run("s3", "cafe0000cafe0000cafe0000cafe0000", DAY_BEACON, DAY_BEACON, 1, "US", "Chrome", "Linux", null, "Diretto", 16509, "Amazon.com, Inc.", "datacenter");

const event = db.prepare(
  `INSERT INTO site_events (ts, name, session_id, visitor_id, path, target) VALUES (?, ?, ?, ?, ?, ?)`
);
event.run(DAY_BEACON, "pageview", "s1", visitorA, "/", null);
event.run(DAY_BEACON + 1000, "pageview", "s1", visitorA, "/manual", null);
event.run(DAY_BEACON + 2000, "pageview", "s2", visitorB, "/", null);
event.run(DAY_BEACON + 3000, "download", "s1", visitorA, "/", "file.osmiumsound.it/osmium.iso");
event.run(DAY_BEACON + 4000, "pageview", "s3", "cafe0000cafe0000cafe0000cafe0000", "/", null);

const view = db.prepare(
  `INSERT INTO page_views (ip, user_agent, path, country, is_bot, is_dc, asn, as_org, first_seen, last_seen)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
);
view.run("203.0.113.7", "Firefox", "/index.html", "IT", 0, 0, 3269, "Telecom Italia", DAY_LOG, DAY_LOG);
view.run("203.0.113.8", "Firefox", "/manual.html", "IT", 0, 0, 3269, "Telecom Italia", DAY_LOG, DAY_LOG);
view.run("198.51.100.1", "curl/8", "/", "US", 1, 0, 0, null, DAY_LOG, DAY_LOG);
view.run("198.51.100.2", "Chrome", "/", "US", 0, 1, 16509, "Amazon.com, Inc.", DAY_LOG, DAY_LOG);
view.run("203.0.113.9", "F-Droid", "/fdroid/repo/app.apk", "IT", 1, 0, 3269, "Telecom Italia", DAY_LOG, DAY_LOG);

const analytics = join(ROOT, "website", "analytics");
db.exec(readFileSync(join(analytics, "01_aggregates.sql"), "utf8"));

const rows = (sql) => db.prepare(sql).all();
const one = (sql) => db.prepare(sql).get();

check(
  "the beacon day keeps its page views",
  one("SELECT SUM(views) AS n FROM site_daily WHERE day = '2026-09-10'").n === 3,
  `got ${one("SELECT SUM(views) AS n FROM site_daily WHERE day = '2026-09-10'").n}, expected 3 (the datacenter visit is not one)`
);
check(
  "the log day keeps its page views, with normalised paths",
  JSON.stringify(rows("SELECT path, views FROM site_daily WHERE day = '2026-09-01' ORDER BY path")) ===
    JSON.stringify([{ path: "/", views: 1 }, { path: "/manual", views: 1 }]),
  JSON.stringify(rows("SELECT path, views FROM site_daily WHERE day = '2026-09-01' ORDER BY path"))
);
check(
  "the two eras never count the same day twice",
  one("SELECT COUNT(*) AS n FROM site_daily WHERE day = '2026-09-10' AND path = '/'").n === 1
);
check(
  "downloads come from both eras, each with its own kind",
  JSON.stringify(rows("SELECT file, kind, hits FROM downloads_daily ORDER BY day")) ===
    JSON.stringify([
      { file: "osmiumsound.it/fdroid/repo/app.apk", kind: "served", hits: 1 },
      { file: "file.osmiumsound.it/osmium.iso", kind: "click", hits: 1 },
    ]),
  JSON.stringify(rows("SELECT day, file, kind, hits FROM downloads_daily ORDER BY day"))
);

// A click and the file it starts are the same name on the same day: they must
// stay two rows, or every download would be counted twice.
db.prepare(
  `INSERT INTO downloads_daily (day, file, kind, hits) VALUES ('2026-09-10', 'file.osmiumsound.it/osmium.iso', 'served', 1)
   ON CONFLICT(day, file, kind) DO UPDATE SET hits = downloads_daily.hits + 1`
).run();
check(
  "a click and the file going out are two rows, not one",
  JSON.stringify(rows("SELECT kind, hits FROM downloads_daily WHERE file = 'file.osmiumsound.it/osmium.iso' ORDER BY kind")) ===
    JSON.stringify([{ kind: "click", hits: 1 }, { kind: "served", hits: 1 }]),
  JSON.stringify(rows("SELECT kind, hits FROM downloads_daily WHERE file = 'file.osmiumsound.it/osmium.iso'"))
);

// A third kind on the same file: an appliance checking for updates. It must
// not land in either of the download numbers. At this point the table holds
// one served row from the F-Droid backfill plus the ISO one just inserted.
db.prepare(
  `INSERT INTO downloads_daily (day, file, kind, hits) VALUES ('2026-09-10', 'osmiumsound.it/ota/latest-prod.json', 'check', 96)`
).run();
check(
  "an update check is neither a download nor a click",
  one("SELECT COALESCE(SUM(hits),0) AS n FROM downloads_daily WHERE kind = 'served'").n === 2 &&
    one("SELECT COALESCE(SUM(hits),0) AS n FROM downloads_daily WHERE kind = 'click'").n === 1 &&
    one("SELECT COALESCE(SUM(hits),0) AS n FROM downloads_daily WHERE kind = 'check'").n === 96,
  JSON.stringify(rows("SELECT kind, SUM(hits) AS hits FROM downloads_daily GROUP BY kind ORDER BY kind"))
);
check("the three kinds are the constants the code uses", [SERVED, CLICK, CHECK].join(",") === "served,click,check");
check(
  "breakdowns are counted per page view",
  one("SELECT count FROM site_breakdown WHERE day = '2026-09-10' AND dim = 'country' AND value = 'IT'").count === 2
);
check(
  "what was filtered out is kept per reason and network",
  JSON.stringify(rows("SELECT reason, asn, count FROM site_drops ORDER BY day, reason")) ===
    JSON.stringify([
      { reason: "datacenter", asn: 16509, count: 1 },
      { reason: "ua_bot", asn: 0, count: 1 },
      { reason: "datacenter", asn: 16509, count: 1 },
    ]),
  JSON.stringify(rows("SELECT day, reason, asn, as_org, count FROM site_drops ORDER BY day, reason"))
);
check(
  "the F-Droid file is a download, not a drop",
  one("SELECT COUNT(*) AS n FROM site_drops WHERE reason = 'ua_bot' AND asn = 3269").n === 0
);
check("no sketch exists yet", one("SELECT COUNT(*) AS n FROM site_daily WHERE visitors_hll IS NOT NULL").n === 0);

// Step 2: export the rows the way wrangler --json would, run the script, apply
// the SQL it writes.
const work = mkdtempSync(join(tmpdir(), "osmium-analytics-"));
const exported = rows(
  `SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, e.path AS key, e.visitor_id AS visitor
   FROM site_events e JOIN site_sessions s ON s.id = e.session_id
   WHERE e.name = 'pageview' AND s.reason IS NULL AND e.path IS NOT NULL
   GROUP BY 1, 2, 3`
);
const exportFile = join(work, "pages.json");
writeFileSync(exportFile, JSON.stringify([{ results: exported, success: true }]));
const generated = execFileSync(
  process.execPath,
  [join(analytics, "02_backfill_sketches.mjs"), "--table", "site_daily", exportFile],
  { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
);
db.exec(generated);

const sketchRows = rows("SELECT path, views, visitors_hll FROM site_daily WHERE day = '2026-09-10' ORDER BY path");
check("every counted day gets a sketch", sketchRows.every((r) => r.visitors_hll), `${sketchRows.length} rows`);
check(
  "the home page had two unique visitors that day",
  count(sketchRows.find((r) => r.path === "/").visitors_hll) === 2,
  `counted ${count(sketchRows.find((r) => r.path === "/").visitors_hll)}`
);
check(
  "the day's total row holds the union of its paths",
  count(sketchRows.find((r) => r.path === "*").visitors_hll) ===
    count(sketchRows.filter((r) => r.path !== "*").map((r) => deserialize(r.visitors_hll)).reduce((a, b) => merge(a, b))),
  `total row counts ${count(sketchRows.find((r) => r.path === "*").visitors_hll)}`
);
check(
  "the total row does not add to the page views",
  sketchRows.find((r) => r.path === "*").views === 0 &&
    one("SELECT SUM(views) AS n FROM site_daily WHERE day = '2026-09-10'").n === 3
);

// Step 3
db.exec(readFileSync(join(analytics, "03_drop_legacy.sql"), "utf8"));
const left = rows("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").map((r) => r.name);
check(
  "the tables holding addresses are gone",
  !left.some((name) => ["page_views", "site_visits", "site_sessions", "site_events"].includes(name)),
  left.join(", ")
);
check(
  "the aggregate tables are still there",
  ["site_daily", "downloads_daily", "site_breakdown", "site_drops"].every((name) => left.includes(name)),
  left.join(", ")
);

// ------------------------------------------------ 5. the Ko-fi supporters list

section("Ko-fi supporters");

// D1 as far as the two functions use it, over node:sqlite.
function fakeD1(sqlite) {
  const statement = (sql, args = []) => ({
    bind: (...values) => statement(sql, values),
    run: async () => sqlite.prepare(sql).run(...args),
    all: async () => ({ results: sqlite.prepare(sql).all(...args) }),
  });
  return {
    prepare: (sql) => statement(sql),
    batch: async (list) => {
      sqlite.exec("BEGIN");
      try {
        for (const s of list) await s.run();
        sqlite.exec("COMMIT");
      } catch (err) {
        sqlite.exec("ROLLBACK");
        throw err;
      }
    },
  };
}

const TOKEN = "test-token";
let donation = 0;
function payload(overrides = {}) {
  donation++;
  return {
    verification_token: TOKEN,
    message_id: `msg-${donation}`,
    timestamp: new Date(Date.UTC(2026, 8, 1, 0, donation)).toISOString(),
    type: "Donation",
    is_public: true,
    from_name: `Supporter ${donation}`,
    message: "A secret message",
    amount: "3.00",
    email: "someone@example.com",
    currency: "EUR",
    kofi_transaction_id: `tx-${donation}`,
    ...overrides,
  };
}
async function post(env, data, raw) {
  const body = raw ?? new URLSearchParams({ data: JSON.stringify(data) }).toString();
  const response = await kofiWebhook({
    request: new Request("https://osmiumsound.it/api/kofi", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body,
    }),
    env,
  });
  return response.status;
}
async function listed(env) {
  return (await (await supportersList({ env })).json()).names;
}

const kofiDb = new DatabaseSync(":memory:");
const kofiEnv = { DB: fakeD1(kofiDb), KOFI_VERIFICATION_TOKEN: TOKEN };

check("no table yet: the list is empty, not an error", (await listed(kofiEnv)).length === 0);
check("no token configured: refused", (await post({ DB: kofiEnv.DB }, payload())) === 503);
check("wrong token: refused", (await post(kofiEnv, payload({ verification_token: "nope" }))) === 403);
check("not form data: refused", (await post(kofiEnv, null, "garbage")) === 400);

const first = payload({ from_name: "  Ada‮   Lovelace\n" });
check("a public donation is accepted", (await post(kofiEnv, first)) === 200);
check("the second delivery of it is a no-op", (await post(kofiEnv, first)) === 200);
const stored = kofiDb.prepare("SELECT * FROM kofi_supporters").all();
check("one row for one donation", stored.length === 1, `${stored.length}`);
check("the name is cleaned up", stored[0]?.name === "Ada Lovelace", JSON.stringify(stored[0]?.name));
check(
  "only the id, the name and the time are stored",
  Object.keys(stored[0] ?? {}).sort().join() === "message_id,name,ts",
  Object.keys(stored[0] ?? {}).join(", ")
);
check(
  "email, message and amount are nowhere in the table",
  !JSON.stringify(stored).match(/example\.com|secret|3\.00/)
);

await post(kofiEnv, payload({ from_name: "Private", is_public: false }));
await post(kofiEnv, payload({ from_name: "Shopper", type: "Shop Order" }));
await post(kofiEnv, payload({ from_name: "Jo Example", kofi_transaction_id: "00000000-1111-2222-3333-444444444444" }));
await post(kofiEnv, payload({ from_name: "   " }));
check(
  "private donations, shop orders, Ko-fi's test and empty names are not kept",
  kofiDb.prepare("SELECT COUNT(*) AS n FROM kofi_supporters").get().n === 1
);

await post(kofiEnv, payload({ from_name: "Monthly" }));
await post(kofiEnv, payload({ from_name: "Grace", type: "Subscription" }));
await post(kofiEnv, payload({ from_name: "Monthly", type: "Subscription" }));
const names = await listed(kofiEnv);
check(
  "the list is newest first, each name once",
  names.join() === "Monthly,Grace,Ada Lovelace",
  names.join(", ")
);

for (let i = 0; i < MAX_NAMES + 5; i++) await post(kofiEnv, payload());
const kept = kofiDb.prepare("SELECT COUNT(DISTINCT name) AS n FROM kofi_supporters").get().n;
check(`only the latest ${MAX_NAMES} names are kept`, kept === MAX_NAMES, `${kept}`);
check("the oldest name went first", !(await listed(kofiEnv)).includes("Ada Lovelace"));
check("a long name is cut", [...cleanName("x".repeat(100))].length === 40);
check("emoji survive", cleanName("Luca 🎧") === "Luca 🎧");

console.log(`\n${checks - failures}/${checks} checks passed`);
process.exit(failures === 0 ? 0 : 1);
