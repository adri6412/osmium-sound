// Cloudflare Pages Function — traccia le visite alle pagine di osmiumsound.it
// in D1 (stesso database usato da file.osmiumsound.it per i download), poi
// lascia sempre proseguire la richiesta: un errore nel tracking non deve mai
// impedire il caricamento della pagina.
//
// Richiede il binding D1 "DB" sul progetto Pages (Settings → Functions →
// D1 database bindings), puntato allo stesso database "osmium-downloads"
// usato da osmium-iso-tracker. Tabella: page_views (vedi schema_pageviews.sql
// nel repo osmium-iso-tracker).

const SESSION_WINDOW_MS = 30 * 60 * 1000;
const BOT_PATTERNS = [
  /bot/i, /crawl/i, /spider/i, /scrap/i, /wget/i, /curl/i,
  /python-requests/i, /httpclient/i, /go-http-client/i, /java\//i,
  /libwww/i, /httpx/i, /okhttp/i, /aria2/i, /axios/i,
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
      waitUntil(
        logPageView(env.DB, {
          ip: getIP(request),
          user_agent: request.headers.get("user-agent") || "",
          path: url.pathname,
          country: getCountry(request),
          is_bot: isBot(request.headers.get("user-agent") || "") ? 1 : 0,
        })
      );
    }
  } catch (err) {
    console.error("page_views tracking error:", err.message);
  }

  return response;
}
