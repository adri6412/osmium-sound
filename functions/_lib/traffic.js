// Traffic classification shared by the website (Pages Functions) and the
// file.osmiumsound.it worker (osmium-iso-tracker/src/traffic.js).
//
// KEEP THE TWO COPIES BYTE-FOR-BYTE IDENTICAL: downloads and site visits must
// be judged by the same rules. `diff` the two files after every change.
//
// The approach follows Umami and Plausible: a request is dropped from the
// numbers when the user-agent admits to being a program, when it comes from a
// hosting/cloud network (scrapers copy Chrome's user-agent but cannot hide
// their ASN), or when the browser itself reports automation. Rows are stored
// with a reason instead of being deleted, so the dashboard can show what was
// filtered out and why.

export const BOT_PATTERNS = [
  /bot/i, /crawl/i, /spider/i, /scrap/i, /wget/i, /curl/i,
  /python-requests/i, /httpclient/i, /go-http-client/i, /java\//i,
  /libwww/i, /httpx/i, /okhttp/i, /aria2/i, /axios/i,
  /urllib/i, /guzzle/i, /fasthttp/i,
  // Social link previews: none of these say "bot"
  /facebookexternalhit/i, /meta-externalagent/i, /facebookcatalog/i,
  /whatsapp/i, /skypeuripreview/i, /embedly/i, /iframely/i, /vkshare/i,
  // Automated clients and infrastructure
  /headless/i, /node-fetch/i, /dart\//i, /deno\//i, /lighthouse/i,
  /prefetch proxy/i, /^hello from/i, /paloalto/i, /f-droid/i,
  /crusader/i, /worker\//i, /probe/i,
  // Network scanners announce themselves
  /censys/i, /shodan/i, /internetmeasurement/i, /masscan/i, /zgrab/i, /nuclei/i,
  // Crawlers, AI fetchers, SEO and uptime tools without "bot" in the name
  // (subset of the isbot / Matomo device-detector lists Umami and Plausible use)
  /anthropic-ai/i, /cohere-ai/i, /perplexity/i, /diffbot/i, /ahrefs/i,
  /semrush/i, /mj12/i, /dataforseo/i, /yandex/i, /baiduspider/i, /sogou/i,
  /ia_archiver/i, /archive\.org/i, /mediapartners/i, /google-inspectiontool/i,
  /googleother/i, /google-extended/i, /feedfetcher/i, /slurp/i, /bingpreview/i,
  /owler/i, /netcraft/i, /leakix/i, /expanse/i, /nmap/i, /nikto/i, /sqlmap/i,
  /wpscan/i, /gobuster/i, /dirbuster/i, /ffuf/i, /httpie/i, /postman/i,
  /insomnia/i, /powershell/i, /winhttp/i, /scrapy/i, /gtmetrix/i, /pingdom/i,
  /uptime/i, /statuscake/i, /site24x7/i, /monitor/i, /checker/i, /validator/i,
  /reqwest/i, /aiohttp/i, /python\//i, /perl\//i, /ruby/i, /php\//i,
  /^mozilla\/\d\.\d$/i,
  // Rotating-proxy scrapers stamp the exit address into the user-agent
  /\[ip:/i,
];

// Hosting, cloud and scanner networks. A request from here is a machine, no
// matter which browser the user-agent claims. Cloudflare passes ASN and
// organisation with every request: the most honest signal available.
// AS13335 (Cloudflare) also covers the few WARP users, an accepted loss.
export const DATACENTER_ASNS = new Set([
  132203, 45090, 132892, 13335,   // Tencent Singapore/China, Cloudflare
  396982, 15169, 19527, 139070,   // Google Cloud and Google infrastructure
                                  // (Google Fiber, AS16591, is an ISP: left out on purpose)
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
  219502,                         // unnamed VPS reseller
  205759,                         // Cyber-Security-SG (scanning)
  398324, 398722,                 // Censys (scanning)
  215125,                         // Tor exits
  44477,                          // Stark Industries
  47583,                          // Hostinger
  51747, 42708,                   // Internetbolaget / Internet Vikings
  43180, 62874, 48090,            // assorted VPS resellers
  // Seen in the site logs in September 2026 with browser user-agents,
  // one or two IPs each walking /.env, /wp-login.php and friends
  150303,                         // SoloRDP
  401626,                         // Felcloud
  197170,                         // TechTies
  208137,                         // Feo Prest (VPS)
  197540,                         // netcup
  53667,                          // FranTech / BuyVM
  60404,                          // The Infrastructure Group
  212238,                         // Datacamp / CDN77
  36352,                          // HostPapa
  26347,                          // DreamHost
  136787,                         // PacketHub (VPN exits)
  209709,                         // code200 (proxy network)
]);

// Small resellers change ASN quickly: the network name catches the ones not
// listed above. Word boundaries keep consumer carriers out (for example
// "Infrastructure for Fastwebs main location" must not match "Fastly").
export const DATACENTER_ORG = /\b(hosting|hostroyale|host royale|servers?|dedicated|colocation|colo|data ?cent(?:er|re)|datacent|cloud|vps|rdp|leaseweb|hetzner|ovh|digital ?ocean|linode|vultr|contabo|scaleway|choopa|m247|aliyun|alibaba|tencent|amazon|azure|akamai|fastly|cloudflare|censys|shodan|internetmeasurement|masscan|zgrab|tor exit|proxy|palo ?alto|meta platforms|collyer quay|pte\.? ?ltd|aceville|netcup|hostpapa|dreamhost|frantech|datacamp|packethub|cdn77|zenlayer)\b/i;

// Paths only vulnerability scanners ask for. The site answers 200 to unknown
// paths, so without this they would count as page views.
export const PROBE_PATHS = /(^|\/)(\.env|\.git|\.aws|\.ssh|\.vscode|\.DS_Store|wp-|wordpress|xmlrpc|phpmyadmin|phpinfo|actuator|cgi-bin|vendor\/|admin\/|config\.|backup|\.well-known\/(?!traffic-advice))|\.(php|asp|aspx|jsp|cgi|sql|bak|old|ya?ml|ini|log|sh)$/i;

export function isDatacenter(asn, asOrg) {
  if (asn && DATACENTER_ASNS.has(asn)) return true;
  return !!asOrg && DATACENTER_ORG.test(asOrg);
}

// Some scrapers pose as a browser but get the fixed formula wrong: every real
// browser that says AppleWebKit also says "(KHTML, like Gecko)".
export function hasForgedBrowserUA(userAgent) {
  return /applewebkit/i.test(userAgent) && !/khtml, like gecko/i.test(userAgent);
}

// Desktop Chrome and Firefox update themselves every four weeks. A version
// years behind is almost always a scraper with a hard-coded user-agent (the
// logs are full of "Chrome/91.0.4472.124" in 2026). The expected version is
// derived from the date so the rule does not need yearly edits; the margins
// are wide enough for Firefox ESR and stale corporate installs.
const CHROME_120 = Date.UTC(2023, 11, 5);
const FIREFOX_120 = Date.UTC(2023, 10, 21);
const RELEASE_MS = 28 * 24 * 60 * 60 * 1000;

export function isOutdatedBrowser(userAgent, now = Date.now()) {
  // Internet Explorer has been dead for years: only scripts still claim it
  if (/msie [1-9]\.|msie 10\./i.test(userAgent)) return true;
  // Android WebViews and embedded browsers lag behind legitimately
  if (/; wv\)|android [0-7]\b/i.test(userAgent)) return false;
  let m = userAgent.match(/(?:chrome|crios)\/(\d+)/i);
  if (m && !/edg|opr|samsungbrowser|yabrowser|electron/i.test(userAgent)) {
    const expected = 120 + Math.floor((now - CHROME_120) / RELEASE_MS);
    return Number(m[1]) < expected - 36;
  }
  m = userAgent.match(/firefox\/(\d+)/i);
  if (m) {
    const expected = 120 + Math.floor((now - FIREFOX_120) / RELEASE_MS);
    return Number(m[1]) < expected - 48;
  }
  return false;
}

