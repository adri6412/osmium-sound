// The only four writes the site makes. Every one of them is a counter or a
// sketch keyed by a day: no row belongs to a visitor, so there is nothing to
// keep, expire or hand over.
//
//   site_daily      views per page, unique visitors as a sketch
//   downloads_daily hits per file, unique downloaders as a sketch
//   site_breakdown  counts per country / browser / OS / source / channel
//   site_drops      what was filtered out, by reason and network
//
// The same file lives in osmium-iso-tracker/src/counters.js, which writes
// downloads_daily and site_drops for the files served from
// file.osmiumsound.it. Keep the two copies identical.
//
// Table and column names come from the constants below, never from a request.

import { add, deserialize, empty, serialize } from "./hll.js";

export const SITE_DAILY = {
  table: "site_daily",
  keyCols: ["path"],
  countCol: "views",
  sketchCol: "visitors_hll",
};

// kind tells the two halves of a download apart: SERVED is a file that
// actually went out, CLICK is a download button somebody pressed on the site.
// Keeping them in one table with a different kind is what stops a click and
// the download it starts from being counted as two downloads of the same file.
export const DOWNLOADS_DAILY = {
  table: "downloads_daily",
  keyCols: ["file", "kind"],
  countCol: "hits",
  sketchCol: "downloaders_hll",
};

export const SERVED = "served";
export const CLICK = "click";
// An appliance asking whether there is a new version. It is a fetch of a file
// like any other, so it lives in the same table under its own kind; its sketch
// is salted by the week, not by the day (see _lib/visitor.js).
export const CHECK = "check";

// The row of a day whose key is "*" holds that day's sketch merged across
// every key, so "how many different people came that day" is one 4 KB read
// instead of one per page. Its counter stays at zero on purpose: a SUM over
// the table is still the right total, with or without this row. Paths always
// start with "/" and file keys with a host name, so "*" cannot collide.
export const TOTAL_KEY = "*";

// Bumps the counter and folds the visitor into the sketch. One read, and a
// write the caller batches with the rest.
//
// The sketch is only rewritten when this visitor raises a register, so the
// second page of a visit, and every later visit that day, costs a counter bump
// and nothing else. Two requests that both raise a register in the same
// millisecond can lose one of the two updates: the cost is one visitor missing
// from a day, which is well inside the sketch's own error, and it is the reason
// this stays a counter and never becomes a list of who was here.
export async function dailyStatement(db, spec, { day, key, hash }) {
  const { table, keyCols, countCol, sketchCol } = spec;
  const keys = Array.isArray(key) ? key : [key];
  const match = keyCols.map((col) => `${col} = ?`).join(" AND ");
  const row = await db
    .prepare(`SELECT ${sketchCol} AS sketch FROM ${table} WHERE day = ? AND ${match}`)
    .bind(day, ...keys)
    .first();

  const columns = ["day", ...keyCols];
  const placeholders = columns.map(() => "?").join(", ");
  const conflict = columns.join(", ");

  // On an empty sketch every rank is at least 1, so a new row always writes.
  const sketch = row ? deserialize(row.sketch) : empty();
  if (!add(sketch, hash)) {
    return db
      .prepare(
        `INSERT INTO ${table} (${conflict}, ${countCol}) VALUES (${placeholders}, 1)
         ON CONFLICT(${conflict}) DO UPDATE SET ${countCol} = ${table}.${countCol} + 1`
      )
      .bind(day, ...keys);
  }
  return db
    .prepare(
      `INSERT INTO ${table} (${conflict}, ${countCol}, ${sketchCol}) VALUES (${placeholders}, 1, ?)
       ON CONFLICT(${conflict}) DO UPDATE SET ${countCol} = ${table}.${countCol} + 1,
         ${sketchCol} = excluded.${sketchCol}`
    )
    .bind(day, ...keys, serialize(sketch));
}

// The keyed row and the day's total row, ready to batch. The total is written
// only when this visitor is new to the day, so a second page view costs one
// counter bump and nothing more.
export async function dailyStatements(db, spec, { day, key, hash }) {
  const keys = Array.isArray(key) ? key : [key];
  const totalKeys = [TOTAL_KEY, ...keys.slice(1)];
  const statements = [await dailyStatement(db, spec, { day, key: keys, hash })];
  const total = await sketchStatement(db, spec, { day, key: totalKeys, hash });
  if (total) statements.push(total);
  return statements;
}

