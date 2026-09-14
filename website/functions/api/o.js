// Cloudflare Pages Function — receives the browser beacon sent by /o.js and
// records visits the way Umami and Plausible do:
//
// - only browsers that run JavaScript get here, so vulnerability scanners and
//   HTML scrapers are out before any rule runs;
// - every event is classified (see _lib/traffic.js); filtered visits are kept
//   with their reason so the dashboard can show what was dropped and why;
// - no cookies and no stored IP address. A visitor is a hash of a random
//   daily salt + IP + user-agent (Plausible's scheme): today's visitor cannot
//   be linked to yesterday's, and the salt is deleted after a day;
// - a visit (session) ends after 30 minutes without events, as in both tools.
//
// Tables: site_sessions, site_events, site_salts (schema_analytics.sql in the
// osmium-iso-tracker repo). The dashboard lives at file.osmiumsound.it/stats/site.

import { classify, parseUA } from "../_lib/traffic.js";

const SESSION_MS = 30 * 60 * 1000;
const MAX_BODY = 2048;
const EVENT_NAMES = new Set(["pageview", "engagement", "download", "outbound"]);

// A session that opens 25 pages in its first minute is not somebody reading.
const BURST_PAGES = 25;
const BURST_MS = 60 * 1000;

// Referrer spam: domains that fake visits to get their name into dashboards.
// A short version of the Matomo list Plausible uses.
const SPAM_REFERRER = /(semalt|darodar|buttons-for|ilovevitaly|priceg\.com|hulfingtonpost|best-seo|seo-?(offer|platform|analyses|tool)|traffic2money|free-share-buttons|get-free-traffic|webmonetizer|social-buttons|trafficbot|site-auditor|rank-checker)/i;

const SEARCH = /(^|\.)(google|bing|duckduckgo|yahoo|ecosia|qwant|yandex|baidu|startpage|search\.brave|naver|seznam|sogou|mojeek|kagi)\./i;
const SOCIAL = /(^|\.)(facebook|fb|instagram|t\.co|twitter|x\.com|linkedin|lnkd\.in|reddit|youtube|youtu\.be|tiktok|pinterest|threads|mastodon|telegram|whatsapp|tumblr|vk\.com|discord)(\.|$)/i;
const AI_CHAT = /(^|\.)(chatgpt\.com|openai\.com|perplexity\.ai|claude\.ai|gemini\.google\.com|copilot\.microsoft\.com|you\.com|phind\.com|deepseek\.com)$/i;

const SOURCE_NAMES = [
  [/(^|\.)google\./i, "Google"], [/(^|\.)bing\./i, "Bing"], [/duckduckgo\./i, "DuckDuckGo"],
  [/(^|\.)(facebook|fb)\./i, "Facebook"], [/instagram\./i, "Instagram"], [/^(t\.co|twitter\.com|x\.com)$/i, "X (Twitter)"],
  [/reddit\./i, "Reddit"], [/(youtube\.|youtu\.be)/i, "YouTube"], [/linkedin\.|lnkd\.in/i, "LinkedIn"],
  [/github\.com$/i, "GitHub"], [/chatgpt\.com|openai\.com/i, "ChatGPT"], [/perplexity\.ai/i, "Perplexity"],
  [/ecosia\./i, "Ecosia"], [/yahoo\./i, "Yahoo"], [/ko-fi\.com$/i, "Ko-fi"],
];

function reply(status) {
  return new Response(null, { status, headers: { "cache-control": "no-store" } });
}

function isExcluded(ip, env) {
  if (!env.EXCLUDE_IPS) return false;
  return env.EXCLUDE_IPS.split(",").some((entry) => entry.trim() === ip);
}

function hostOf(value) {
  try {
    return new URL(value).host.toLowerCase();
  } catch {
    return null;
  }
}

