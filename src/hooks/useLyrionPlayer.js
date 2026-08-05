import { useState, useEffect, useRef } from 'react';
import { lyrionApi } from '../utils/lyrionApi';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';

// ── Safe image URLs ───────────────────────────────────────────
// Artwork/icon URLs come from the (untrusted) Lyrion server. Only allow
// http(s) absolute or same-origin relative URLs as <img src>; reject
// javascript:, data: and other schemes that can lead to DOM-based XSS.
export const safeUrl = (url) => {
  if (typeof url !== 'string') return '';
  const raw = url.trim();
  if (!raw) return '';
  // Same-origin relative path (e.g. "/music/123/cover"): rebuild it from the
  // parsed URL so no scheme/host/meta-characters can ride along.
  if (raw[0] === '/' && raw[1] !== '/') {
    try { const u = new URL(raw, 'http://localhost'); return encodeURI(u.pathname + u.search); }
    catch { return ''; }
  }
  // Absolute URL: allow ONLY http/https (blocks javascript:/data:/…) and return
  // the parser's serialized href — a freshly built, well-formed string rather
  // than the raw input. encodeURI() escapes any residual HTML meta-characters
  // (< > ") while keeping the URL valid, so nothing unescaped flows through to
  // <img src> (and it's a sanitizer the static analyser recognises).
  try {
    const u = new URL(raw);
    return (u.protocol === 'http:' || u.protocol === 'https:') ? encodeURI(u.href) : '';
  } catch { return ''; }
};

export const formatTime = (s) => {
  if (!s || isNaN(s)) return '0:00';
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
};

// How many library rows/cards to mount initially and add per scroll step. The
// full result set is kept in state (search/counts stay correct); we just grow
// the rendered slice as the user scrolls, so a 5000-album grid never tries to
// mount 5000 nodes at once on the mini-PC.
export const LIST_PAGE = 120;

