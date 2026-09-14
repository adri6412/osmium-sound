// Cloudflare Pages Function — server-side request log for osmiumsound.it,
// written to D1 (same database file.osmiumsound.it uses for downloads). The
// request always goes through: a tracking error must never break the page.
//
// This is the raw log: it sees every request, including scanners and scrapers
// that never run JavaScript. The visitor numbers on the dashboard come from
// the browser beacon instead (functions/api/o.js + /o.js), the way Umami and
// Plausible count; this log stays for diagnosis and for the history before
// the beacon existed.
//
// Requires the D1 binding "DB" on the Pages project, pointed at the
// "osmium-downloads" database. Tables: page_views (one row per page per IP
// per 30 minutes, schema_pageviews.sql) and site_visits (one row per IP per
// day, schema_visits.sql), both in the osmium-iso-tracker repo.
//
// Optional environment variable EXCLUDE_IPS: comma-separated IPs that are
// never recorded (your own, so you don't count yourself).

import { isBot, isDatacenter, PROBE_PATHS } from "./_lib/traffic.js";

// Views of the same page from the same IP: 30 minutes (page_views).
const SESSION_WINDOW_MS = 30 * 60 * 1000;
// Site visits: one day. With the short window the same person coming back
// three times in an afternoon was three visits (site_visits).
const VISIT_WINDOW_MS = 24 * 60 * 60 * 1000;

// Static files that are not a visit to a page
const ASSET_EXTENSIONS = /\.(png|jpe?g|gif|svg|webp|avif|ico|css|js|mjs|map|json|woff2?|ttf|eot|otf|mp4|webm|pdf|xml|txt|zip)$/i;

// Only a browser that actually draws the page fetches images and fonts; a
// scraper takes the HTML and leaves. Marks the visit as "browser confirmed".
const RENDER_ASSETS = /\.(png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|otf)$/i;

// The F-Droid repository: update checks (entry.jar) and APK downloads stay
// recorded so they can be counted, but they are not a person reading a page.
const NON_PAGE_EXTENSIONS = /\.(jar|apk)$/i;

// A second way to confirm a browser, independent of the cache: the headers
// every browser sends when it opens a page (Fetch Metadata, or Accept: text/html
// with Accept-Language and Accept-Encoding). Needed because image confirmation
// only fires when the image misses Cloudflare's cache.
function looksLikeBrowserRequest(request) {
  const h = request.headers;
  if (h.get("sec-fetch-dest") === "document" && h.get("sec-fetch-mode") === "navigate") {
    return true;
  }
  const accept = h.get("accept") || "";
  return accept.includes("text/html") && !!h.get("accept-language") && !!h.get("accept-encoding");
}

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

async function logPageView(db, { ip, user_agent, path, country, is_bot, is_dc, asn, as_org }) {
  const now = Date.now();
  const windowStart = now - SESSION_WINDOW_MS;

  const existing = await db.prepare(
    `SELECT id FROM page_views
     WHERE ip = ? AND path = ? AND last_seen > ?
     ORDER BY last_seen DESC LIMIT 1`
  ).bind(ip, path, windowStart).first();

  if (existing) {
    await db.prepare(
      `UPDATE page_views SET last_seen = ?, request_count = request_count + 1 WHERE id = ?`
    ).bind(now, existing.id).run();
  } else {
    await db.prepare(
      `INSERT INTO page_views (ip, user_agent, path, country, is_bot, is_dc, asn, as_org, request_count, first_seen, last_seen)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`
    ).bind(ip, user_agent, path, country, is_bot, is_dc, asn, as_org, now, now).run();
  }
}

// Deduplicated by IP only (not by page): one person reading several pages in
// the same day is one visit.
async function logVisit(db, { ip, user_agent, country, is_bot, is_dc, asn, as_org, browser_confirmed }) {
  const now = Date.now();
  const windowStart = now - VISIT_WINDOW_MS;

  const existing = await db.prepare(
    `SELECT id FROM site_visits
     WHERE ip = ? AND last_seen > ?
     ORDER BY last_seen DESC LIMIT 1`
  ).bind(ip, windowStart).first();

  if (existing) {
    await db.prepare(
      `UPDATE site_visits SET last_seen = ?, page_count = page_count + 1 WHERE id = ?`
    ).bind(now, existing.id).run();
  } else {
    // 11 columns, 11 values: an extra placeholder here silently stopped
    // every insert from 2026-09-04 to 2026-09-14.
    await db.prepare(
      `INSERT INTO site_visits (ip, user_agent, country, is_bot, is_dc, asn, as_org, browser_confirmed, page_count, first_seen, last_seen)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`
    ).bind(ip, user_agent, country, is_bot, is_dc, asn, as_org, browser_confirmed, now, now).run();
  }
}

// Marks the current visit as "browser confirmed" when the same IP also asks
// for images or fonts. One UPDATE, no SELECT: nothing is written when the
// visit is already confirmed.
async function confirmBrowser(db, ip) {
  const windowStart = Date.now() - VISIT_WINDOW_MS;
  await db.prepare(
    `UPDATE site_visits SET browser_confirmed = 1
     WHERE ip = ? AND last_seen > ? AND browser_confirmed = 0`
  ).bind(ip, windowStart).run();
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

      if (ASSET_EXTENSIONS.test(url.pathname)) {
        if (RENDER_ASSETS.test(url.pathname)) {
          waitUntil(confirmBrowser(env.DB, ip).catch(logError("confirmBrowser")));
        }
        return response;
      }

      const user_agent = request.headers.get("user-agent") || "";
      const country = request.cf?.country || "XX";
      const asn = request.cf?.asn ?? null;
      const as_org = request.cf?.asOrganization || null;
      const probe = PROBE_PATHS.test(url.pathname);
      const ua_bot = isBot(user_agent) || probe ? 1 : 0;
      const dc = isDatacenter(asn, as_org) ? 1 : 0;
      const isPage = !NON_PAGE_EXTENSIONS.test(url.pathname) && !probe;

      waitUntil(logPageView(env.DB, {
        ip, user_agent, path: url.pathname, country,
        is_bot: ua_bot || !isPage ? 1 : 0,
        is_dc: dc,
        asn, as_org,
      }).catch(logError("logPageView")));

      // An APK download, an F-Droid index check or a vulnerability probe is not
      // a visit to the site: it neither opens nor extends a visit.
      if (isPage) {
        waitUntil(logVisit(env.DB, {
          ip, user_agent, country, is_bot: ua_bot, is_dc: dc, asn, as_org,
          browser_confirmed: looksLikeBrowserRequest(request) ? 1 : 0,
        }).catch(logError("logVisit")));
      }
    }
  } catch (err) {
    console.error("page_views tracking error:", err.message);
  }

  return response;
}