function normalizePath(pathname) {
  let p = String(pathname || "/").split(/[?#]/)[0];
  p = p.replace(/\/index\.html$/i, "/").replace(/\.html$/i, "");
  if (p.length > 1) p = p.replace(/\/+$/, "");
  return (p || "/").slice(0, 200);
}

function int(value, min, max) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

function sourceName(host) {
  if (!host) return null;
  const bare = host.replace(/^(www|m|l|lm|mobile)\./, "");
  for (const [re, name] of SOURCE_NAMES) if (re.test(bare)) return name;
  return bare;
}

function channelOf({ refHost, utmMedium, utmSource }) {
  const medium = (utmMedium || "").toLowerCase();
  if (/^(cpc|ppc|paid|paidsearch|display|cpm)$/.test(medium)) return "A pagamento";
  if (/e-?mail|newsletter/.test(medium)) return "Email";
  if (refHost && AI_CHAT.test(refHost)) return "Assistenti AI";
  if (refHost && SEARCH.test(refHost)) return "Ricerca";
  if ((refHost && SOCIAL.test(refHost)) || /social/.test(medium)) return "Social";
  if (refHost || utmSource) return "Altri siti";
  return "Diretto";
}

function hex(bytes) {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Daily salt, generated at random the first time it is needed and deleted the
// day after: the hash of an IP cannot be reversed or linked across days.
const saltCache = new Map();

async function dailySalt(db, now) {
  const day = new Date(now).toISOString().slice(0, 10);
  const cached = saltCache.get(day);
  if (cached) return cached;
  const fresh = hex(crypto.getRandomValues(new Uint8Array(16)));
  const yesterday = new Date(now - 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
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

async function visitorId(db, now, ip, userAgent) {
  const salt = await dailySalt(db, now);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${salt}|${ip}|${userAgent}`));
  return hex(digest).slice(0, 32);
}

export async function onRequestPost({ request, env }) {
  if (!env.DB) return reply(204);
  const site = new URL(request.url).host;

  // Same-origin only: the beacon is sent by our own pages. Blocks events
  // forged from elsewhere without needing a key in the page.
  const origin = hostOf(request.headers.get("origin")) || hostOf(request.headers.get("referer"));
  if (origin !== site) return reply(403);

  const ip = request.headers.get("cf-connecting-ip") || "0.0.0.0";
  if (isExcluded(ip, env)) return reply(204);

  const raw = await request.text();
  if (raw.length > MAX_BODY) return reply(413);
  let body;
  try {
    body = JSON.parse(raw);
  } catch {
    return reply(400);
  }
  if (!body || !EVENT_NAMES.has(body.n)) return reply(400);
  const pageId = typeof body.p === "string" && /^[a-z0-9]{8,32}$/.test(body.p) ? body.p : null;
  if (!pageId) return reply(400);

  const db = env.DB;
  const now = Date.now();
  const userAgent = (request.headers.get("user-agent") || "").slice(0, 400);

  try {
    const visitor = await visitorId(db, now, ip, userAgent);
    const session = await db.prepare(
      `SELECT id, started, pageviews FROM site_sessions
       WHERE visitor_id = ? AND last_seen > ?
       ORDER BY last_seen DESC LIMIT 1`
    ).bind(visitor, now - SESSION_MS).first();

    if (body.n === "engagement") {
      if (!session) return reply(202);
      const engaged = int(body.e, 0, SESSION_MS);
      const scroll = int(body.s, 0, 100);
      const interacted = body.i ? 1 : 0;
      await db.batch([
        db.prepare(
          `UPDATE site_events SET engaged_ms = engaged_ms + ?, scroll = MAX(scroll, ?), interacted = MAX(interacted, ?)
           WHERE page_id = ? AND session_id = ? AND name = 'pageview'`
        ).bind(engaged, scroll, interacted, pageId, session.id),
        db.prepare(
          `UPDATE site_sessions SET last_seen = ?, engaged_ms = engaged_ms + ?,
             max_scroll = MAX(max_scroll, ?), interacted = MAX(interacted, ?)
           WHERE id = ?`
        ).bind(now, engaged, scroll, interacted, session.id),
      ]);
      return reply(202);
    }

    const pageUrl = (() => {
      try {
        return new URL(String(body.u || "/"), `https://${site}`);
      } catch {
        return new URL(`https://${site}/`);
      }
    })();
    const path = normalizePath(pageUrl.pathname);

    if (body.n === "download" || body.n === "outbound") {
      if (!session) return reply(202);
      let target;
      try {
        const t = new URL(String(body.t));
        if (!/^https?:$/.test(t.protocol)) return reply(400);
        target = (t.host + t.pathname).slice(0, 300);
      } catch {
        return reply(400);
      }
      await db.batch([
        db.prepare(
          `INSERT INTO site_events (ts, name, session_id, visitor_id, page_id, path, target)
           VALUES (?, ?, ?, ?, ?, ?, ?)`
        ).bind(now, body.n, session.id, visitor, pageId, path, target),
        db.prepare(
          `UPDATE site_sessions SET last_seen = ?, goals = goals + 1, interacted = 1 WHERE id = ?`
        ).bind(now, session.id),
      ]);
      return reply(202);
    }

    // Pageview
    const asn = request.cf?.asn ?? null;
    const asOrg = request.cf?.asOrganization || null;
    const refHostRaw = hostOf(body.r);
    const refHost = refHostRaw && refHostRaw !== site ? refHostRaw : null;
    const q = pageUrl.searchParams;
    const utmSource = (q.get("utm_source") || q.get("ref") || q.get("source") || "").slice(0, 80) || null;
    const utmMedium = (q.get("utm_medium") || "").slice(0, 80) || null;
    const utmCampaign = (q.get("utm_campaign") || "").slice(0, 80) || null;

    let reason = body.a ? "automation" : classify({ userAgent, asn, asOrg });
    if (!reason && refHost && SPAM_REFERRER.test(refHost)) reason = "spam_ref";

    if (session) {
      if (!reason && session.pageviews + 1 >= BURST_PAGES && now - session.started < BURST_MS) {
        reason = "burst";
      }
      await db.batch([
        db.prepare(
          `UPDATE site_sessions SET last_seen = ?, pageviews = pageviews + 1, exit_path = ?,
             reason = COALESCE(reason, ?)
           WHERE id = ?`
        ).bind(now, path, reason, session.id),
        db.prepare(
          `INSERT INTO site_events (ts, name, session_id, visitor_id, page_id, path)
           VALUES (?, 'pageview', ?, ?, ?, ?)`
        ).bind(now, session.id, visitor, pageId, path),
      ]);
      return reply(202);
    }

    const screenWidth = int(body.w, 0, 10000);
    const { browser, os, device } = parseUA(userAgent, screenWidth);
    const lang = typeof body.l === "string" && /^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})?$/.test(body.l)
      ? body.l.slice(0, 2).toLowerCase()
      : null;
    const sessionId = crypto.randomUUID();
    const cf = request.cf || {};

    await db.batch([
      db.prepare(
        `INSERT INTO site_sessions (id, visitor_id, started, last_seen, pageviews, entry_path, exit_path,
           referrer, source, channel, utm_medium, utm_campaign, country, region, city,
           browser, os, device, screen_w, lang, asn, as_org, http_proto, reason)
         VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
      ).bind(
        sessionId, visitor, now, now, path, path,
        refHost, utmSource || sourceName(refHost), channelOf({ refHost, utmMedium, utmSource }),
        utmMedium, utmCampaign,
        cf.country || null, cf.region || null, cf.city || null,
        browser, os, device, screenWidth || null, lang,
        asn, asOrg, cf.httpProtocol || null, reason
      ),
      db.prepare(
        `INSERT INTO site_events (ts, name, session_id, visitor_id, page_id, path)
         VALUES (?, 'pageview', ?, ?, ?, ?)`
      ).bind(now, sessionId, visitor, pageId, path),
    ]);
    return reply(202);
  } catch (err) {
    console.error("beacon error:", err.message);
    return reply(500);
  }
}
