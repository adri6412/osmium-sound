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