// Folds the visitor into a sketch without touching the counter. Returns null
// when the sketch already knew this visitor: then there is nothing to write.
async function sketchStatement(db, spec, { day, key, hash }) {
  const { table, keyCols, countCol, sketchCol } = spec;
  const match = keyCols.map((col) => `${col} = ?`).join(" AND ");
  const row = await db
    .prepare(`SELECT ${sketchCol} AS sketch FROM ${table} WHERE day = ? AND ${match}`)
    .bind(day, ...key)
    .first();

  const sketch = row ? deserialize(row.sketch) : empty();
  if (!add(sketch, hash)) return null;

  const columns = ["day", ...keyCols];
  const placeholders = columns.map(() => "?").join(", ");
  const conflict = columns.join(", ");
  return db
    .prepare(
      `INSERT INTO ${table} (${conflict}, ${countCol}, ${sketchCol}) VALUES (${placeholders}, 0, ?)
       ON CONFLICT(${conflict}) DO UPDATE SET ${sketchCol} = excluded.${sketchCol}`
    )
    .bind(day, ...key, serialize(sketch));
}

// ---------------------------------------------------------------- live
//
// How many appliances are on right now. The daily counters have no clock in
// them, so "now" needs its own place: one sketch per quarter of an hour, and
// the old ones are deleted within the hour. An appliance asks for the manifest
// every fifteen minutes, so merging the last two slots catches every box that
// is on, and a box switched off drops out of the number inside half an hour.
//
// Nothing here outlives the hour, and it is the same unreadable sketch as
// everywhere else: it says how many, never which.
export const LIVE_SLOT_MS = 15 * 60 * 1000;
const LIVE_KEEP_SLOTS = 4;

export function liveSlot(now) {
  return new Date(Math.floor(now / LIVE_SLOT_MS) * LIVE_SLOT_MS).toISOString().slice(0, 16);
}

export async function liveStatements(db, { now, hash }) {
  const slot = liveSlot(now);
  const row = await db
    .prepare("SELECT boxes_hll AS sketch FROM appliances_live WHERE slot = ?")
    .bind(slot)
    .first();

  const statements = [
    db.prepare("DELETE FROM appliances_live WHERE slot < ?").bind(liveSlot(now - LIVE_KEEP_SLOTS * LIVE_SLOT_MS)),
  ];
  const sketch = row ? deserialize(row.sketch) : empty();
  // Already in this quarter of an hour: nothing to write but the cleanup.
  if (!add(sketch, hash)) return statements;
  statements.push(
    db
      .prepare(
        `INSERT INTO appliances_live (slot, boxes_hll) VALUES (?, ?)
         ON CONFLICT(slot) DO UPDATE SET boxes_hll = excluded.boxes_hll`
      )
      .bind(slot, serialize(sketch))
  );
  return statements;
}

export function breakdownStatement(db, { day, dim, value }) {
  return db
    .prepare(
      `INSERT INTO site_breakdown (day, dim, value, count) VALUES (?, ?, ?, 1)
       ON CONFLICT(day, dim, value) DO UPDATE SET count = site_breakdown.count + 1`
    )
    .bind(day, dim, String(value).slice(0, 120));
}

// An ASN is an organisation, not a person: keeping the count of what was
// filtered out, per network, is how a whole ISP excluded by mistake becomes
// visible without keeping any of the requests. asn 0 means the network was
// unknown, because a primary key column cannot hold NULL and deduplicate.
export function dropStatement(db, { day, reason, asn, asOrg }) {
  return db
    .prepare(
      `INSERT INTO site_drops (day, reason, asn, as_org, count) VALUES (?, ?, ?, ?, 1)
       ON CONFLICT(day, reason, asn) DO UPDATE SET count = site_drops.count + 1,
         as_org = COALESCE(site_drops.as_org, excluded.as_org)`
    )
    .bind(day, reason, asn ?? 0, asOrg ? String(asOrg).slice(0, 120) : null);
}

// Networks that were NOT filtered out, so the dashboard can still show where
// downloads come from. An organisation, never a person; the value carries the
// number and the name because site_breakdown holds one string per row.
export function networkValue(asn, asOrg) {
  return `${asn ?? 0}|${(asOrg || "").slice(0, 100)}`;
}
