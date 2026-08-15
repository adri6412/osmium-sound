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
  // parsed URL so no scheme/host/meta-characters can ride along. u.pathname/
  // u.search are already fully percent-encoded per the WHATWG URL spec —
  // confirmed live: `new URL('http://x/y?a=<script>"')`.search comes back as
  // `?a=%3Cscript%3E%22`, no extra escaping needed. Wrapping that in
  // encodeURI() (as this used to) doesn't add safety, it just re-escapes the
  // '%' of any percent-encoded byte already in the string — which every
  // artwork URL here has (encodeURIComponent'd player mac / cache-buster).
  // That corrupted e.g. now-playing artwork's ?player=<mac> into garbage LMS
  // couldn't parse back into a real player, silently falling back to
  // whatever other player happened to be active on the same LMS server.
  if (raw[0] === '/' && raw[1] !== '/') {
    try { const u = new URL(raw, 'http://localhost'); return u.pathname + u.search; }
    catch { return ''; }
  }
  // Absolute URL: allow ONLY http/https (blocks javascript:/data:/…) and
  // return the parser's serialized href as-is — already a well-formed,
  // fully percent-encoded string (see above), re-encoding it is redundant
  // and, for any URL that already contains a percent-escape, corrupting.
  try {
    const u = new URL(raw);
    return (u.protocol === 'http:' || u.protocol === 'https:') ? u.href : '';
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
  // This device's own squeezelite player name (see connectToServer), kept in
  // a ref so fetchStatus can cheaply cross-check every poll against it — see
  // fetchStatus's player_name guard below.
  const localPlayerNameRef = useRef(null);

  // Queue state
  const [queue, setQueue] = useState([]);
  const [queueIndex, setQueueIndex] = useState(0);

  // ReplayGain mode ('0' off / '1' track / '2' album / '3' smart) — drives the
  // BitPerfect/ReplayGain LED bar. Polled separately from playerStatus since
  // it's an LMS player *pref*, not part of the status payload, and changes
  // rarely (only via Settings), so a slow independent poll is enough.
  const [replayGainMode, setReplayGainMode] = useState('0');
  // Transition type ('0' none / '1' crossfade / '2' fade-in / '3' fade-out /
  // '4' fade-in+out) + its duration (seconds) — same reasoning as
  // replayGainMode: a player pref, not in `status`, polled alongside it.
  // Feeds BitPerfect too: any active transition applies a gain envelope (a
  // crossfade blends two tracks' samples together, a fade shapes one
  // track's), so it's a digital gain stage exactly like ReplayGain/volume
  // control, not just a crossfade-specific concern.
  const [transitionType, setTransitionType] = useState('0');
  const [transitionDuration, setTransitionDuration] = useState('0');

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
        // LMS player, and on a multiroom LMS server there can be several more
        // (other appliances, lirplay/AirPlay receivers, ...) — radios/apps
        // browsing is capability-filtered per-player, so landing on the wrong
        // one leaves tabs like Radio empty, and now-playing/cover art follows
        // whatever THAT player happens to be doing. Prefer the player matching
        // this device's own squeezelite name (-n, from the Flask API) over
        // just taking the first entry in the list.
        const nameRes = await systemAPI.getPlayerName().catch(() => null);
        const localName = nameRes?.success ? nameRes.data?.name : null;
        localPlayerNameRef.current = localName;
        const local = localName && avail.find(x => x.name === localName);
        // A fresh local-name match always wins over whatever was already
        // selected: if an earlier resolution locked onto the wrong player
        // (e.g. this device's own squeezelite hadn't registered with LMS yet
        // the first time this ran, while other players had), that lock would
        // otherwise persist forever — connectToServer() only re-runs on a
        // poll failure or a multiroom URL change, and a wrongly-selected but
        // perfectly healthy player never fails a poll. Only fall back to
        // keeping the previous selection (or avail[0]) when no local match is
        // resolvable at all, so a transient Flask API hiccup doesn't cause
        // needless flapping between players.
        setActivePlayer(p => local || ((p && avail.find(x => x.playerid === p.playerid)) ? p : avail[0]));
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
  // No overlap guard: a 1s tick with a slow/stuck LMS (this box shares its
  // CPU with squeezelite/CamillaDSP) used to just fire another concurrent
  // POST to jsonrpc.js on top of whichever was still in flight — up to 10 of
  // them stacked before lyrionApi's own 10s abort ceiling caught the first
  // one, which was enough to make LMS's own web server start dropping
  // connections outright (net::ERR_EMPTY_RESPONSE), not just respond slowly.
  const statusInFlightRef = useRef(false);
  const fetchStatus = async () => {
    if (!activePlayer || statusInFlightRef.current) return;
    statusInFlightRef.current = true;
    try {
      const st = await lyrionApi.getPlayerStatus(activePlayer.playerid);
      if (st && typeof st === 'object' && 'mode' in st) {
        // Defense against a stale activePlayer lock (see connectToServer's
        // local-name-match comment): LMS's status response for this exact
        // playerid still carries its own player_name, so if it no longer
        // matches this device's actual local player name, activePlayer has
        // drifted onto someone else's player (renamed locally, or a stale
        // lock from before the local player registered with LMS). Don't
        // apply that status/artwork — force a fresh resolution instead of
        // quietly showing another player's now-playing indefinitely.
        if (localPlayerNameRef.current && st.player_name && st.player_name !== localPlayerNameRef.current) {
          statusFailCountRef.current = 0;
          connectToServer();
          return;
        }
        statusFailCountRef.current = 0;
        // LMS reports volume under the key "mixer volume" (space, like
        // "playlist shuffle"/"playlist repeat" below) — there is no
        // "mixer_volume" in the real status payload. Normalize it into the
        // "mixer_volume" key the rest of this hook (and setVolume's
        // optimistic update) reads/writes; otherwise every unguarded refetch
        // wipes it to undefined and the `?? 0` fallback further down shows 0
        // — the actual cause of the slider settling back to zero after the
        // guard window above elapses.
        const normalized = { ...st, mixer_volume: Math.abs(Number(st['mixer volume'])) || 0 };
        if (Date.now() - lastVolumeChangeRef.current < VOLUME_GUARD_MS) {
          setPlayerStatus(prev => ({ ...normalized, mixer_volume: prev?.mixer_volume ?? normalized.mixer_volume }));
        } else {
          setPlayerStatus(normalized);
        }
        return;
      }
    } catch (_) { /* fall through to failure counting below */ }
    finally {
      statusInFlightRef.current = false;
    }
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

  // ReplayGain mode: cheap, rarely-changing pref — a flat 5s poll (no
  // play/pause-adaptive cadence needed) is enough to keep the LED bar in sync
  // with changes made from Settings.
  useEffect(() => {
    if (!activePlayer) return;
    let cancelled = false;
    const pollReplayGain = async () => {
      try {
        const [rg, tt, td] = await Promise.all([
          lyrionApi.getPlayerPref(activePlayer.playerid, 'replayGainMode'),
          lyrionApi.getPlayerPref(activePlayer.playerid, 'transitionType'),
          lyrionApi.getPlayerPref(activePlayer.playerid, 'transitionDuration'),
        ]);
        if (cancelled) return;
        if (rg != null) setReplayGainMode(String(rg));
        if (tt != null) setTransitionType(String(tt));
        if (td != null) setTransitionDuration(String(td));
      } catch (_) { /* keep last known values */ }
    };
    pollReplayGain();
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') pollReplayGain();
    }, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [activePlayer]);

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
  // Queue entries carry no stable id of their own (id/url can repeat when the
  // same track appears twice in a queue), so React would key drag-reordered
  // rows by position and remount them instead of sliding them. Stamp a
  // synthetic per-fetch `_uid` here, once, so row components can key off it.
  const queueUidRef = useRef(0);
  const loadQueue = async () => {
    if (!activePlayer) return;
    try {
      const r = await lyrionApi.getQueue(activePlayer.playerid);
      setQueue((r?.playlist_loop || []).map((item) => ({ ...item, _uid: ++queueUidRef.current })));
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
  // Append to / insert-next-in the queue without replacing it (unlike
  // handlePlayItem's playlistcontrol cmd:load) — backs the long-press
  // context menu's "add to queue" / "play next" actions.
  const queueAddTrack  = (id) => handleAction(() => lyrionApi.playItem(activePlayer.playerid, 'track_id', id, 'add'));
  const queuePlayNext  = (id) => handleAction(() => lyrionApi.playItem(activePlayer.playerid, 'track_id', id, 'insert'));

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
      // Favorites now has its own tile in the Musica tab (see LyrionServer.jsx),
      // so drop it from the generic Apps list here. Match on the resolved `go`
      // action's base command rather than `id`/label text — those vary across
      // LMS versions/locales, but the command a Favorites node drills into is
      // always ['favorites', 'items', ...].
      const isFavorites = (it) => it.actions?.go?.cmd?.[0] === 'favorites';
      return all
        .filter(it => it.actions && (it.actions.go || it.actions.do || it.input)
          && ['home', '', 'extras'].includes(it.node)
          && !EXCLUDE.has(it.id)
          && !isFavorites(it))
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

  // `replace`: swap the current top-of-stack entry instead of pushing a new
  // one — used when re-submitting a search from its own results screen, so
  // typing a second query doesn't pile up a fresh breadcrumb crumb per search.
  const navigateTo = async (view, title, params = null, { replace = false } = {}) => {
    setLibraryLoading(true);
    try {
      const data = await fetchViewData(view, params);
      setNavigationStack(prev => replace
        ? [...prev.slice(0, -1), { view, title, params }]
        : [...prev, { view, title, params }]);
      setCurrentView(view);
      setLibraryData(data);
    } catch (err) { console.error(`Failed to load ${view}:`, err); }
    finally { setLibraryLoading(false); }
  };

  const goBack = async () => {
    if (navigationStack.length <= 1) return;
    setMenuSearch(null); // leaving this node — dismiss its search bar, if any
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
    setMenuSearch(null); // jumping to an ancestor crumb — dismiss any open search bar
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
    if (item.input && go) {                 // needs text input → search bar
      setSearchText('');
      setMenuSearch({ action: go, title: item.text || item.name || t('player.titles.search') });
    } else if (go) {                        // submenu (or play-on-go leaf) → drill in
      setMenuSearch(null);                  // leaving any open search context behind
      navigateTo('menu', item.text || item.name || '…', { action: go });
    } else if (play) {                      // playable leaf
      handleAction(() => lyrionApi.menuDo(activePlayer.playerid, play));
    } else if (doAct) {                     // toggle / settings action
      handleAction(() => lyrionApi.menuDo(activePlayer.playerid, doAct));
    }
  };

  // Submits the persistent search bar (see LyrionServer.jsx's renderTabContent).
  // The bar stays open after this — Qobuz/Tidal-style search-then-refine —
  // rather than closing on every query like the old one-shot prompt did.
  const submitMenuSearch = () => {
    if (!menuSearch) return;
    const q = searchText.trim();
    // An empty query isn't just a no-op here: some Lyrion search plugins
    // (RadioNet in particular) build an outbound API request straight from
    // it and choke on a blank term, surfacing a raw network-error string as
    // the first "result" instead of just returning nothing.
    if (!q) return;
    const { action, title } = menuSearch;
    // Re-searching from the results screen replaces that entry instead of
    // stacking a fresh breadcrumb crumb per query.
    const top = navigationStack[navigationStack.length - 1];
    const isSameSearch = top?.view === 'menu' && top?.params?.action === action;
    navigateTo('menu', title, { action, input: q }, { replace: isSameSearch });
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
  // Local tracks have a stable DB id, so they use the exact same static,
  // race-free per-ID endpoint the library browse grid already relies on
  // (lyrionApi.getArtworkUrl → /music/{id}/cover) — no cache-buster needed,
  // the URL itself changes when (and only when) the track does, and there's
  // no server-side "what's playing right now" state to race against.
  //
  // Remote streams (radio/Qobuz/Spotify/on-demand plugins/...) don't have a
  // resolvable id/coverid on the client — that field can be a path relative
  // to LMS itself (its /imageproxy/... proxy), a protocol-handler-specific
  // format, or simply absent depending on the plugin. LMS already has to
  // solve this exact problem for its own web skins, via a special
  // `/music/current/cover.jpg?player=<mac>` URL that it resolves server-side
  // for whatever is actually playing (see Slim::Web::Graphics::
  // artworkRequest's `id eq 'current'` case) — reuse that instead of
  // duplicating LMS's own resolution logic on the client. `k=` is a pure
  // cache-buster: the URL itself never changes as tracks advance, so without
  // it the browser would keep showing a stale image.
  // For internet radio the playlist_loop entry's `id`/`title`/`artist`/
  // `album` are the *station*'s, set once when the stream started, and
  // don't change as the station's own now-playing song changes — LMS never
  // rewrites the playlist entry's DB fields from ICY/plugin metadata.
  // The one field that *does* update live per song is the top-level
  // `current_title` the status query adds for any playing remote track
  // (Slim::Control::Queries::statusQuery, via Slim::Music::Info::
  // getCurrentTitle) — and it's exactly what the /music/current/cover.jpg
  // endpoint re-resolves through the stream's protocol handler on every
  // request (Slim::Web::Graphics, the `id eq 'current'` + `->remote` case).
  // Without it in the key, the URL stays identical across songs and the
  // browser just keeps showing the first song's (or the station's) cover.
  //
  // current_title alone isn't enough, though: it's populated via ICY-style
  // metadata, which classic internet radio sends but on-demand streaming
  // plugins (Qobuz, Tidal, ...) generally don't — their "radio"/mix features
  // can advance to a new song while leaving id/title/artist/album/current_title
  // all exactly as they were (whatever the plugin set when the stream started),
  // so the key never changes and the cover sticks on the first song. There's
  // no single field these plugins reliably update, so for any remote source
  // add a coarse heartbeat (`time` is the one field guaranteed to keep moving
  // during playback) — it re-fetches the cover at most every ~10s, which
  // bounds how stale it can get without refetching on every 1s poll.
  //
  // `artworkIdentityKey` mirrors trackKey but *without* the heartbeat: it
  // only changes when LMS has actually told us something changed (id/title/
  // artist/album/current_title), never on a routine heartbeat tick. The
  // consumer (usePolledArtwork in LyrionServer.jsx) uses this to tell a
  // confirmed track change — where the art on screen is now known-stale and
  // must not linger — apart from a periodic "maybe it changed, maybe it
  // didn't" probe, where keeping the current art visible until proven
  // otherwise is the right call.
  // LMS's JSON-RPC serializes `remote` as the STRING "0"/"1", not a number
  // or boolean — confirmed live (`"remote":"0"` in a real status response).
  // `!!currentTrack.remote` is true for ANY non-empty string, "0" included,
  // so this was permanently misidentifying every local track as remote and
  // routing it through the player-scoped /music/current/cover.jpg path
  // instead of the static per-id one. Harmless with a single active LMS
  // player (that endpoint's own player= resolution has nothing else to fall
  // back to but the right one); becomes visibly wrong the moment a second
  // player is active on the same server (see safeUrl's comment above for the
  // other half of this bug — a mangled player= param compounded it).
  const isRemoteTrack = Number(currentTrack.remote) === 1;
  const remoteHeartbeat = isRemoteTrack ? Math.floor((playerStatus?.time || 0) / 10) : '';
  const artworkIdentityKey = `${currentTrack.id || ''}-${currentTrack.title || ''}-${currentTrack.artist || ''}-${currentTrack.album || ''}-${playerStatus?.current_title || ''}`;
  const trackKey = `${artworkIdentityKey}-${remoteHeartbeat}`;
  const nowPlayingCoverBase = activePlayer?.playerid
    ? `${lyrionApi.baseUrl}/music/current/cover.jpg?player=${encodeURIComponent(activePlayer.playerid)}&k=${encodeURIComponent(trackKey)}`
    : null;
  const artworkUrl   = isRemoteTrack
    ? (nowPlayingCoverBase ? safeUrl(`${nowPlayingCoverBase}&size=300`) : null)
    : (currentTrack.id ? safeUrl(lyrionApi.getArtworkUrl(currentTrack.id, 300, currentTrack.coverid)) : null);
  const artworkUrlLg = isRemoteTrack
    ? (nowPlayingCoverBase ? safeUrl(`${nowPlayingCoverBase}&size=600`) : null)
    : (currentTrack.id ? safeUrl(lyrionApi.getArtworkUrl(currentTrack.id, 600, currentTrack.coverid)) : null);

  const samplerate = currentTrack.samplerate;
  const samplesize = currentTrack.samplesize;
  const codecType  = currentTrack.type;
  const formatLabel = codecType
    ? `${String(codecType).toUpperCase()}${samplesize ? ` · ${samplesize}bit` : ''}${samplerate ? ` · ${Math.round(samplerate / 1000)}kHz` : ''}`
    : null;
  // Hi-Res/PCM/DSD LED bar segment. `type` is LMS's own codec id — DSD-native
  // files report 'dsf'/'dff' there regardless of the DoP samplerate they're
  // wrapped in, so that's the reliable DSD signal (not samplerate/size, which
  // describe the PCM carrier, not the source). PCM above redbook (44.1kHz/
  // 16bit) also lights Hi-Res alongside PCM; DSD always lights Hi-Res too.
  const isDsdTrack = /^ds[df]$/i.test(String(codecType || ''));
  const isHiResPcm = !isDsdTrack && ((samplerate > 44100) || (samplesize > 16));
  const formatQuality = codecType
    ? { pcm: !isDsdTrack, hires: isDsdTrack || isHiResPcm, dsd: isDsdTrack }
    : { pcm: false, hires: false, dsd: false };
  // LMS applies ReplayGain via software gain on the samples, so a track is
  // never bit-perfect while it's active — the two are mutually exclusive,
  // which is also how the LED bar artwork itself was drawn (only one LED lit
  // at a time). Nothing lit while nothing is actually playing.
  const replayGainActive = replayGainMode !== '0';
  // Actually verify bit-perfect, not just "ReplayGain happens to be off":
  // `status` always includes `use_volume_control` (Slim::Control::Queries,
  // unconditional, no tag needed) — 1 whenever LMS's own volume slider is
  // adjusting the digital output level (the "Il controllo del volume regola
  // le uscite" player setting, or a player with no fixed-100% option at
  // all), 0 only when output is fixed at 100% ("digitalVolumeControl" pref
  // off). Either way it's a digital gain stage on the samples, same as
  // ReplayGain — so it blocks BitPerfect the same way. Missing/undefined
  // (older LMS, field briefly absent) fails open (treated as not adjusting)
  // rather than never lighting BitPerfect on an LMS that doesn't send it.
  const digitalVolumeAdjusting = Number(playerStatus?.use_volume_control) === 1;
  // Any transition (crossfade blends two tracks' samples; a fade shapes
  // one) is a digital gain stage too — only matters once it actually has a
  // nonzero duration to apply.
  const transitionActive = transitionType !== '0' && Number(transitionDuration) > 0;
  const isBitPerfect = isPlaying && !replayGainActive && !digitalVolumeAdjusting && !transitionActive;
  // Neither LED lights when playing with volume-adjusted-but-not-ReplayGain
  // (e.g. LMS's own volume control turned up) — genuinely neither label,
  // and lighting ReplayGain there would be wrong.
  const playbackMode = !isPlaying ? null : replayGainActive ? 'replaygain' : (isBitPerfect ? 'bitperfect' : null);

  return {
    // connection
    serverUrl, isConnected, activePlayer, playerStatus, error, isLoading,
    connectToServer, fetchStatus, handleAction,
    // now playing (derived)
    currentTrack, title, artist, album, isPlaying, volume, repeatMode, shuffleMode,
    willSleepIn, duration, time, progress, artworkUrl, artworkUrlLg, formatLabel, formatQuality,
    replayGainMode, replayGainActive, playbackMode,
    isRemoteTrack, artworkIdentityKey,
    setVolume, toggleMute, seek, cycleShuffle, cycleRepeat, setSleepTimer,
    // queue
    queue, queueIndex, loadQueue, queueJump, queueRemove, queueMove, queueClear, saveQueue,
    queueAddTrack, queuePlayNext,
    // library navigation
    currentView, libraryData, libraryLoading, visibleCount, setVisibleCount, navigationStack,
    menuSearch, setMenuSearch, searchText, setSearchText,
    // Jive base+item action model for the current menu view (see resolveMenuIcon/
    // handleMenuItem) — row renderers need this to resolve a leaf's play action.
    menuBase: menuBaseRef.current,
    listScrollRef, handleLibraryScroll,
    navigateTo, goBack, goHome, goToBreadcrumb, handlePlayItem,
    resolveMenuIcon, handleMenuItem, submitMenuSearch, openTabView,
  };
}
