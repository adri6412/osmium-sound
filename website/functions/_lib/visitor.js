// The daily visitor hash, shared by the beacon and the middleware.
//
// The hash exists only inside the request that computes it: it goes straight
// into a HyperLogLog sketch and is never written to a column, returned or
// logged. The daily salt is what keeps it from being reversed or matched
// across days, and it is deleted the day after (site_salts).

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
  saltCache.clear();
  saltCache.set(day, salt);
  return salt;
}

// 32 bits of SHA-256(salt | ip | user-agent): all a HyperLogLog register needs.
export async function visitorHash(db, now, ip, userAgent) {
  const salt = await dailySalt(db, now);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${salt}|${ip}|${userAgent}`));
  return new DataView(digest).getUint32(0);
}
