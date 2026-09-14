/* Osmium Sound — cookieless visit counter, modelled on the Plausible and
   Umami trackers. Sends to /api/o (functions/api/o.js):
   - pageview   when the page is shown (prerendered pages wait until visible)
   - engagement when the page is hidden or loses focus: visible time since the
                last report, deepest scroll in percent, whether the visitor
                clicked, typed or touched anything
   - download   clicks on file links (ISO, flasher, APK); pages can also call
                window.osmiumTrack('download', url) for downloads they start
   - outbound   clicks on links to other sites
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
  // one of these. The visit is still sent, flagged, so the dashboard can show
  // how many were filtered.
  var automated = !!(navigator.webdriver || window._phantom || window.callPhantom ||
                     window.__nightmare || window.Cypress);

  var pageId = Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
  var visibleSince = 0;      // when the page last became visible and focused
  var engagedMs = 0;         // visible time not yet reported
  var maxScroll = 0;         // deepest scroll, percent of the document
  var reportedScroll = -1;
  var interacted = false;
  var started = false;

  function send(payload) {
    payload.p = pageId;
    var body = JSON.stringify(payload);
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(ENDPOINT, body)) return;
    } catch (e) { /* fall back to fetch */ }
    try {
      fetch(ENDPOINT, { method: 'POST', body: body, keepalive: true, credentials: 'omit' });
    } catch (e) { /* offline or blocked: nothing to do */ }
  }

  function docHeight() {
    var b = document.body || {}, d = document.documentElement || {};
    return Math.max(b.scrollHeight || 0, b.offsetHeight || 0, d.scrollHeight || 0, d.offsetHeight || 0, 1);
  }

  function updateScroll() {
    var bottom = (window.scrollY || window.pageYOffset || 0) + (window.innerHeight || 0);
    var pct = Math.min(100, Math.round(bottom / docHeight() * 100));
    if (pct > maxScroll) maxScroll = pct;
  }

  function isActive() {
    return document.visibilityState === 'visible' && document.hasFocus();
  }

  function flushEngagement() {
    if (!started) return;
    if (visibleSince) {
      engagedMs += Date.now() - visibleSince;
      visibleSince = 0;
    }
    // Like Plausible: only report when something new happened
    if (engagedMs >= 3000 || maxScroll > reportedScroll) {
      send({ n: 'engagement', e: engagedMs, s: maxScroll, i: interacted ? 1 : 0 });
      reportedScroll = maxScroll;
      engagedMs = 0;
    }
  }

  function onVisibility() {
    if (isActive()) {
      if (!visibleSince) visibleSince = Date.now();
    } else {
      flushEngagement();
    }
  }

  function pageview() {
    if (started) return;
    started = true;
    updateScroll();
    reportedScroll = -1;
    send({
      n: 'pageview',
      u: location.pathname + location.search,
      r: document.referrer || null,
      w: (window.screen && screen.width) || 0,
      l: navigator.language || '',
      a: automated ? 1 : 0
    });
    if (isActive()) visibleSince = Date.now();
  }

  function trackGoal(name, url) {
    if (!started || (name !== 'download' && name !== 'outbound')) return;
    var href;
    try { href = new URL(url, location.href).href; } catch (e) { return; }
    interacted = true;
    send({ n: name, u: location.pathname, t: href });
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
    } else if (url.hostname !== location.hostname) {
      trackGoal('outbound', url.href);
    }
  }

  function markInteraction() { interacted = true; }

  document.addEventListener('click', onLinkClick);
  document.addEventListener('auxclick', onLinkClick);
  ['pointerdown', 'keydown', 'touchstart', 'wheel'].forEach(function (type) {
    document.addEventListener(type, markInteraction, { passive: true, capture: true });
  });
  document.addEventListener('scroll', updateScroll, { passive: true });
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('focus', onVisibility);
  window.addEventListener('blur', onVisibility);
  window.addEventListener('pagehide', flushEngagement);

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
