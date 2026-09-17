// Cloudflare Pages Function — aggregate counters for osmiumsound.it, written
// to D1 (same database file.osmiumsound.it uses for downloads). The request
// always goes through: a tracking error must never break the page.
//
// Nothing that identifies a visitor is written. The IP address and the
// user-agent are read from the request, used to tell a person from a scanner
// and to derive the day's visitor hash, and then dropped with the request:
// what reaches D1 is a count per day, a HyperLogLog sketch and the reason a
// request was not counted, per network.
//
// Pages are counted by the browser beacon (functions/api/o.js + /o.js), the
// way Umami and Plausible count. This function only records the two things the
// beacon cannot see, because they never run JavaScript:
//
//   - files the site serves itself (the F-Droid repository: .apk and .jar),
//     into downloads_daily;
//   - requests that do not count as a person, into site_drops, so a network
//     filtered out by mistake is visible in the numbers.
//
// Requires the D1 binding "DB" on the Pages project, pointed at the
// "osmium-downloads" database (tables in website/analytics/01_aggregates.sql).
//
// Optional environment variable EXCLUDE_IPS: comma-separated IPs that are
// never counted (your own, so you don't count yourself).

import { classify, isDatacenter, PROBE_PATHS } from "./_lib/traffic.js";
import { DOWNLOADS_DAILY, dailyStatement, dropStatement } from "./_lib/counters.js";
import { utcDay, visitorHash } from "./_lib/visitor.js";

// Files served from the site itself and worth counting: the F-Droid repository
// index and the APKs. Everything else on file.osmiumsound.it is counted by the
// worker that serves it.
const DOWNLOAD_EXTENSIONS = /\.(apk|jar)$/i;

// Static files that are neither a page nor a download
const ASSET_EXTENSIONS = /\.(png|jpe?g|gif|svg|webp|avif|ico|css|js|mjs|map|json|woff2?|ttf|eot|otf|mp4|webm|pdf|xml|txt|zip)$/i;

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

// A download is judged by the network only. People fetch files with curl, with
// wget, with a download manager and with the F-Droid client, all of which the
// user-agent rules call programs; a hosting network asking for an APK is not
// somebody installing it.
function downloadReason(asn, asOrg) {
  return isDatacenter(asn, asOrg) ? "datacenter" : null;
}

async function countDownload(db, { day, file, now, ip, userAgent }) {
  const hash = await visitorHash(db, now, ip, userAgent);
  const statement = await dailyStatement(db, DOWNLOADS_DAILY, { day, key: file, hash });
  await statement.run();
}

function logError(label) {
  return (err) => console.error(label, err.message);
}

export async function onRequest(context) {
  const { request, env, waitUntil } = context;
  const response = await context.next();

  try {
    const url = new URL(request.url);
    const served = request.method === "GET" && response.status === 200;

    if (served && env.DB) {
      const ip = getIP(request);
      if (isExcluded(ip, env)) return response;

      const isDownload = DOWNLOAD_EXTENSIONS.test(url.pathname);
      if (!isDownload && ASSET_EXTENSIONS.test(url.pathname)) return response;

      const userAgent = request.headers.get("user-agent") || "";
      const asn = request.cf?.asn ?? null;
      const asOrg = request.cf?.asOrganization || null;
      const now = Date.now();
      const day = utcDay(now);

      const reason = isDownload
        ? downloadReason(asn, asOrg)
        : PROBE_PATHS.test(url.pathname)
          ? "probe"
          : classify({ userAgent, asn, asOrg });

      if (reason) {
        waitUntil(dropStatement(env.DB, { day, reason, asn, asOrg }).run().catch(logError("site_drops")));
        return response;
      }

      // A page that passes the filters is counted by the beacon, not here:
      // counting it twice would be worse than not counting the few visitors
      // who run without JavaScript.
      if (isDownload) {
        const file = `${url.host}${url.pathname}`;
        waitUntil(countDownload(env.DB, { day, file, now, ip, userAgent }).catch(logError("downloads_daily")));
      }
    }
  } catch (err) {
    console.error("tracking error:", err.message);
  }

  return response;
}
