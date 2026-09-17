// The only four writes the site makes. Every one of them is a counter or a
// sketch keyed by a day: no row belongs to a visitor, so there is nothing to
// keep, expire or hand over.
//
//   site_daily      views per page, unique visitors as a sketch
//   downloads_daily hits per file, unique downloaders as a sketch
//   site_breakdown  counts per country / browser / OS / source / channel
//   site_drops      what was filtered out, by reason and network
//
// Table and column names come from the constants below, never from a request.

import { add, deserialize, empty, serialize } from "./hll.js";

export const SITE_DAILY = {
  table: "site_daily",
  keyCol: "path",
  countCol: "views",
  sketchCol: "visitors_hll",
};

export const DOWNLOADS_DAILY = {
  table: "downloads_daily",
  keyCol: "file",
  countCol: "hits",
  sketchCol: "downloaders_hll",
};

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
  const { table, keyCol, countCol, sketchCol } = spec;
  const row = await db
    .prepare(`SELECT ${sketchCol} AS sketch FROM ${table} WHERE day = ? AND ${keyCol} = ?`)
    .bind(day, key)
    .first();

  // On an empty sketch every rank is at least 1, so a new row always writes.
  const sketch = row ? deserialize(row.sketch) : empty();
  if (!add(sketch, hash)) {
    return db
      .prepare(
        `INSERT INTO ${table} (day, ${keyCol}, ${countCol}) VALUES (?, ?, 1)
         ON CONFLICT(day, ${keyCol}) DO UPDATE SET ${countCol} = ${countCol} + 1`
      )
      .bind(day, key);
  }
  return db
    .prepare(
      `INSERT INTO ${table} (day, ${keyCol}, ${countCol}, ${sketchCol}) VALUES (?, ?, 1, ?)
       ON CONFLICT(day, ${keyCol}) DO UPDATE SET ${countCol} = ${countCol} + 1, ${sketchCol} = excluded.${sketchCol}`
    )
    .bind(day, key, serialize(sketch));
}

export function breakdownStatement(db, { day, dim, value }) {
  return db
    .prepare(
      `INSERT INTO site_breakdown (day, dim, value, count) VALUES (?, ?, ?, 1)
       ON CONFLICT(day, dim, value) DO UPDATE SET count = count + 1`
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
       ON CONFLICT(day, reason, asn) DO UPDATE SET count = count + 1,
         as_org = COALESCE(site_drops.as_org, excluded.as_org)`
    )
    .bind(day, reason, asn ?? 0, asOrg ? String(asOrg).slice(0, 120) : null);
}
