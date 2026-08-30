// Cloudflare Pages Function — traccia le visite alle pagine di osmiumsound.it
// in D1 (stesso database usato da file.osmiumsound.it per i download), poi
// lascia sempre proseguire la richiesta: un errore nel tracking non deve mai
// impedire il caricamento della pagina.
//
// Richiede il binding D1 "DB" sul progetto Pages (Settings → Functions →
// D1 database bindings), puntato allo stesso database "osmium-downloads"
// usato da osmium-iso-tracker. Tabelle: page_views (una riga per pagina,
// vedi schema_pageviews.sql) e site_visits (una riga per IP, indipendente
// dalla pagina — usata per il conteggio "visite uniche"; vedi
// schema_visits.sql), entrambe nel repo osmium-iso-tracker.

const SESSION_WINDOW_MS = 30 * 60 * 1000;
const BOT_PATTERNS = [
  /bot/i, /crawl/i, /spider/i, /scrap/i, /wget/i, /curl/i,
  /python-requests/i, /httpclient/i, /go-http-client/i, /java\//i,
  /libwww/i, /httpx/i, /okhttp/i, /aria2/i, /axios/i,
  // Anteprime dei link sui social: non hanno "bot" nello user-agent
  /facebookexternalhit/i,
];

// Estensioni statiche da non contare come "visita a una pagina"
const ASSET_EXTENSIONS = /\.(png|jpe?g|gif|svg|webp|avif|ico|css|js|mjs|map|json|woff2?|ttf|eot|otf|mp4|webm|pdf|xml|txt|zip)$/i;

function isBot(userAgent) {
  if (!userAgent) return true;
  return BOT_PATTERNS.some((p) => p.test(userAgent));
}

function getCountry(request) {
  return request.cf?.country || "XX";
}

function getIP(request) {
  return (
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "0.0.0.0"
  );
}

async function logPageView(db, { ip, user_agent, path, country, is_bot }) {
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
      `INSERT INTO page_views (ip, user_agent, path, country, is_bot, request_count, first_seen, last_seen)
       VALUES (?, ?, ?, ?, ?, 1, ?, ?)`
    ).bind(ip, user_agent, path, country, is_bot, now, now).run();
  }
}

// Dedupe solo per IP (non per pagina): una persona che naviga piu' pagine
// nella stessa finestra di sessione conta come 1 sola visita.
async function logVisit(db, { ip, user_agent, country, is_bot }) {
  const now = Date.now();
  const windowStart = now - SESSION_WINDOW_MS;

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
    await db.prepare(
      `INSERT INTO site_visits (ip, user_agent, country, is_bot, page_count, first_seen, last_seen)
       VALUES (?, ?, ?, ?, 1, ?, ?)`
    ).bind(ip, user_agent, country, is_bot, now, now).run();
  }
}

export async function onRequest(context) {
  const { request, env, waitUntil } = context;
  const response = await context.next();

  try {
    const url = new URL(request.url);
    const trackable =
      request.method === "GET" &&
      response.status === 200 &&
      !ASSET_EXTENSIONS.test(url.pathname);

    if (trackable && env.DB) {
      const ip = getIP(request);
      const user_agent = request.headers.get("user-agent") || "";
      const country = getCountry(request);
      const is_bot = isBot(user_agent) ? 1 : 0;

      waitUntil(logPageView(env.DB, { ip, user_agent, path: url.pathname, country, is_bot }));
      waitUntil(logVisit(env.DB, { ip, user_agent, country, is_bot }));
    }
  } catch (err) {
    console.error("page_views tracking error:", err.message);
  }

  return response;
}
