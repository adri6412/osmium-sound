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

// The Monday of the UTC week, as a salt key: "week-2026-09-14". It sorts like
// a date, and no date string can collide with it.
export function weekStart(now) {
  const date = new Date(now);
  // getUTCDay(): 0 is Sunday, so Sunday belongs to the week that began six
  // days earlier, not to the one starting tomorrow.
  const back = (date.getUTCDay() + 6) % 7;
  return `week-${utcDay(now - back * 24 * 60 * 60 * 1000)}`;
}

const saltCache = new Map();

// One salt, and it lasts a week.
//
// It used to turn over at midnight, which made every count a count of
// visitor-days: the same person tomorrow is a different code, so "how many
// different people this month" could only ever be answered with the sum of
// its days. A week-long salt answers it once, for a week.
//
// The cost is stated plainly rather than hidden: two requests from the same
// address can be recognised as the same for seven days instead of one. What
// is stored does not change — a sketch that cannot be read back, and nothing
// else — and the salt is deleted the moment its week is over, which is what
// makes everything made with it unlinkable from then on.
export async function weeklySalt(db, now) {
  const key = weekStart(now);
  const cached = saltCache.get(key);
  if (cached) return cached;
  const fresh = hex(crypto.getRandomValues(new Uint8Array(16)));
  const [, row] = await db.batch([
    db.prepare("INSERT OR IGNORE INTO site_salts (day, salt) VALUES (?, ?)").bind(key, fresh),
    db.prepare("SELECT salt FROM site_salts WHERE day = ?").bind(key),
    // Only this week's salt is ever needed, so nothing else is kept: last
    // week's goes the moment this one starts, and so do the day-keyed rows
    // left over from when the salt turned over at midnight. While a salt
    // exists the hashes made with it could in principle be recomputed from a
    // guessed address, which is the whole reason they are thrown away.
    db.prepare("DELETE FROM site_salts WHERE day <> ?").bind(key),
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
  return hash32(await weeklySalt(db, now), ip, userAgent);
}

// Same hash, different name at the call site: an appliance checking in is not
// a person browsing, and the code should not pretend they are the same thing
// just because the arithmetic is.
export const applianceHash = visitorHash;
