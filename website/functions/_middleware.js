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
// Variabile d'ambiente opzionale EXCLUDE_IPS: elenco di IP separati da virgola
// che non vengono registrati affatto (i tuoi, per non contarti da solo).
//
// NB: il riconoscimento dei bot qui sotto e' identico a quello del worker
// osmium-iso-tracker (src/index.js). Se cambi un pattern, cambialo in
// entrambi i file, altrimenti download e visite si contano con regole
// diverse.

// Viste della stessa pagina dallo stesso IP: 30 minuti (page_views).
const SESSION_WINDOW_MS = 30 * 60 * 1000;
// Visite al sito: un giorno. Con la finestra breve la stessa persona che
// tornava sul sito tre volte in un pomeriggio valeva tre "visite"; qui una
// visita e' un visitatore unico nelle 24 ore (site_visits).
const VISIT_WINDOW_MS = 24 * 60 * 60 * 1000;

const BOT_PATTERNS = [
  /bot/i, /crawl/i, /spider/i, /scrap/i, /wget/i, /curl/i,
  /python-requests/i, /httpclient/i, /go-http-client/i, /java\//i,
  /libwww/i, /httpx/i, /okhttp/i, /aria2/i, /axios/i,
  /urllib/i, /guzzle/i, /fasthttp/i,
  // Anteprime dei link sui social: nessuno di questi ha "bot" nello user-agent
  /facebookexternalhit/i, /meta-externalagent/i, /facebookcatalog/i,
  /whatsapp/i, /skypeuripreview/i, /embedly/i, /iframely/i, /vkshare/i,
  // Client automatici e infrastruttura: non e' una persona che guarda la pagina
  /headless/i, /node-fetch/i, /dart\//i, /deno\//i, /lighthouse/i,
  /prefetch proxy/i, /^hello from/i, /paloalto/i, /f-droid/i,
  /crusader/i, /worker\//i, /probe/i,
  // Scanner di rete: si annunciano, basta ascoltarli
  /censys/i, /shodan/i, /internetmeasurement/i, /masscan/i, /zgrab/i, /nuclei/i,
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

// Reti di hosting, cloud e scanner. Una richiesta che arriva da qui non e' una
// persona che naviga, qualunque browser dichiari lo user-agent: gli scraper
// copiano la stringa di Chrome o di Safari, e i piu' accurati scaricano anche
// immagini e font, quindi il solo user-agent non li distingue. Cloudflare passa
// ASN e organizzazione a ogni richiesta: e' il segnale piu' onesto disponibile.
// NB: AS13335 (Cloudflare) marca anche i pochi utenti WARP, che sono persone
// vere. E' un prezzo accettabile per non contare Worker e proxy come visite.
const DATACENTER_ASNS = new Set([
  132203, 45090, 132892, 13335,   // Tencent Singapore/Cina, Cloudflare
  396982, 15169, 19527, 139070,   // Google Cloud e infrastruttura Google
                                  // (Google Fiber, AS16591, e' un ISP: escluso apposta)
  16509, 14618,                   // Amazon
  8075,                           // Microsoft Azure
  31898,                          // Oracle Cloud
  37963, 45102, 45104,            // Aliyun
  24940,                          // Hetzner
  14061,                          // DigitalOcean
  16276,                          // OVH
  32613, 60781, 30633,            // Leaseweb
  20473,                          // Vultr / Choopa
  51167,                          // Contabo
  12876,                          // Scaleway
  63949,                          // Akamai / Linode
  36183, 20940,                   // Akamai
  54113,                          // Fastly
  9009,                           // M247
  49505,                          // Selectel
  62240,                          // Clouvider
  135377,                         // UCloud
  8560,                           // IONOS
  26496,                          // GoDaddy
  18779,                          // EGIHosting
  39486, 203020,                  // HostRoyale
  19624,                          // Data Room
  219502,                         // rivenditore VPS senza nome commerciale
  205759,                         // Cyber-Security-SG (scansioni)
  398324, 398722,                 // Censys (scansioni)
  215125,                         // uscite Tor
  44477,                          // Stark Industries
  47583,                          // Hostinger
  51747, 42708,                   // Internetbolaget / Internet Vikings
  43180, 62874, 48090,            // rivenditori VPS vari
]);

// I rivenditori piccoli cambiano ASN in fretta: il nome della rete prende
// quelli non elencati sopra. I confini di parola servono a non catturare gli
// operatori consumer (p.es. "Infrastructure for Fastwebs main location" non
// deve finire dentro per via di "Fastly").
const DATACENTER_ORG = /\b(hosting|hostroyale|host royale|servers?|dedicated|colocation|colo|data ?cent(?:er|re)|datacent|cloud|vps|leaseweb|hetzner|ovh|digital ?ocean|linode|vultr|contabo|scaleway|choopa|m247|aliyun|alibaba|tencent|amazon|azure|akamai|fastly|cloudflare|censys|shodan|internetmeasurement|masscan|zgrab|tor exit|proxy|palo ?alto|meta platforms|collyer quay|pte\.? ?ltd|aceville)\b/i;

function isDatacenter(asn, asOrg) {
  if (asn && DATACENTER_ASNS.has(asn)) return true;
  return !!asOrg && DATACENTER_ORG.test(asOrg);
}

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

// Dedupe solo per IP (non per pagina): una persona che naviga piu' pagine
// nella stessa giornata conta come 1 sola visita.
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
    await db.prepare(
      `INSERT INTO site_visits (ip, user_agent, country, is_bot, is_dc, asn, as_org, browser_confirmed, page_count, first_seen, last_seen)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)`
    ).bind(ip, user_agent, country, is_bot, is_dc, asn, as_org, browser_confirmed, now, now).run();
  }
}

