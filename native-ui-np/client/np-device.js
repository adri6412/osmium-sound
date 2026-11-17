// Osmium — "Now Playing only" web build: the only bridge the Qt/WASM page needs
// from the host page. Unlike the public demo (client/device.js, which mocks the
// three backend services in the browser), this build is served by the appliance
// itself and the Qt code reaches the real services over the network, same-origin
// (/device/api, /device/src, /device/lms — reverse-proxied by webui_server.py).
// So there is no request mocking here. All this provides is:
//   * vuLevels() — the live VU needle levels, read off the device's DAC through
//     the /device/vu/stream SSE bridge (webui_server ↔ vu_meter_daemon on :9001),
//   * lang()/setLang() — the interface language, as the loader page reads it.
(function () {
  'use strict';

  // Last VU frame as [peakLeft, peakRight] on the 0..100 scale the daemon sends,
  // the same quantity the appliance's own vumeter.cpp takes (maxArray(levels_*)).
  var peak = [0, 0];
  function maxArr(a) {
    var m = 0;
    if (a) for (var i = 0; i < a.length; i++) if (a[i] > m) m = a[i];
    return m;
  }

  function openVu() {
    var es;
    try {
      es = new EventSource('/device/vu/stream');
    } catch (e) {
      return;   // no EventSource (very old browser): the needle just stays at 0
    }
    es.onmessage = function (ev) {
      try {
        var f = JSON.parse(ev.data);
        peak = [maxArr(f.levels_l), maxArr(f.levels_r)];
      } catch (e) { /* ignore a malformed frame */ }
    };
    // EventSource reconnects by itself after a dropped connection; on an error
    // frame drop the needle back to rest in the meantime.
    es.onerror = function () { peak = [0, 0]; };
  }
  openVu();

  var lang;
  try { lang = localStorage.getItem('osmium-lang'); } catch (e) { /* private mode */ }
  if (lang !== 'it' && lang !== 'en')
    lang = (navigator.language || 'en').slice(0, 2) === 'it' ? 'it' : 'en';

  window.osmiumDevice = {
    vuLevels: function () { return peak; },
    lang: function () { return lang; },
    setLang: function (l) {
      lang = l === 'it' ? 'it' : 'en';
      try { localStorage.setItem('osmium-lang', lang); } catch (e) { /* ignore */ }
    },
  };
})();
