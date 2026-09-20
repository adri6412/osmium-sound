// Cloudflare Pages Function — /kofi?from=<place>
//
// Every "support us on Ko-fi" link on the site, in the README and in the
// appliance's web admin goes through here, so that opening it can be counted
// before it is sent on to Ko-fi. The count answers one question the site
// could not answer before: does anybody ever reach the donation page, and
// from where — the download popup, the reviews section, the footer, the
// appliance itself. Ko-fi's own dashboard says what happens after that.
//
// The redirect always happens, whatever the counting does: a missing D1
// binding or a failed write must never leave somebody on an error page.
//
// Counted the way an appliance check is counted (_middleware.js): one row per
// day and place in downloads_daily, kind "kofi", with a HyperLogLog sketch of
// the day's visitor hashes so "how many different people" can be read back.
// The address and the user-agent are used for the hash and to tell a person
// from a scanner, then dropped with the request. Scanners and hosting
// networks are sent on without being counted.

import { classify } from "./_lib/traffic.js";
import { DOWNLOADS_DAILY, dailyStatements } from "./_lib/counters.js";
import { utcDay, visitorHash } from "./_lib/visitor.js";

const KOFI_URL = "https://ko-fi.com/osmiumsound";

// The kind that tells these rows apart from files served (served), download
// buttons pressed (click) and appliances checking in (check). Defined here
// and in the stats worker rather than in _lib/counters.js, which stays
// byte-identical between the two repositories.
const KOFI = "kofi";

// Where the link was opened. Anything else is "other": the value ends up as
// a row name in the dashboard, so it is never taken from the request as is.
const PLACES = new Set(["popup", "reviews", "footer", "admin", "github"]);

function getIP(request) {
  return (
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "0.0.0.0"
  );
}

function isExcluded(ip, env) {
  if (!env.EXCLUDE_IPS) return false;
  return env.EXCLUDE_IPS.split(",").some((entry) => entry.trim() === ip);
}

async function countClick(db, { day, place, now, ip, userAgent }) {
  const hash = await visitorHash(db, now, ip, userAgent);
  await db.batch(await dailyStatements(db, DOWNLOADS_DAILY, { day, key: [place, KOFI], hash }));
}

export async function onRequestGet(context) {
  const { request, env, waitUntil } = context;
  const redirect = new Response(null, {
    status: 302,
    headers: { location: KOFI_URL, "cache-control": "no-store" },
  });

  try {
    if (!env.DB) return redirect;
    const ip = getIP(request);
    if (isExcluded(ip, env)) return redirect;

    const userAgent = request.headers.get("user-agent") || "";
    const asn = request.cf?.asn ?? null;
    const asOrg = request.cf?.asOrganization || null;
    if (classify({ userAgent, asn, asOrg })) return redirect;

    const from = new URL(request.url).searchParams.get("from") || "";
    const place = PLACES.has(from) ? from : "other";
    const now = Date.now();
    waitUntil(
      countClick(env.DB, { day: utcDay(now), place, now, ip, userAgent })
        .catch((err) => console.error("kofi click:", err.message))
    );
  } catch (err) {
    console.error("kofi tracking error:", err.message);
  }

  return redirect;
}
