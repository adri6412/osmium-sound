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
//
// NB: il riconoscimento dei bot qui sotto e' identico a quello del worker
// osmium-iso-tracker (src/index.js). Se cambi un pattern, cambialo in
// entrambi i file, altrimenti download e visite si contano con regole
// diverse.

const SESSION_WINDOW_MS = 30 * 60 * 1000;

const BOT_PATTERNS = [
  /bot/i, /crawl/i, /spider/i, /scrap/i, /wget/i, /curl/i,
  /python-requests/i, /httpclient/i, /go-http-client/i, /java\//i,
  /libwww/i, /httpx/i, /okhttp/i, /aria2/i, /axios/i,
  // Anteprime dei link sui social: nessuno di questi ha "bot" nello user-agent
  /facebookexternalhit/i, /meta-externalagent/i, /facebookcatalog/i,
  /whatsapp/i, /skypeuripreview/i, /embedly/i, /iframely/i, /vkshare/i,
  // Client automatici e infrastruttura: non e' una persona che guarda la pagina
  /headless/i, /node-fetch/i, /dart\//i, /deno\//i, /lighthouse/i,
  /prefetch proxy/i, /^hello from/i, /paloalto/i, /f-droid/i,
];

// Estensioni statiche da non contare come "visita a una pagina"
const ASSET_EXTENSIONS = /\.(png|jpe?g|gif|svg|webp|avif|ico|css|js|mjs|map|json|woff2?|ttf|eot|otf|mp4|webm|pdf|xml|txt|zip)$/i;

// Risorse che scarica solo un browser che sta davvero disegnando la pagina:
// immagini e font. Uno scraper si prende l'HTML e basta. Serve a marcare la
// visita come "browser confermato" (vedi confirmBrowser).
const RENDER_ASSETS = /\.(png|jpe?g|gif|svg|webp|avif|ico|woff2?|ttf|otf)$/i;

// Il repository F-Droid: i controlli aggiornamento dell'app (entry.jar) e i
// download di APK restano registrati per poterli contare, ma non sono la
// visita di una persona a una pagina.
const NON_PAGE_EXTENSIONS = /\.(jar|apk)$/i;

// Alcuni scraper si spacciano per browser ma sbagliano la formula fissa dello
// user-agent: ogni browser vero che dichiara AppleWebKit scrive subito dopo
// anche "(KHTML, like Gecko)".
function hasForgedBrowserUA(userAgent) {
  return /applewebkit/i.test(userAgent) && !/khtml, like gecko/i.test(userAgent);
}

function isBot(userAgent) {
  if (!userAgent) return true;
  if (hasForgedBrowserUA(userAgent)) return true;
  return BOT_PATTERNS.some((p) => p.test(userAgent));
}

// Seconda strada, indipendente dalla cache: gli header che un browser manda
// sempre quando apre una pagina. Chrome, Firefox e Safari mandano la terna
// Fetch Metadata (sec-fetch-*); tutti mandano comunque Accept: text/html
// insieme a Accept-Language e Accept-Encoding. curl, python-requests e gli
// scraper artigianali quasi mai. Serve perche' la conferma tramite immagini
// (confirmBrowser) scatta solo quando la richiesta sfugge alla cache di
// Cloudflare: se l'immagine e' gia' in cache, la funzione non viene eseguita.
function looksLikeBrowserRequest(request) {
  const h = request.headers;
  if (h.get("sec-fetch-dest") === "document" && h.get("sec-fetch-mode") === "navigate") {
    return true;
  }
  const accept = h.get("accept") || "";
  return accept.includes("text/html") && !!h.get("accept-language") && !!h.get("accept-encoding");
}

function getCountry(request) {
  return request.cf?.country || "XX";
}

// Rete di provenienza. Un IP di Amazon, Hetzner o OVH e' una macchina
// qualunque cosa dichiari lo user-agent; un IP di Fastweb o Vodafone e' una
// persona. Cloudflare passa gia' questi due campi a ogni richiesta.
function getASN(request) {
  return request.cf?.asn ?? null;
}

function getASOrg(request) {
  return request.cf?.asOrganization || null;
}

function getIP(request) {
  return (
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "0.0.0.0"
  );
}

async function logPageView(db, { ip, user_agent, path, country, is_bot, asn, as_org }) {
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
      `INSERT INTO page_views (ip, user_agent, path, country, is_bot, asn, as_org, request_count, first_seen, last_seen)
       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`
    ).bind(ip, user_agent, path, country, is_bot, asn, as_org, now, now).run();
  }
}

// Dedupe solo per IP (non per pagina): una persona che naviga piu' pagine
// nella stessa finestra di sessione conta come 1 sola visita.
async function logVisit(db, { ip, user_agent, country, is_bot, asn, as_org, browser_confirmed }) {
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
      `INSERT INTO site_visits (ip, user_agent, country, is_bot, asn, as_org, browser_confirmed, page_count, first_seen, last_seen)
       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`
    ).bind(ip, user_agent, country, is_bot, asn, as_org, browser_confirmed, now, now).run();
  }
}

// Marca la visita in corso come "browser confermato" quando dallo stesso IP
// arriva anche una richiesta di immagini o font. Non tocca il conteggio delle
// visite: e' un indizio in piu', da valutare sui dati prima di fidarsene.
// Una sola UPDATE, senza SELECT: se la visita e' gia' confermata non scrive.
async function confirmBrowser(db, ip) {
  const windowStart = Date.now() - SESSION_WINDOW_MS;
  await db.prepare(
    `UPDATE site_visits SET browser_confirmed = 1
     WHERE ip = ? AND last_seen > ? AND browser_confirmed = 0`
  ).bind(ip, windowStart).run();
}

export async function onRequest(context) {
  const { request, env, waitUntil } = context;
  const response = await context.next();

  try {
    const url = new URL(request.url);
    const served = request.method === "GET" && response.status === 200;

    if (served && env.DB) {
      const isAsset = ASSET_EXTENSIONS.test(url.pathname);

      if (isAsset) {
        if (RENDER_ASSETS.test(url.pathname)) {
          waitUntil(confirmBrowser(env.DB, getIP(request)));
        }
        return response;
      }

      const ip = getIP(request);
      const user_agent = request.headers.get("user-agent") || "";
      const country = getCountry(request);
      const asn = getASN(request);
      const as_org = getASOrg(request);
      const ua_bot = isBot(user_agent) ? 1 : 0;
      const isPage = !NON_PAGE_EXTENSIONS.test(url.pathname);

      waitUntil(logPageView(env.DB, {
        ip, user_agent, path: url.pathname, country,
        is_bot: ua_bot || !isPage ? 1 : 0,
        asn, as_org,
      }));

      // Scaricare un APK o controllare il repository F-Droid non e' una visita
      // al sito: non apre (ne' prolunga) una sessione.
      if (isPage) {
        waitUntil(logVisit(env.DB, {
          ip, user_agent, country, is_bot: ua_bot, asn, as_org,
          browser_confirmed: looksLikeBrowserRequest(request) ? 1 : 0,
        }));
      }
    }
  } catch (err) {
    console.error("page_views tracking error:", err.message);
  }

  return response;
}
