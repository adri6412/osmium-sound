// The daily visitor hash, shared by the beacon and the middleware.
//
// The hash exists only inside the request that computes it: it goes straight
// into a HyperLogLog sketch and is never written to a column, returned or
// logged. The daily salt is what keeps it from being reversed or matched
// across days, and it is deleted the day after (site_salts).
//
// The same file lives in osmium-iso-tracker/src/visitor.js, so a download and
// a page view from the same person on the same day share one hash. Keep the
// two copies identical.

function hex(bytes) {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// UTC day, the same boundary the salt uses: a stored day must never span two
// salts, or the same person would be counted twice inside it.
export function utcDay(now) {
  return new Date(now).toISOString().slice(0, 10);
}

const saltCache = new Map();

export async function dailySalt(db, now) {
  const day = utcDay(now);
  const cached = saltCache.get(day);
  if (cached) return cached;
  const fresh = hex(crypto.getRandomValues(new Uint8Array(16)));
  const yesterday = utcDay(now - 24 * 60 * 60 * 1000);
  const [, row] = await db.batch([
    db.prepare("INSERT OR IGNORE INTO site_salts (day, salt) VALUES (?, ?)").bind(day, fresh),
    db.prepare("SELECT salt FROM site_salts WHERE day = ?").bind(day),
    db.prepare("DELETE FROM site_salts WHERE day < ?").bind(yesterday),
  ]);
  const salt = row.results[0].salt;
  // Yesterday's entry is dead weight, but the week's is not: drop only days.
  for (const key of [...saltCache.keys()]) if (!key.startsWith("week-")) saltCache.delete(key);
  saltCache.set(day, salt);
  return salt;
}

// The Monday of the UTC week, as a salt key: "week-2026-09-14". It sorts like
// a date, and no date string can collide with it.
export function weekStart(now) {
  const date = new Date(now);
  // getUTCDay(): 0 is Sunday, so Sunday belongs to the week that began six
  // days earlier, not to the one starting tomorrow.
  const back = (date.getUTCDay() + 6) % 7;
  return `week-${utcDay(now - back * 24 * 60 * 60 * 1000)}`;
}

// A salt that lasts a week, used only for counting appliances.
//
// An appliance asks for the update manifest every fifteen minutes, so with a
// salt that changes at midnight the same box is a new box every morning, and
// one home connection that reconnects at night is two boxes on the same day.
// A week-long salt answers the question actually being asked — how many boxes
// are out there — instead of seven noisy versions of it. Site visitors keep
// the daily salt: a person browsing and an appliance checking in are not the
// same thing, and the stored sketch is unreadable either way.
export async function weeklySalt(db, now) {
  const key = weekStart(now);
  const cached = saltCache.get(key);
  if (cached) return cached;
  const fresh = hex(crypto.getRandomValues(new Uint8Array(16)));
  const [, row] = await db.batch([
    db.prepare("INSERT OR IGNORE INTO site_salts (day, salt) VALUES (?, ?)").bind(key, fresh),
    db.prepare("SELECT salt FROM site_salts WHERE day = ?").bind(key),
    // Last week's salt is deleted the moment this week starts. Nothing reads
    // an expired one, and while it exists the hashes made with it could in
    // principle be recomputed from a guessed address — so it does not outlive
    // its week by a day.
    db.prepare("DELETE FROM site_salts WHERE day LIKE 'week-%' AND day < ?").bind(key),
  ]);
  const salt = row.results[0].salt;
  saltCache.set(key, salt);
  return salt;
}

async function hash32(salt, ip, userAgent) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${salt}|${ip}|${userAgent}`));
  return new DataView(digest).getUint32(0);
}

// 32 bits of SHA-256(salt | ip | user-agent): all a HyperLogLog register needs.
export async function visitorHash(db, now, ip, userAgent) {
  return hash32(await dailySalt(db, now), ip, userAgent);
}

export async function applianceHash(db, now, ip, userAgent) {
  return hash32(await weeklySalt(db, now), ip, userAgent);
}