// Marca la visita in corso come "browser confermato" quando dallo stesso IP
// arriva anche una richiesta di immagini o font. Non tocca il conteggio delle
// visite: e' un indizio in piu'. Da solo non basta a distinguere una persona —
// gli scraper accurati scaricano anche le immagini — per questo il filtro vero
// e' la rete di provenienza (is_dc).
// Una sola UPDATE, senza SELECT: se la visita e' gia' confermata non scrive.
async function confirmBrowser(db, ip) {
  const windowStart = Date.now() - VISIT_WINDOW_MS;
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
      const ip = getIP(request);
      if (isExcluded(ip, env)) return response;

      const isAsset = ASSET_EXTENSIONS.test(url.pathname);

      if (isAsset) {
        if (RENDER_ASSETS.test(url.pathname)) {
          waitUntil(confirmBrowser(env.DB, ip));
        }
        return response;
      }

      const user_agent = request.headers.get("user-agent") || "";
      const country = getCountry(request);
      const asn = getASN(request);
      const as_org = getASOrg(request);
      const ua_bot = isBot(user_agent) ? 1 : 0;
      const dc = isDatacenter(asn, as_org) ? 1 : 0;
      const isPage = !NON_PAGE_EXTENSIONS.test(url.pathname);

      waitUntil(logPageView(env.DB, {
        ip, user_agent, path: url.pathname, country,
        is_bot: ua_bot || !isPage ? 1 : 0,
        is_dc: dc,
        asn, as_org,
      }));

      // Scaricare un APK o controllare il repository F-Droid non e' una visita
      // al sito: non apre (ne' prolunga) una sessione.
      if (isPage) {
        waitUntil(logVisit(env.DB, {
          ip, user_agent, country, is_bot: ua_bot, is_dc: dc, asn, as_org,
          browser_confirmed: looksLikeBrowserRequest(request) ? 1 : 0,
        }));
      }
    }
  } catch (err) {
    console.error("page_views tracking error:", err.message);
  }

  return response;
}
