/* Osmium Sound — cookieless visit counter, modelled on the Plausible and
   Umami trackers. Sends to /api/o (functions/api/o.js):
   - pageview when the page is shown (prerendered pages wait until visible)
   - download clicks on file links (ISO, flasher, APK); pages can also call
              window.osmiumTrack('download', url) for downloads they start
   Two numbers come out of it, unique visitors and downloads, and nothing is
   kept per visitor on the server: counts per day and a sketch that cannot be
   read back. That is why this script sends so little — no screen size, no
   language, no time on page, no path through the site.
   No cookies, no storage, no fingerprinting. To stop counting yourself, run
   localStorage.setItem('osmium_ignore', '1') in this browser's console. */
(function () {
  'use strict';

  var ENDPOINT = '/api/o';
  var FILE_LINK = /\.(iso|img|zip|exe|run|apk|dmg|appimage|deb|rpm|gz|xz|7z|pdf)$/i;
  var FILE_HOSTS = /^file\.osmiumsound\.it$/i;

  if (location.protocol === 'file:' ||
      /^localhost$|^127(\.\d+){3}$|^\[::1?\]$/.test(location.hostname)) return;
  try { if (localStorage.getItem('osmium_ignore') === '1') return; } catch (e) { /* storage blocked */ }

  // Selenium, Puppeteer, Playwright, PhantomJS, Nightmare and Cypress all set
  // one of these. The visit is still sent, flagged, so it can be counted among
  // the ones filtered out instead of disappearing.
  var automated = !!(navigator.webdriver || window._phantom || window.callPhantom ||
                     window.__nightmare || window.Cypress);

  var started = false;

  function send(payload) {
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(ENDPOINT, body)) return;
    } catch (e) { /* fall back to fetch */ }
    try {
      fetch(ENDPOINT, { method: 'POST', body: body, keepalive: true, credentials: 'omit' });
    } catch (e) { /* offline or blocked: nothing to do */ }
  }

  function pageview() {
    if (started) return;
    started = true;
    send({
      n: 'pageview',
      u: location.pathname + location.search,
      r: document.referrer || null,
      a: automated ? 1 : 0
    });
  }

  function trackGoal(name, url) {
    if (!started || name !== 'download') return;
    var href;
    try { href = new URL(url, location.href).href; } catch (e) { return; }
    send({ n: 'download', t: href });
  }
  window.osmiumTrack = trackGoal;

  function onLinkClick(e) {
    if (e.type === 'auxclick' && e.button !== 1) return;
    // A handler that took over the click (the download popup) reports on its own
    if (e.defaultPrevented) return;
    var a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!a) return;
    var url;
    try { url = new URL(a.href, location.href); } catch (err) { return; }
    if (!/^https?:$/.test(url.protocol)) return;
    if (FILE_HOSTS.test(url.hostname) || FILE_LINK.test(url.pathname)) {
      trackGoal('download', url.href);
    }
  }

  document.addEventListener('click', onLinkClick);
  document.addEventListener('auxclick', onLinkClick);

  if (document.visibilityState === 'prerender') {
    document.addEventListener('visibilitychange', function wait() {
      if (document.visibilityState === 'visible') {
        document.removeEventListener('visibilitychange', wait);
        pageview();
      }
    });
  } else {
    pageview();
  }
})();