export function isBot(userAgent) {
  if (!userAgent) return true;
  if (hasForgedBrowserUA(userAgent)) return true;
  if (isOutdatedBrowser(userAgent)) return true;
  return BOT_PATTERNS.some((p) => p.test(userAgent));
}

// Why a request does not count as a person, or null when it does.
// Order matters only for the label shown: the first matching reason wins.
export function classify({ userAgent, asn, asOrg }) {
  if (!userAgent) return "ua_bot";
  if (hasForgedBrowserUA(userAgent)) return "ua_forged";
  if (BOT_PATTERNS.some((p) => p.test(userAgent))) return "ua_bot";
  if (isOutdatedBrowser(userAgent)) return "ua_old";
  if (isDatacenter(asn, asOrg)) return "datacenter";
  return null;
}

// Minimal user-agent parser, enough for browser / OS / device breakdowns.
export function parseUA(ua = "", screenWidth = 0) {
  let browser = "Altro";
  // Our own clients: the flasher downloads through Node's fetch, the
  // appliance announces itself
  if (/^node$/i.test(ua)) browser = "Osmium Flasher";
  else if (/^osmiumsound/i.test(ua)) browser = "Apparecchio Osmium";
  else if (/edg(?:e|a|ios)?\//i.test(ua)) browser = "Edge";
  else if (/opr\/|opera/i.test(ua)) browser = "Opera";
  else if (/samsungbrowser/i.test(ua)) browser = "Samsung Internet";
  else if (/yabrowser/i.test(ua)) browser = "Yandex";
  else if (/vivaldi/i.test(ua)) browser = "Vivaldi";
  else if (/electron/i.test(ua)) browser = "Electron";
  else if (/firefox|fxios/i.test(ua)) browser = "Firefox";
  else if (/chrome|crios|chromium/i.test(ua)) browser = "Chrome";
  else if (/safari/i.test(ua) && /version\//i.test(ua)) browser = "Safari";
  else if (/curl|wget|python|go-http|java|okhttp|aria2|urllib/i.test(ua)) browser = "Programma";

  let os = "Altro";
  if (/windows/i.test(ua)) os = "Windows";
  else if (/android/i.test(ua)) os = "Android";
  else if (/iphone|ipad|ipod/i.test(ua)) os = "iOS";
  else if (/cros/i.test(ua)) os = "ChromeOS";
  else if (/mac os x|macintosh/i.test(ua)) os = "macOS";
  else if (/linux|x11/i.test(ua)) os = "Linux";

  let device;
  if (screenWidth > 0) {
    device = screenWidth < 576 ? "Telefono" : screenWidth < 992 ? "Tablet" : "Computer";
  } else if (/ipad|tablet/i.test(ua) || (/android/i.test(ua) && !/mobile/i.test(ua))) {
    device = "Tablet";
  } else if (/mobi|iphone/i.test(ua)) {
    device = "Telefono";
  } else {
    device = "Computer";
  }
  return { browser, os, device };
}
