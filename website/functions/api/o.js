// Cloudflare Pages Function — receives the browser beacon sent by /o.js and
// counts visits the way Umami and Plausible do, minus everything that could
// point back at a person:
//
// - only browsers that run JavaScript get here, so vulnerability scanners and
//   HTML scrapers are out before any rule runs;
// - every event is classified (see _lib/traffic.js). What is filtered out
//   becomes a count per reason and network in site_drops, not a stored request;
// - no cookies, no stored IP address, and no row per visitor anywhere. The IP
//   and the user-agent become a hash of a random daily salt (Plausible's
//   scheme), the hash goes into a HyperLogLog sketch, and both are gone when
//   the request ends. The salt is deleted the day after.
//
// Tables: site_daily, downloads_daily, site_breakdown, site_drops and
// site_salts (website/analytics/01_aggregates.sql). The dashboard lives at
// file.osmiumsound.it/stats/site.

import { classify, parseUA } from "../_lib/traffic.js";
import {
  CLICK,
  DOWNLOADS_DAILY,
  SITE_DAILY,
  breakdownStatement,
  dailyStatement,
  dropStatement,
} from "../_lib/counters.js";
import { utcDay, visitorHash } from "../_lib/visitor.js";

const MAX_BODY = 2048;
const EVENT_NAMES = new Set(["pageview", "download"]);

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

  const db = env.DB;
  const now = Date.now();
  const day = utcDay(now);
  const userAgent = (request.headers.get("user-agent") || "").slice(0, 400);
  const asn = request.cf?.asn ?? null;
  const asOrg = request.cf?.asOrganization || null;

  try {
    const pageUrl = (() => {
      try {
        return new URL(String(body.u || "/"), `https://${site}`);
      } catch {
        return new URL(`https://${site}/`);
      }
    })();
    const refHostRaw = hostOf(body.r);
    const refHost = refHostRaw && refHostRaw !== site ? refHostRaw : null;

    let reason = body.a ? "automation" : classify({ userAgent, asn, asOrg });
    if (!reason && refHost && SPAM_REFERRER.test(refHost)) reason = "spam_ref";
    if (reason) {
      await dropStatement(db, { day, reason, asn, asOrg }).run();
      return reply(202);
    }

    const hash = await visitorHash(db, now, ip, userAgent);

    if (body.n === "download") {
      let file;
      try {
        const target = new URL(String(body.t));
        if (!/^https?:$/.test(target.protocol)) return reply(400);
        file = (target.host + target.pathname).slice(0, 300);
      } catch {
        return reply(400);
      }
      // A click, not a file going out: the worker that serves the file counts
      // that one, and the two must not add up.
      const statement = await dailyStatement(db, DOWNLOADS_DAILY, { day, key: [file, CLICK], hash });
      await statement.run();
      return reply(202);
    }

    // Pageview
    const path = normalizePath(pageUrl.pathname);
    const q = pageUrl.searchParams;
    const utmSource = (q.get("utm_source") || q.get("ref") || q.get("source") || "").slice(0, 80) || null;
    const utmMedium = (q.get("utm_medium") || "").slice(0, 80) || null;
    const { browser, os } = parseUA(userAgent);

    // One count per dimension per page view. Separated from the visit that
    // held them together, a country and a browser name single nobody out.
    const dims = {
      country: request.cf?.country || "XX",
      browser,
      os,
      source: utmSource || sourceName(refHost) || "Diretto",
      channel: channelOf({ refHost, utmMedium, utmSource }),
    };

    const daily = await dailyStatement(db, SITE_DAILY, { day, key: path, hash });
    await db.batch([
      daily,
      ...Object.entries(dims).map(([dim, value]) => breakdownStatement(db, { day, dim, value })),
    ]);
    return reply(202);
  } catch (err) {
    console.error("beacon error:", err.message);
    return reply(500);
  }
}
