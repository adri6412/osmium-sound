// Cloudflare Pages Function — HTTP Basic Auth gate for /beta/*
//
// Credentials are read from the Cloudflare Pages project's environment
// variables (Settings → Environment variables), NOT hardcoded here:
//   BETA_USER
//   BETA_PASSWORD
// Set them as "Secret" values for both Production and Preview environments,
// then redeploy (or retrigger via workflow_dispatch on deploy-pages.yml).

// La beta è finita (2026-08-28): l'indice di /beta rimanda al sito pubblico,
// e lo fa QUI, prima della password — altrimenti chi arriva da un vecchio
// link o QR vede solo la richiesta di credenziali e non il rimando.
// beta/index.html fa la stessa cosa lato browser, come riserva. Il resto
// della cartella (manuale, privacy, immagini) resta protetto com'era.
const PUBLIC_SITE = 'https://osmiumsound.it/';
const RETIRED_PATHS = new Set(['/beta', '/beta/', '/beta/index.html']);

export async function onRequest(context) {
  const { request, env } = context;
  const { BETA_USER, BETA_PASSWORD } = env;

  if (RETIRED_PATHS.has(new URL(request.url).pathname)) {
    return Response.redirect(PUBLIC_SITE, 302);
  }

  if (!BETA_USER || !BETA_PASSWORD) {
    return new Response('Beta auth is not configured (missing BETA_USER/BETA_PASSWORD).', { status: 500 });
  }

  const authHeader = request.headers.get('Authorization') || '';
  const [scheme, encoded] = authHeader.split(' ');

  if (scheme === 'Basic' && encoded) {
    let decoded = '';
    try {
      decoded = atob(encoded);
    } catch {
      decoded = '';
    }
    const sep = decoded.indexOf(':');
    const user = sep === -1 ? decoded : decoded.slice(0, sep);
    const pass = sep === -1 ? '' : decoded.slice(sep + 1);

    if (user === BETA_USER && pass === BETA_PASSWORD) {
      return context.next();
    }
  }

  return new Response('Authentication required.', {
    status: 401,
    headers: {
      'WWW-Authenticate': 'Basic realm="Osmium Sound Beta", charset="UTF-8"',
    },
  });
}