// Presentation-agnostic LMS/Lyrion control layer: connection, now-playing
// state, queue, library navigation. No JSX — both the kiosk (LyrionServer.jsx)
// and the PWA screens (src/pages/pwa/) consume this so there is exactly one
// place that talks to lyrionApi and tracks playback/browse state.
export function useLyrionPlayer() {
  const { t } = useI18n();
  const [serverUrl, setServerUrl] = useState(localStorage.getItem('lyrionUrl') || 'http://localhost:9000');

  // Connection state
  const [isConnected, setIsConnected] = useState(false);
  const [activePlayer, setActivePlayer] = useState(null);
  const [playerStatus, setPlayerStatus] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // Queue state
  const [queue, setQueue] = useState([]);
  const [queueIndex, setQueueIndex] = useState(0);

  // Library navigation state
  const [currentView, setCurrentView] = useState('home');
  const [libraryData, setLibraryData] = useState([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  // How many of libraryData to actually render (progressive rendering, grows on
  // scroll). Reset back to the first page whenever the list contents change.
  const [visibleCount, setVisibleCount] = useState(LIST_PAGE);
  const [navigationStack, setNavigationStack] = useState([{ view: 'home', title: t('player.titles.home'), params: null }]);
  // Search prompt for Lyrion menu items that require text input (e.g. TuneIn / global search)
  const [menuSearch, setMenuSearch] = useState(null); // { action, title }
  const [searchText, setSearchText] = useState('');
  // `base` object from the last Lyrion menu response (Jive base+item action model)
  const menuBaseRef = useRef(null);

  // ── Server connection ──────────────────────────────────────
  // Delayed 10s on first mount to give the appliance's own Lyrion server
  // (or, if this device already follows another Osmium unit for multiroom,
  // that device's server) time to finish starting up during boot.
  useEffect(() => {
    lyrionApi.setBaseUrl(serverUrl);
    const timer = setTimeout(connectToServer, 10000);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // `lyrionApi` is a shared singleton (utils/lyrionApi.js) — Settings.jsx can
  // repoint it live to a different Lyrion server (multiroom "follow another
  // device") while this page stays mounted for the app's entire lifetime.
  // Without this listener, activePlayer/playerStatus polling below would
  // keep silently querying the OLD server's now-stale playerid forever (the
  // symptom: progress bar/VU meter go dead on the follower and never
  // recover). Settings.jsx's applyLmsRole dispatches this event right after
  // it repoints lyrionApi's own baseUrl.
  useEffect(() => {
    const onUrlChanged = (e) => {
      const url = e.detail;
      if (!url) return;
      setServerUrl(url);
      setActivePlayer(null);
      setPlayerStatus(null);
      lyrionApi.setBaseUrl(url);
      connectToServer();
    };
    window.addEventListener('osmium:lyrion-url-changed', onUrlChanged);
    return () => window.removeEventListener('osmium:lyrion-url-changed', onUrlChanged);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connectToServer = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const ss = await lyrionApi.getServerStatus();
      setIsConnected(true);
      const avail = ss?.players_loop || [];
      if (avail.length > 0) {
        // `players_loop` isn't necessarily "this appliance first": the companion
        // app auto-launches Squeezelite/SqueezePlayer on the phone as a second
        // LMS player (radios/apps browsing is capability-filtered per-player, so
        // landing on that one leaves tabs like Radio empty). Prefer the player
        // matching this device's own squeezelite name (-n, from the Flask API)
        // over just taking the first entry in the list.
        const nameRes = await systemAPI.getPlayerName().catch(() => null);
        const localName = nameRes?.success ? nameRes.data?.name : null;
        const local = localName && avail.find(x => x.name === localName);
        setActivePlayer(p => (p && avail.find(x => x.playerid === p.playerid)) ? p : (local || avail[0]));
      }
      else { setActivePlayer(null); setPlayerStatus(null); }
    } catch (_) {
      setIsConnected(false);
      setError(t('player.connectError'));
    } finally {
      setIsLoading(false);
    }
  };

  // The one dead-end in this hook's recovery story: the bad-poll self-heal
  // below only runs while an activePlayer is set. If connectToServer() lands
  // in the exact window where the local squeezelite is disconnected from LMS
  // (it bounces whenever DSP toggles on/off — that's a systemctl restart),
  // players_loop comes back empty, activePlayer is nulled, and from then on
  // NOTHING retried: the status poll early-returns, the fail counter never
  // moves, and the kiosk sat dead until a manual reload. Close the loop by
  // retrying the connect itself for as long as we have no player.
  useEffect(() => {
    if (activePlayer || isLoading) return;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') connectToServer();
    }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlayer, isLoading]);

  // connectToServer() only ever resolves activePlayer once (10s after mount,
  // or on a multiroom server-URL change) — there was no path back if the
  // squeezelite process behind it ever bounced (e.g. Settings → DSP restarts
  // it to redirect through the loopback). The kiosk would then poll a player
  // that never again reports a valid status, staying "stuck" until the whole
  // UI was reloaded. Recover automatically instead: after a few consecutive
  // bad polls, re-run connectToServer() to re-resolve everything from scratch.
  const statusFailCountRef = useRef(0);
  // Volume drags fire many onChange ticks in quick succession, each kicking
  // off its own optimistic update + setVolume request + status refetch. Those
  // refetches can resolve out of order (or the periodic poll below can land
  // mid-drag), and a plain setPlayerStatus(st) would stomp the just-set
  // optimistic mixer_volume with a stale snapshot — the slider visibly snaps
  // back even though the server did receive the right value. Guard by
  // preserving the locally-set volume for a short window after the user's
  // last change, giving in-flight requests time to actually land server-side.
  const lastVolumeChangeRef = useRef(0);
  const VOLUME_GUARD_MS = 1200;
  const fetchStatus = async () => {
    if (!activePlayer) return;
    try {
      const st = await lyrionApi.getPlayerStatus(activePlayer.playerid);
      if (st && typeof st === 'object' && 'mode' in st) {
        statusFailCountRef.current = 0;
        if (Date.now() - lastVolumeChangeRef.current < VOLUME_GUARD_MS) {
          setPlayerStatus(prev => ({ ...st, mixer_volume: prev?.mixer_volume ?? st.mixer_volume }));
        } else {
          setPlayerStatus(st);
        }
        return;
      }
    } catch (_) { /* fall through to failure counting below */ }
    if (++statusFailCountRef.current >= 3) {
      statusFailCountRef.current = 0;
      connectToServer();
    }
  };

  // Poll the player status, but adaptively:
  //  • 1s while playing (so the progress bar / time stay smooth);
  //  • 5s when paused/stopped (nothing is moving — cut idle CPU & server load);
  //  • not at all while the window is hidden (re-syncs immediately on return).
  // The effect re-runs only when playback actually starts/stops (isPlaying
  // flips), not on every poll, so the cadence switches without churn.
  const playing = playerStatus?.mode === 'play';
  useEffect(() => {
    if (!activePlayer) return;
    fetchStatus();
    const period = playing ? 1000 : 5000;
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') fetchStatus();
    }, period);
    const onVisible = () => { if (document.visibilityState === 'visible') fetchStatus(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePlayer, playing]);

  // New list contents (navigated to a different view / went back) → render from
  // the top again. Consumers with a scroll container reset it via this ref.
  const listScrollRef = useRef(null);
  useEffect(() => {
    setVisibleCount(LIST_PAGE);
    if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
  }, [libraryData]);

  // Grow the rendered slice as the user nears the bottom of the list.
  const handleLibraryScroll = (e) => {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 400) {
      setVisibleCount(c => (c < libraryData.length ? c + LIST_PAGE : c));
    }
  };

  const handleAction = async (fn) => {
    try { await fn(); fetchStatus(); } catch (_) {}
  };

  // ── Playback modes (shuffle / repeat) ──────────────────────
  // Optimistic update of the status fields (keys carry a space), like volume.
  const cycleShuffle = () => {
    if (!activePlayer) return;
    const next = (Number(playerStatus?.['playlist shuffle'] ?? 0) + 1) % 3;
    setPlayerStatus(prev => ({ ...prev, 'playlist shuffle': next }));
    handleAction(() => lyrionApi.setShuffle(activePlayer.playerid, next));
  };
  const cycleRepeat = () => {
    if (!activePlayer) return;
    const next = (Number(playerStatus?.['playlist repeat'] ?? 0) + 1) % 3;
    setPlayerStatus(prev => ({ ...prev, 'playlist repeat': next }));
    handleAction(() => lyrionApi.setRepeat(activePlayer.playerid, next));
  };

  const setVolume = (v) => {
    lastVolumeChangeRef.current = Date.now();
    setPlayerStatus(prev => ({ ...prev, mixer_volume: v }));
    handleAction(() => lyrionApi.setVolume(activePlayer?.playerid, v));
  };
  const toggleMute = () => setVolume(volume === 0 ? 50 : 0);

  const seek = (fraction) => {
    if (!duration || !activePlayer) return;
    handleAction(() => lyrionApi.seek(activePlayer.playerid, duration * fraction));
  };

  // ── Play queue ─────────────────────────────────────────────
  const loadQueue = async () => {
    if (!activePlayer) return;
    try {
      const r = await lyrionApi.getQueue(activePlayer.playerid);
      setQueue(r?.playlist_loop || []);
      setQueueIndex(Number(r?.playlist_cur_index ?? 0));
    } catch (_) {}
  };
  const queueJump   = (i) => handleAction(() => lyrionApi.playlistJump(activePlayer.playerid, i)).then(loadQueue);
  const queueRemove = (i) => handleAction(() => lyrionApi.playlistRemove(activePlayer.playerid, i)).then(loadQueue);
  const queueMove   = (from, to) => {
    if (to < 0 || to >= queue.length) return;
    handleAction(() => lyrionApi.playlistMove(activePlayer.playerid, from, to)).then(loadQueue);
  };
  const queueClear  = () => handleAction(() => lyrionApi.playlistClear(activePlayer.playerid)).then(loadQueue);

  // Save the queue, verify Lyrion actually wrote it, then jump to the Playlists
  // view so the result is immediately visible. Returns { success, error } —
  // callers own any UI-local cleanup (closing dialogs, resetting tabs, etc.).
  const saveQueue = async (name) => {
    const trimmed = (name || '').trim();
    if (!trimmed || !activePlayer) return { success: false };
    try {
      const res = await lyrionApi.playlistSave(activePlayer.playerid, trimmed);
      if (res && (res.writeError || res.error)) {
        return { success: false, error: t('player.saveError') };
      }
      goHome();
      navigateTo('playlists', t('player.titles.playlists'));
      return { success: true };
    } catch (_) {
      return { success: false, error: t('player.saveError') };
    }
  };

  // ── Sleep timer ────────────────────────────────────────────
  const setSleepTimer = (minutes) => {
    if (!activePlayer) return;
    handleAction(() => lyrionApi.setSleep(activePlayer.playerid, minutes * 60));
  };

  // ── Library navigation ─────────────────────────────────────
  const fetchViewData = async (view, params) => {
    if (view === 'artists')      { const r = await lyrionApi.getArtists(); return r?.artists_loop || []; }
    if (view === 'albums')       { const r = await lyrionApi.getAlbums(9999, 0, params?.artistId); return r?.albums_loop || []; }
    if (view === 'tracks')       { const r = await lyrionApi.getTracks(9999, 0, params?.albumId); return r?.titles_loop || []; }
    if (view === 'folders')      { const r = await lyrionApi.getMusicFolders(params?.folderId); return r?.folder_loop || []; }
    if (view === 'playlists')    { const r = await lyrionApi.getPlaylists(); return r?.playlists_loop || []; }
    if (view === 'playlist_tracks') { const r = await lyrionApi.getPlaylistTracks(params?.playlistId); return r?.playlisttracks_loop || []; }
    // LMS's `radios` command replies under "radioss_loop" (double s, an
    // upstream quirk) rather than "radios_loop" — same story as appss_loop below.
    if (view === 'radios')       { const r = await lyrionApi.getRadios(activePlayer?.playerid); return r?.radioss_loop || r?.radios_loop || []; }
    if (view === 'apps')         { const r = await lyrionApi.getApps(activePlayer?.playerid); return r?.appss_loop || r?.apps_loop || []; }
    if (view === 'menu_home') {
      // The full Lyrion home menu, filtered to the top-level "app"-like entries
      // (Applicazioni/Spotty, Preferiti, CD, YouTube, Suoni…). Local-library
      // browse modes live under the Musica tab; Radio has its own tab.
      const all = await lyrionApi.getHomeMenu(activePlayer?.playerid);
      menuBaseRef.current = null; // home items carry their own complete actions
      const EXCLUDE = new Set(['myMusic', 'radios', 'playerpower']);
      return all
        .filter(it => it.actions && (it.actions.go || it.actions.do || it.input)
          && ['home', '', 'extras'].includes(it.node)
          && !EXCLUDE.has(it.id))
        .sort((a, b) => (Number(a.weight) || 0) - (Number(b.weight) || 0));
    }
    if (view === 'menu') {
      const { items, base } = await lyrionApi.menuGo(activePlayer?.playerid, params.action, { input: params.input });
      menuBaseRef.current = base;
      return items;
    }
    if (view === 'plugin_items') {
      const r = await lyrionApi.getPluginItems(activePlayer?.playerid, params.pluginCmd, 9999, 0, params.itemId);
      // Radio/Apps plugin sub-menus (xmlbrowser "<cmd> items") reply under
      // "loop_loop" regardless of cmd — same LMS naming quirk as radioss_loop.
      return r?.loop_loop || r?.item_loop || r?.[`${params.pluginCmd}_loop`] || [];
    }
    return [];
  };

  const navigateTo = async (view, title, params = null) => {
    setLibraryLoading(true);
    try {
      const data = await fetchViewData(view, params);
      setNavigationStack(prev => [...prev, { view, title, params }]);
      setCurrentView(view);
      setLibraryData(data);
    } catch (err) { console.error(`Failed to load ${view}:`, err); }
    finally { setLibraryLoading(false); }
  };

  const goBack = async () => {
    if (navigationStack.length <= 1) return;
    const newStack = navigationStack.slice(0, -1);
    const prev = newStack[newStack.length - 1];
    setNavigationStack(newStack);
    setCurrentView(prev.view);
    if (prev.view === 'home') return;
    setLibraryLoading(true);
    try { setLibraryData(await fetchViewData(prev.view, prev.params)); } catch (_) {}
    finally { setLibraryLoading(false); }
  };

  const goToBreadcrumb = (idx) => {
    if (idx >= navigationStack.length - 1) return;
    const ns = navigationStack.slice(0, idx + 1);
    setNavigationStack(ns);
    const last = ns[ns.length - 1];
    setCurrentView(last.view);
    if (last.view !== 'home') navigateTo(last.view, last.title, last.params);
  };

  const goHome = () => {
    setMenuSearch(null);
    setNavigationStack([{ view: 'home', title: t('player.titles.home'), params: null }]);
    setCurrentView('home');
  };

  const handlePlayItem = (type, id) => {
    // Diagnostic: this used to bail out silently with no visible trace when
    // activePlayer was stale/null, which was indistinguishable in the logs
    // from "nothing was clicked". Log both branches so a failed Play attempt
    // always leaves a trace in renderer-console.log.
    if (!activePlayer) {
      console.warn('handlePlayItem: no activePlayer, ignoring', { type, id });
      return;
    }
    console.warn('handlePlayItem: sending playItem', { type, id, playerid: activePlayer.playerid });
    handleAction(() => lyrionApi.playItem(activePlayer.playerid, type, id));
  };

  // ── Generic Lyrion menu items (home menu / plugin nodes) ───
  const resolveMenuIcon = (item) => {
    const ic = item['icon-id'] || item.window?.['icon-id'] || item.icon || item.image;
    if (!ic) return null;
    return ic.startsWith('http') ? ic : `${serverUrl}/${ic.replace(/^\//, '')}`;
  };

  const handleMenuItem = (item) => {
    if (!activePlayer) return;
    const base = menuBaseRef.current;
    const go = lyrionApi.resolveMenuAction(base, item, 'go');
    const play = lyrionApi.resolveMenuAction(base, item, 'play');
    const doAct = lyrionApi.resolveMenuAction(base, item, 'do');
    if (item.input && go) {                 // needs text input → search prompt
      setSearchText('');
      setMenuSearch({ action: go, title: item.text || item.name || t('player.titles.search') });
    } else if (go) {                        // submenu (or play-on-go leaf) → drill in
      navigateTo('menu', item.text || item.name || '…', { action: go });
    } else if (play) {                      // playable leaf
      handleAction(() => lyrionApi.menuDo(activePlayer.playerid, play));
    } else if (doAct) {                     // toggle / settings action
      handleAction(() => lyrionApi.menuDo(activePlayer.playerid, doAct));
    }
  };

  const submitMenuSearch = () => {
    if (!menuSearch) return;
    const { action, title } = menuSearch;
    const q = searchText;
    setMenuSearch(null);
    setSearchText('');
    navigateTo('menu', title, { action, input: q });
  };

  // Loads the default view for a top-level tab (radio/apps get their own
  // library view; musica falls back home only if not already browsing music).
  const openTabView = async (tabId) => {
    setMenuSearch(null);
    if (tabId === 'radio' || tabId === 'apps') {
      const view = tabId === 'radio' ? 'radios' : 'menu_home';
      const title = tabId === 'radio' ? t('player.titles.radio') : t('player.titles.apps');
      setLibraryLoading(true);
      try {
        const data = await fetchViewData(view, null);
        setNavigationStack([
          { view: 'home', title: t('player.titles.home'), params: null },
          { view, title, params: null }
        ]);
        setCurrentView(view);
        setLibraryData(data);
      } catch (_) {}
      finally { setLibraryLoading(false); }
    } else if (tabId === 'musica') {
      if (!['artists', 'albums', 'tracks', 'folders', 'playlists', 'playlist_tracks', 'home'].includes(currentView)) {
        goHome();
      }
    }
  };

  // ── Derived player values ──────────────────────────────────
  const currentTrack = playerStatus?.playlist_loop?.[0] || {};
  const title        = currentTrack.title  || t('player.noTrack');
  const artist       = currentTrack.artist || t('player.unknownArtist');
  const album        = currentTrack.album  || '';
  const isPlaying    = playerStatus?.mode === 'play';
  const volume       = playerStatus?.mixer_volume ?? 0;
  const repeatMode   = Number(playerStatus?.['playlist repeat'] ?? 0);   // 0 off / 1 song / 2 all
  const shuffleMode  = Number(playerStatus?.['playlist shuffle'] ?? 0);  // 0 off / 1 songs / 2 albums
  const willSleepIn  = Number(playerStatus?.will_sleep_in ?? 0);         // seconds left, 0 = inactive
  const duration     = currentTrack.duration || 0;
  const time         = playerStatus?.time || 0;
  const progress     = duration > 0 ? (time / duration) * 100 : 0;
  // Internet radio stations often push their own cover art via ICY metadata;
  // LMS exposes it as `artwork_url` on the playlist entry. Prefer that over
  // the local /music/{id}/cover endpoint (which for a radio stream just
  // serves LMS's generic station-icon placeholder). LMS frequently returns
  // this as a path relative to *itself* (e.g. via its /imageproxy/... image
  // proxy), not an absolute URL — resolve it against the LMS server's own
  // origin before sanitizing, otherwise the browser resolves it against the
  // Electron app's own origin and the image 404s.
  const rawArtworkUrl = currentTrack.artwork_url || '';
  const resolvedArtworkUrl = rawArtworkUrl && rawArtworkUrl[0] === '/'
    ? `${lyrionApi.baseUrl}${rawArtworkUrl}`
    : rawArtworkUrl;
  const remoteArtworkUrl = resolvedArtworkUrl ? safeUrl(resolvedArtworkUrl) : '';
  const artworkUrl   = remoteArtworkUrl || (currentTrack.id ? lyrionApi.getArtworkUrl(currentTrack.id, 300) : null);
  const artworkUrlLg = remoteArtworkUrl || (currentTrack.id ? lyrionApi.getArtworkUrl(currentTrack.id, 600) : null);

  const samplerate = currentTrack.samplerate;
  const samplesize = currentTrack.samplesize;
  const codecType  = currentTrack.type;
  const formatLabel = codecType
    ? `${String(codecType).toUpperCase()}${samplesize ? ` · ${samplesize}bit` : ''}${samplerate ? ` · ${Math.round(samplerate / 1000)}kHz` : ''}`
    : null;

  return {
    // connection
    serverUrl, isConnected, activePlayer, playerStatus, error, isLoading,
    connectToServer, fetchStatus, handleAction,
    // now playing (derived)
    currentTrack, title, artist, album, isPlaying, volume, repeatMode, shuffleMode,
    willSleepIn, duration, time, progress, artworkUrl, artworkUrlLg, formatLabel,
    setVolume, toggleMute, seek, cycleShuffle, cycleRepeat, setSleepTimer,
    // queue
    queue, queueIndex, loadQueue, queueJump, queueRemove, queueMove, queueClear, saveQueue,
    // library navigation
    currentView, libraryData, libraryLoading, visibleCount, navigationStack,
    menuSearch, setMenuSearch, searchText, setSearchText,
    // Jive base+item action model for the current menu view (see resolveMenuIcon/
    // handleMenuItem) — row renderers need this to resolve a leaf's play action.
    menuBase: menuBaseRef.current,
    listScrollRef, handleLibraryScroll,
    navigateTo, goBack, goHome, goToBreadcrumb, handlePlayItem,
    resolveMenuIcon, handleMenuItem, submitMenuSearch, openTabView,
  };
}
