import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Play, Pause, SkipBack, SkipForward,
  Volume2, VolumeX, Music, AlertCircle, RefreshCw,
  Folder, User, Disc, Home, ChevronRight, ChevronDown,
  Radio, AppWindow,
  Settings as SettingsIcon, Maximize2,
  Shuffle, Repeat, Repeat1, ListMusic, Moon,
  Trash2, X, Save, ArrowUp, ArrowDown
} from 'lucide-react';
import { lyrionApi } from '../utils/lyrionApi';
import { useI18n } from '../i18n';
import AnalogVUMeter from '../components/AnalogVUMeter';
import SettingsPage from './Settings';

// ── Safe image URLs ───────────────────────────────────────────
// Artwork/icon URLs come from the (untrusted) Lyrion server. Only allow
// http(s) absolute or same-origin relative URLs as <img src>; reject
// javascript:, data: and other schemes that can lead to DOM-based XSS.
const safeUrl = (url) => {
  if (typeof url !== 'string') return '';
  const u = url.trim();
  if (/^https?:\/\//i.test(u)) return u;
  if (u.startsWith('/') && !u.startsWith('//')) return u;
  return '';
};

// ── Tab definitions ──────────────────────────────────────────
// `labelKey` is resolved through i18n at render time (null = icon-only tab).
const TABS = [
  { id: 'musica',   labelKey: 'player.tabs.music', Icon: Music },
  { id: 'radio',    labelKey: 'player.tabs.radio', Icon: Radio },
  { id: 'apps',     labelKey: 'player.tabs.apps',  Icon: AppWindow },
  { id: 'settings', labelKey: null,                Icon: SettingsIcon },
];

// How many library rows/cards to mount initially and add per scroll step. The
// full result set is kept in state (search/counts stay correct); we just grow
// the rendered slice as the user scrolls, so a 5000-album grid never tries to
// mount 5000 nodes at once on the mini-PC.
const LIST_PAGE = 120;

// ── Artwork with error fallback ───────────────────────────────
const ArtworkImage = ({ src, alt, className, FallbackIcon }) => {
  const [err, setErr] = useState(false);
  useEffect(() => { setErr(false); }, [src]);
  if (!src || err) {
    return (
      <div className="absolute inset-0 flex items-center justify-center text-hifi-silver/20 bg-gradient-to-br from-hifi-gray to-hifi-dark">
        <FallbackIcon size={40} />
      </div>
    );
  }
  // loading="lazy" so an album grid with hundreds of covers only fetches the
  // ones scrolled into view (decoding off the main thread keeps scroll smooth).
  return <img src={safeUrl(src)} alt={alt} className={className} loading="lazy" decoding="async" onError={() => setErr(true)} />;
};

// ── Animated playing indicator ────────────────────────────────
const PlayingBars = () => (
  <div className="flex items-end space-x-[2px] h-4 ml-1.5 shrink-0 self-center">
    <div className="playing-bar h-3" />
    <div className="playing-bar h-4" />
    <div className="playing-bar h-2.5" />
  </div>
);

// ── Main component ────────────────────────────────────────────
const LyrionServer = () => {
  const { t } = useI18n();
  const [serverUrl] = useState(localStorage.getItem('lyrionUrl') || 'http://localhost:9000');

  // LMS state
  const [isConnected, setIsConnected] = useState(false);
  const [activePlayer, setActivePlayer] = useState(null);
  const [playerStatus, setPlayerStatus] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // UI state
  const [isPlayerExpanded, setIsPlayerExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('musica');

  // Queue / sleep state
  const [showQueue, setShowQueue] = useState(false);
  const [queue, setQueue] = useState([]);
  const [queueIndex, setQueueIndex] = useState(0);
  const [saveQueueOpen, setSaveQueueOpen] = useState(false);
  const [queueName, setQueueName] = useState('');
  const [saveMsg, setSaveMsg] = useState('');
  const [sleepMenuOpen, setSleepMenuOpen] = useState(false);

  // Library state
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
  useEffect(() => {
    lyrionApi.setBaseUrl(serverUrl);
    const t = setTimeout(connectToServer, 10000);
    return () => clearTimeout(t);
  }, [serverUrl]);

  const connectToServer = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const ss = await lyrionApi.getServerStatus();
      setIsConnected(true);
      const avail = ss?.players_loop || [];
      if (avail.length > 0)
        setActivePlayer(p => p && avail.find(x => x.playerid === p.playerid) ? p : avail[0]);
      else { setActivePlayer(null); setPlayerStatus(null); }
    } catch (_) {
      setIsConnected(false);
      setError(t('player.connectError'));
    } finally {
      setIsLoading(false);
    }
  };

  const fetchStatus = async () => {
    if (!activePlayer) return;
    try { setPlayerStatus(await lyrionApi.getPlayerStatus(activePlayer.playerid)); } catch (_) {}
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
  }, [activePlayer, playing]);

  // New list contents (navigated to a different view / went back) → render from
  // the top again. Also keep the scroll container reset to the top.
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

  // ── Play queue ─────────────────────────────────────────────
  const loadQueue = async () => {
    if (!activePlayer) return;
    try {
      const r = await lyrionApi.getQueue(activePlayer.playerid);
      setQueue(r?.playlist_loop || []);
      setQueueIndex(Number(r?.playlist_cur_index ?? 0));
    } catch (_) {}
  };
  const openQueue = () => { setShowQueue(true); loadQueue(); };
  const queueJump   = (i) => handleAction(() => lyrionApi.playlistJump(activePlayer.playerid, i)).then(loadQueue);
  const queueRemove = (i) => handleAction(() => lyrionApi.playlistRemove(activePlayer.playerid, i)).then(loadQueue);
  const queueMove   = (from, to) => {
    if (to < 0 || to >= queue.length) return;
    handleAction(() => lyrionApi.playlistMove(activePlayer.playerid, from, to)).then(loadQueue);
  };
  const queueClear  = () => handleAction(() => lyrionApi.playlistClear(activePlayer.playerid)).then(loadQueue);
  // Save the queue, verify Lyrion actually wrote it, then jump to the Playlists
  // view so the result is immediately visible. `writeError` in the response
  // means the save failed (e.g. no writable playlist folder configured).
  const saveQueue   = async () => {
    const name = queueName.trim();
    if (!name || !activePlayer) return;
    setSaveMsg('');
    try {
      const res = await lyrionApi.playlistSave(activePlayer.playerid, name);
      if (res && (res.writeError || res.error)) {
        setSaveMsg(t('player.saveError'));
        return;
      }
      setSaveQueueOpen(false);
      setQueueName('');
      setShowQueue(false);
      setIsPlayerExpanded(false);
      setActiveTab('musica');
      setMenuSearch(null);
      setNavigationStack([{ view: 'home', title: t('player.titles.home'), params: null }]);
      setCurrentView('home');
      navigateTo('playlists', t('player.titles.playlists'));
    } catch (_) {
      setSaveMsg(t('player.saveError'));
    }
  };

  // ── Sleep timer ────────────────────────────────────────────
  const setSleepTimer = (minutes) => {
    setSleepMenuOpen(false);
    if (!activePlayer) return;
    handleAction(() => lyrionApi.setSleep(activePlayer.playerid, minutes * 60));
  };

  const formatTime = (s) => {
    if (!s || isNaN(s)) return '0:00';
    return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
  };

  // ── Library navigation ─────────────────────────────────────
  const fetchViewData = async (view, params) => {
    if (view === 'artists')      { const r = await lyrionApi.getArtists(); return r?.artists_loop || []; }
    if (view === 'albums')       { const r = await lyrionApi.getAlbums(9999, 0, params?.artistId); return r?.albums_loop || []; }
    if (view === 'tracks')       { const r = await lyrionApi.getTracks(9999, 0, params?.albumId); return r?.titles_loop || []; }
    if (view === 'folders')      { const r = await lyrionApi.getMusicFolders(params?.folderId); return r?.folder_loop || []; }
    if (view === 'playlists')    { const r = await lyrionApi.getPlaylists(); return r?.playlists_loop || []; }
    if (view === 'playlist_tracks') { const r = await lyrionApi.getPlaylistTracks(params?.playlistId); return r?.playlisttracks_loop || []; }
    if (view === 'radios')       { const r = await lyrionApi.getRadios(activePlayer?.playerid); return r?.radios_loop || []; }
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
      return r?.item_loop || r?.[`${params.pluginCmd}_loop`] || [];
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

  const goHome = () => {
    setMenuSearch(null);
    setNavigationStack([{ view: 'home', title: t('player.titles.home'), params: null }]);
    setCurrentView('home');
  };

  const handlePlayItem = (type, id) => {
    if (!activePlayer) return;
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

  // ── Tab switch ─────────────────────────────────────────────
  const handleTabSwitch = async (tabId) => {
    setActiveTab(tabId);
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
  const artworkUrl   = currentTrack.id ? lyrionApi.getArtworkUrl(currentTrack.id, 300) : null;
  const artworkUrlLg = currentTrack.id ? lyrionApi.getArtworkUrl(currentTrack.id, 600) : null;

  const samplerate = currentTrack.samplerate;
  const samplesize = currentTrack.samplesize;
  const codecType  = currentTrack.type;
  const formatLabel = codecType
    ? `${String(codecType).toUpperCase()}${samplesize ? ` · ${samplesize}bit` : ''}${samplerate ? ` · ${Math.round(samplerate / 1000)}kHz` : ''}`
    : null;

  // ── Library content renderer ───────────────────────────────
  const renderLibraryContent = () => {
    if (menuSearch) {
      return (
        <div className="p-4 space-y-3">
          <p className="text-sm font-medium text-white">{menuSearch.title}</p>
          <input
            type="text"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submitMenuSearch(); }}
            placeholder={t('player.searchPlaceholder')}
            className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-3 text-white focus:outline-none focus:border-hifi-gold"
          />
          <div className="flex gap-2">
            <button onClick={() => { setMenuSearch(null); setSearchText(''); }}
              className="flex-1 bg-hifi-light hover:bg-hifi-accent text-white py-2.5 rounded-lg text-sm font-medium transition-colors">
              {t('common.cancel')}
            </button>
            <button onClick={submitMenuSearch}
              className="flex-1 bg-hifi-gold hover:bg-yellow-600 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
              {t('common.search')}
            </button>
          </div>
        </div>
      );
    }
    if (libraryLoading) {
      return (
        <div className="flex-1 flex items-center justify-center">
          <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            className="w-10 h-10 border-4 border-hifi-gold border-t-transparent rounded-full" />
        </div>
      );
    }

    if (currentView === 'home') {
      return (
        <div className="grid grid-cols-3 gap-3 p-4">
          {[
            { label: t('player.titles.artists'),   Icon: User,      action: () => navigateTo('artists',   t('player.titles.artists')) },
            { label: t('player.titles.albums'),    Icon: Disc,      action: () => navigateTo('albums',    t('player.titles.albums')) },
            { label: t('player.titles.folders'),   Icon: Folder,    action: () => navigateTo('folders',   t('player.titles.folders')) },
            { label: t('player.titles.playlists'), Icon: ListMusic, action: () => navigateTo('playlists', t('player.titles.playlists')) },
          ].map(({ label, Icon, action }) => (
            <button key={label} onClick={action}
              className="flex flex-col items-center justify-center py-7 bg-hifi-surface hover:bg-hifi-light rounded-xl border border-hifi-border hover:border-hifi-accent transition-colors">
              <Icon size={30} className="text-hifi-silver mb-2.5" />
              <span className="text-sm font-medium text-white">{label}</span>
            </button>
          ))}
        </div>
      );
    }

    const visibleItems = libraryData.slice(0, visibleCount);
    return (
      <div ref={listScrollRef} onScroll={handleLibraryScroll}
        className="flex-1 overflow-y-auto content-scrollbar px-3 pb-3">
        {currentView === 'albums' ? (
          <div className="grid grid-cols-3 gap-3 pt-1">
            {visibleItems.map((item, idx) => {
              const aId  = item.artwork_track_id || item.id;
              const aUrl = aId ? lyrionApi.getArtworkUrl(aId, 200) : null;
              return (
                <div key={item.id || idx}
                  onClick={() => navigateTo('tracks', item.album, { albumId: item.id })}
                  className="bg-hifi-surface hover:bg-hifi-light rounded-xl overflow-hidden group cursor-pointer border border-hifi-border hover:border-hifi-accent transition-colors">
                  <div className="relative aspect-square bg-hifi-gray">
                    <ArtworkImage src={aUrl} alt={item.album} className="w-full h-full object-cover" FallbackIcon={Disc} />
                    <div className="absolute inset-0 bg-black/50 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={(e) => { e.stopPropagation(); handlePlayItem('album_id', item.id); }}
                        className="p-3 bg-hifi-gold text-black rounded-full hover:scale-110 transition-transform shadow-lg">
                        <Play size={16} fill="currentColor" />
                      </button>
                    </div>
                  </div>
                  <div className="p-2">
                    <p className="text-white text-xs font-medium truncate">{item.album}</p>
                    <p className="text-hifi-silver/70 text-xs truncate">{item.artist}</p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <ul className="space-y-1 pt-1">
            {visibleItems.map((item, idx) => {
              if (currentView === 'artists') return (
                <li key={idx}
                  onClick={() => navigateTo('albums', item.artist, { artistId: item.id })}
                  className="flex items-center justify-between px-3 py-2.5 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                  <div className="flex items-center space-x-3">
                    <div className="w-7 h-7 rounded-full bg-hifi-light flex items-center justify-center flex-shrink-0">
                      <User size={13} className="text-hifi-silver" />
                    </div>
                    <span className="text-sm text-white">{item.artist}</span>
                  </div>
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={(e) => { e.stopPropagation(); handlePlayItem('artist_id', item.id); }}
                      className="p-1.5 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                      <Play size={12} fill="currentColor" />
                    </button>
                  </div>
                </li>
              );

              if (currentView === 'tracks' || currentView === 'playlist_tracks') return (
                <li key={idx}
                  onClick={() => handlePlayItem('track_id', item.id)}
                  className="flex items-center px-3 py-2.5 bg-hifi-surface hover:bg-hifi-light rounded-lg cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                  <Music size={13} className="text-hifi-silver/60 mr-3 flex-shrink-0" />
                  <span className="text-sm text-white truncate">{item.title}</span>
                </li>
              );

              if (currentView === 'playlists') return (
                <li key={item.id || idx}
                  onClick={() => navigateTo('playlist_tracks', item.playlist, { playlistId: item.id })}
                  className="flex items-center justify-between px-3 py-2.5 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                  <div className="flex items-center space-x-3 min-w-0">
                    <div className="w-7 h-7 rounded-lg bg-hifi-light flex items-center justify-center flex-shrink-0">
                      <ListMusic size={14} className="text-hifi-silver" />
                    </div>
                    <span className="text-sm text-white truncate">{item.playlist}</span>
                  </div>
                  <div className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                    <button onClick={(e) => { e.stopPropagation(); handlePlayItem('playlist_id', item.id); }}
                      className="p-1.5 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                      <Play size={12} fill="currentColor" />
                    </button>
                  </div>
                </li>
              );

              if (currentView === 'folders') {
                const isDir = item.type === 'folder';
                return (
                  <li key={idx}
                    onClick={() => isDir ? navigateTo('folders', item.filename, { folderId: item.id }) : handlePlayItem('track_id', item.id)}
                    className="flex items-center justify-between px-3 py-2.5 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                    <div className="flex items-center space-x-3 min-w-0">
                      {isDir
                        ? <Folder size={15} className="text-hifi-gold flex-shrink-0" />
                        : <Music size={15} className="text-hifi-silver/60 flex-shrink-0" />}
                      <span className="text-sm text-white truncate">{item.filename || item.title}</span>
                    </div>
                    <div className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                      <button onClick={(e) => { e.stopPropagation(); handlePlayItem(isDir ? 'folder_id' : 'track_id', item.id); }}
                        className="p-1.5 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                        <Play size={12} fill="currentColor" />
                      </button>
                    </div>
                  </li>
                );
              }

              if (currentView === 'radios' || currentView === 'apps') return (
                <li key={idx}
                  onClick={() => navigateTo('plugin_items', item.name, { pluginCmd: item.cmd })}
                  className="flex items-center px-3 py-2.5 bg-hifi-surface hover:bg-hifi-light rounded-lg cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                  {item.icon
                    ? <img src={safeUrl(item.icon.startsWith('http') ? item.icon : `${serverUrl}/${item.icon}`)}
                        className="w-6 h-6 rounded mr-3 flex-shrink-0" alt="" loading="lazy" decoding="async"
                        onError={(e) => { e.target.style.display = 'none'; }} />
                    : currentView === 'radios'
                      ? <Radio size={15} className="text-hifi-silver/60 mr-3 flex-shrink-0" />
                      : <AppWindow size={15} className="text-hifi-silver/60 mr-3 flex-shrink-0" />
                  }
                  <span className="text-sm text-white">{item.name}</span>
                </li>
              );

              if (currentView === 'menu_home' || currentView === 'menu') {
                const iconUrl = resolveMenuIcon(item);
                // Resolve through the menu `base` (Jive base+item model): sub-items
                // inherit base.actions and only supply params, so reading
                // item.actions directly would miss them.
                const base = menuBaseRef.current;
                const play = lyrionApi.resolveMenuAction(base, item, 'play')
                  || lyrionApi.resolveMenuAction(base, item, 'playall');
                const isNav = !!(lyrionApi.resolveMenuAction(base, item, 'go') || item.input);
                return (
                  <li key={item.id || idx}
                    onClick={() => handleMenuItem(item)}
                    className="flex items-center justify-between px-3 py-2.5 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                    <div className="flex items-center space-x-3 min-w-0">
                      {iconUrl
                        ? <img src={safeUrl(iconUrl)} className="w-6 h-6 rounded flex-shrink-0 object-cover" alt="" loading="lazy" decoding="async"
                            onError={(e) => { e.target.style.display = 'none'; }} />
                        : isNav
                          ? <AppWindow size={15} className="text-hifi-silver/60 flex-shrink-0" />
                          : <Music size={15} className="text-hifi-silver/60 flex-shrink-0" />
                      }
                      <span className="text-sm text-white truncate">{item.text || item.name}</span>
                    </div>
                    {play && (
                      <div className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                        <button onClick={(e) => { e.stopPropagation(); handleAction(() => lyrionApi.menuDo(activePlayer.playerid, play)); }}
                          className="p-1.5 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                          <Play size={12} fill="currentColor" />
                        </button>
                      </div>
                    )}
                  </li>
                );
              }

              if (currentView === 'plugin_items') {
                const params = navigationStack[navigationStack.length - 1].params;
                const pluginCmd = params?.pluginCmd;
                const hasItems = item.hasitems === 1 || item.type === 'link';
                const isAudio  = item.isaudio === 1 || item.type === 'audio';
                return (
                  <li key={idx}
                    onClick={() => {
                      if (hasItems) navigateTo('plugin_items', item.name || item.title, { pluginCmd, itemId: item.id });
                      else if (isAudio || item.play) handleAction(() => lyrionApi.playPluginItem(activePlayer.playerid, pluginCmd, item.id || item.play));
                    }}
                    className="flex items-center justify-between px-3 py-2.5 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                    <div className="flex items-center space-x-3 min-w-0">
                      {item.icon
                        ? <img src={safeUrl(item.icon.startsWith('http') ? item.icon : `${serverUrl}/${item.icon}`)}
                            className="w-6 h-6 rounded flex-shrink-0" alt="" loading="lazy" decoding="async"
                            onError={(e) => { e.target.style.display = 'none'; }} />
                        : hasItems
                          ? <Folder size={15} className="text-hifi-silver/60 flex-shrink-0" />
                          : <Music size={15} className="text-hifi-silver/60 flex-shrink-0" />
                      }
                      <span className="text-sm text-white truncate">{item.name || item.title}</span>
                    </div>
                    {(isAudio || item.play) && (
                      <div className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                        <button onClick={(e) => { e.stopPropagation(); handleAction(() => lyrionApi.playPluginItem(activePlayer.playerid, pluginCmd, item.id || item.play)); }}
                          className="p-1.5 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                          <Play size={12} fill="currentColor" />
                        </button>
                      </div>
                    )}
                  </li>
                );
              }

              return null;
            })}
          </ul>
        )}
      </div>
    );
  };

  // ── Right-panel content ────────────────────────────────────
  const renderTabContent = () => {
    if (activeTab === 'settings') return <SettingsPage />;

    // musica / radio / apps — library browser
    if (isLoading && !isConnected) return (
      <div className="flex-1 flex flex-col items-center justify-center">
        <motion.div animate={{ rotate: 360 }} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
          className="w-12 h-12 border-4 border-hifi-gold border-t-transparent rounded-full mb-4" />
        <p className="text-hifi-silver text-sm">{t('player.connecting')}</p>
      </div>
    );
    if (error) return (
      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
        <AlertCircle size={40} className="text-red-400 mb-4" />
        <h2 className="text-base font-bold text-white mb-2">{t('player.connectionErrorTitle')}</h2>
        <p className="text-hifi-silver/70 text-sm mb-6 max-w-xs">{error}</p>
        <button onClick={connectToServer}
          className="flex items-center space-x-2 bg-hifi-surface hover:bg-hifi-light px-5 py-2.5 rounded-lg text-white text-sm transition-colors border border-hifi-border">
          <RefreshCw size={15} />
          <span>{t('common.retry')}</span>
        </button>
      </div>
    );
    if (!activePlayer) return (
      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
        <Music size={48} className="text-hifi-silver/20 mb-4" />
        <p className="text-hifi-silver/60 text-sm mb-2">{t('player.noPlayer')}</p>
        <p className="text-hifi-silver/40 text-xs mb-6 max-w-xs">
          {t('player.noPlayerHint')}
        </p>
        <button onClick={connectToServer} disabled={isLoading}
          className="flex items-center space-x-2 bg-hifi-surface hover:bg-hifi-light disabled:opacity-50 px-5 py-2.5 rounded-lg text-white text-sm transition-colors border border-hifi-border">
          <RefreshCw size={15} className={isLoading ? 'animate-spin' : ''} />
          <span>{isLoading ? t('player.connectingShort') : t('player.reconnect')}</span>
        </button>
      </div>
    );

    return (
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Breadcrumb */}
        <div className="flex items-center px-3 py-2 border-b border-hifi-border/50 shrink-0 bg-hifi-panel/40">
          <button onClick={goHome}
            className="p-1.5 text-hifi-silver/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
            <Home size={15} />
          </button>
          {navigationStack.length > 1 && (
            <div className="flex items-center space-x-1 text-xs ml-1 min-w-0 flex-1">
              {navigationStack.map((nav, idx) => (
                <React.Fragment key={idx}>
                  {idx > 0 && <ChevronRight size={11} className="text-hifi-silver/30 flex-shrink-0" />}
                  <span
                    className={`truncate max-w-[100px] ${idx === navigationStack.length - 1 ? 'text-white font-medium' : 'text-hifi-silver/60 cursor-pointer hover:text-white'}`}
                    onClick={() => {
                      if (idx < navigationStack.length - 1) {
                        const ns = navigationStack.slice(0, idx + 1);
                        setNavigationStack(ns);
                        const last = ns[ns.length - 1];
                        setCurrentView(last.view);
                        if (last.view !== 'home') navigateTo(last.view, last.title, last.params);
                      }
                    }}>
                    {nav.title}
                  </span>
                </React.Fragment>
              ))}
            </div>
          )}
          <div className="flex-1" />
          {navigationStack.length > 1 && (
            <button onClick={goBack}
              className="text-xs px-3 py-1 bg-white/5 hover:bg-white/10 text-hifi-silver/70 hover:text-white rounded-lg transition-colors ml-2">
              {t('common.back')}
            </button>
          )}
        </div>

        {renderLibraryContent()}
      </div>
    );
  };

  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <div className="h-screen w-screen flex overflow-hidden bg-hifi-dark font-display">

      {/* ══════════════════ LEFT — NOW PLAYING (340px) ══════════════════ */}
      <div className="w-[340px] flex-shrink-0 flex flex-col bg-hifi-panel overflow-hidden">

        {/* Brand header */}
        <div className="flex items-center justify-between px-4 h-10 shrink-0 border-b border-hifi-border/60">
          <div className="flex items-center space-x-2">
            <div className="w-2 h-2 rounded-full bg-hifi-gold shadow-[0_0_6px_rgba(212,175,55,0.8)]" />
            <span className="text-[11px] font-bold tracking-[0.18em] text-hifi-silver/80 uppercase select-none">
              Osmium Sound
            </span>
          </div>
          <div className="flex items-center space-x-2">
            {isConnected && activePlayer && (
              <span className="text-[10px] text-hifi-silver/50 truncate max-w-[90px]">
                {activePlayer.name || activePlayer.playerid}
              </span>
            )}
            <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-500' : 'bg-red-500/70'}`} />
            {activePlayer && (
              <button onClick={() => setIsPlayerExpanded(true)}
                className="p-1 text-hifi-silver/40 hover:text-hifi-silver transition-colors rounded" title={t('player.expand')}>
                <Maximize2 size={13} />
              </button>
            )}
          </div>
        </div>

        {/* Spacer (centers now-playing block vertically) */}
        <div className="flex-1 min-h-0" />

        {/* Artwork */}
        <div className="flex justify-center px-5 pt-2 pb-3 shrink-0">
          <div
            className="relative w-[250px] h-[250px] rounded-2xl overflow-hidden shadow-[0_8px_40px_rgba(0,0,0,0.7)] border border-white/5 cursor-pointer group bg-hifi-gray flex-shrink-0"
            onClick={() => activePlayer && setIsPlayerExpanded(true)}>
            {artworkUrl && (
              <div className="artwork-glow" style={{ backgroundImage: `url(${artworkUrl})` }} />
            )}
            <ArtworkImage src={artworkUrl} alt="Album Art" className="w-full h-full object-cover relative z-10" FallbackIcon={Music} />
            {activePlayer && (
              <div className="absolute inset-0 z-20 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity rounded-2xl">
                <Maximize2 size={26} className="text-white drop-shadow-lg" />
              </div>
            )}
          </div>
        </div>

        {/* Track info */}
        <div className="px-4 pb-1 shrink-0">
          <div className="flex items-start">
            <h2 className="text-[15px] font-bold text-white line-clamp-2 leading-tight flex-1">
              {title}
            </h2>
            {isPlaying && <PlayingBars />}
          </div>
          <p className="text-[13px] text-hifi-gold truncate mt-0.5 font-medium">{artist}</p>
          {album && <p className="text-[12px] text-hifi-silver/60 truncate">{album}</p>}
          {formatLabel && (
            <span className="inline-block mt-1 px-2 py-0.5 bg-white/5 text-[10px] text-hifi-silver/50 rounded border border-white/5 tracking-wide">
              {formatLabel}
            </span>
          )}
        </div>

        {/* Progress */}
        <div className="px-4 pt-1 pb-0.5 shrink-0">
          <div className="flex justify-between text-[10px] text-hifi-silver/50 mb-1 font-mono">
            <span>{formatTime(time)}</span>
            <span>{formatTime(duration)}</span>
          </div>
          <div className="relative h-[3px] bg-white/8 rounded-full overflow-hidden cursor-pointer group"
            onClick={(e) => {
              if (!duration || !activePlayer) return;
              const r = e.currentTarget.getBoundingClientRect();
              handleAction(() => lyrionApi.seek(activePlayer.playerid, duration * ((e.clientX - r.left) / r.width)));
            }}>
            <div className="absolute inset-0 bg-white/5 rounded-full" />
            <motion.div className="absolute top-0 left-0 h-full bg-gradient-to-r from-hifi-gold to-yellow-400 rounded-full"
              style={{ width: `${progress}%` }} />
          </div>
        </div>

        {/* Transport controls */}
        <div className="flex items-center justify-center space-x-3 px-4 py-1.5 shrink-0">
          <motion.button whileHover={{ scale: 1.12 }} whileTap={{ scale: 0.88 }}
            onClick={() => handleAction(() => lyrionApi.previous(activePlayer?.playerid))}
            className="w-10 h-10 flex items-center justify-center text-hifi-silver hover:text-white rounded-full hover:bg-white/8 transition-colors">
            <SkipBack size={19} />
          </motion.button>

          <motion.button whileHover={{ scale: 1.06 }} whileTap={{ scale: 0.94 }}
            onClick={() => handleAction(() => lyrionApi.togglePause(activePlayer?.playerid))}
            className="w-[52px] h-[52px] flex items-center justify-center bg-hifi-gold text-black rounded-full shadow-[0_0_18px_rgba(212,175,55,0.35)] hover:shadow-[0_0_28px_rgba(212,175,55,0.55)] transition-all">
            {isPlaying
              ? <Pause size={20} fill="currentColor" />
              : <Play size={20} fill="currentColor" className="ml-0.5" />}
          </motion.button>

          <motion.button whileHover={{ scale: 1.12 }} whileTap={{ scale: 0.88 }}
            onClick={() => handleAction(() => lyrionApi.next(activePlayer?.playerid))}
            className="w-10 h-10 flex items-center justify-center text-hifi-silver hover:text-white rounded-full hover:bg-white/8 transition-colors">
            <SkipForward size={19} />
          </motion.button>
        </div>

        {/* Secondary controls: shuffle / repeat / queue / sleep */}
        <div className="flex items-center justify-center space-x-5 px-4 pb-1 shrink-0">
          <button onClick={cycleShuffle} disabled={!activePlayer} title={t('player.shuffle')}
            className={`p-1.5 rounded-full transition-colors disabled:opacity-30 ${shuffleMode > 0 ? 'text-hifi-gold' : 'text-hifi-silver/50 hover:text-hifi-silver'}`}>
            <Shuffle size={16} />
          </button>
          <button onClick={cycleRepeat} disabled={!activePlayer} title={t('player.repeat')}
            className={`p-1.5 rounded-full transition-colors disabled:opacity-30 ${repeatMode > 0 ? 'text-hifi-gold' : 'text-hifi-silver/50 hover:text-hifi-silver'}`}>
            {repeatMode === 1 ? <Repeat1 size={16} /> : <Repeat size={16} />}
          </button>
          <button onClick={openQueue} disabled={!activePlayer} title={t('player.queue')}
            className="p-1.5 rounded-full text-hifi-silver/50 hover:text-hifi-silver transition-colors disabled:opacity-30">
            <ListMusic size={16} />
          </button>
          <button onClick={() => setSleepMenuOpen(true)} disabled={!activePlayer} title={t('player.sleep')}
            className={`p-1.5 rounded-full transition-colors disabled:opacity-30 ${willSleepIn > 0 ? 'text-hifi-gold' : 'text-hifi-silver/50 hover:text-hifi-silver'}`}>
            <Moon size={16} />
          </button>
        </div>

        {/* Volume */}
        <div className="flex items-center space-x-2 px-4 py-1 shrink-0">
          <button
            onClick={() => handleAction(() => lyrionApi.setVolume(activePlayer?.playerid, volume === 0 ? 50 : 0))}
            className="text-hifi-silver/60 hover:text-hifi-silver transition-colors flex-shrink-0">
            {volume === 0 ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </button>
          <input type="range" min="0" max="100" value={volume}
            className="vol-slider flex-1"
            onChange={(e) => {
              const v = parseInt(e.target.value);
              setPlayerStatus(prev => ({ ...prev, mixer_volume: v }));
              handleAction(() => lyrionApi.setVolume(activePlayer?.playerid, v));
            }} />
          <span className="text-[10px] text-hifi-silver/40 w-6 text-right font-mono flex-shrink-0">{volume}</span>
        </div>

        {/* Spacer (balances vertical centering; VU meters live in fullscreen view) */}
        <div className="flex-1 min-h-0" />
      </div>

      {/* Panel divider */}
      <div className="panel-divider" />

      {/* ══════════════════ RIGHT — CONTENT (flex-1) ══════════════════ */}
      <div className="flex-1 flex flex-col overflow-hidden bg-hifi-dark min-w-0">

        {/* Tab bar */}
        <div className="flex shrink-0 border-b border-hifi-border bg-hifi-panel/50 overflow-x-auto">
          {TABS.map(({ id, labelKey, Icon }) => {
            const active = activeTab === id;
            return (
              <button key={id} onClick={() => handleTabSwitch(id)}
                className={`relative flex items-center space-x-1.5 px-4 py-3 text-xs font-medium whitespace-nowrap transition-colors flex-shrink-0
                  ${active ? 'text-white' : 'text-hifi-silver/50 hover:text-hifi-silver'}`}>
                <Icon size={14} />
                {labelKey && <span>{t(labelKey)}</span>}
                {active && (
                  <span className="absolute bottom-0 left-2 right-2 h-[2px] bg-hifi-gold rounded-t-sm" />
                )}
              </button>
            );
          })}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-hidden flex flex-col">
          <AnimatePresence mode="wait">
            <motion.div key={activeTab}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.12 }}
              className="flex-1 flex flex-col overflow-hidden">
              {renderTabContent()}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      {/* ══════════════════ FULLSCREEN NOW PLAYING (portal) ══════════════════ */}
      {createPortal(
        <AnimatePresence>
          {isPlayerExpanded && (
            <motion.div
              initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }}
              transition={{ type: 'spring', damping: 26, stiffness: 200 }}
              className="fixed inset-0 z-50 flex flex-col bg-hifi-dark overflow-hidden">

              {/* Blurred art background */}
              <div className="absolute inset-0 opacity-20 bg-cover bg-center blur-3xl scale-125 pointer-events-none transition-all duration-1000"
                style={{ backgroundImage: artworkUrlLg ? `url(${artworkUrlLg})` : 'none' }} />
              <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/60 to-transparent pointer-events-none" />

              {/* Close button row */}
              <div className="relative z-40 flex items-center justify-between px-5 pt-3 pb-1 shrink-0">
                <button onClick={() => setIsPlayerExpanded(false)}
                  className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors">
                  <ChevronDown size={22} />
                </button>
                <p className="text-[10px] tracking-[0.25em] text-hifi-silver/70 uppercase">{t('player.nowPlaying')}</p>
                <div className="flex items-center space-x-2">
                  <button onClick={openQueue} title={t('player.queue')}
                    className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors">
                    <ListMusic size={18} />
                  </button>
                  <button onClick={() => setSleepMenuOpen(true)} title={t('player.sleep')}
                    className={`p-2 rounded-full transition-colors ${willSleepIn > 0 ? 'bg-hifi-gold/30 text-hifi-gold' : 'bg-white/10 hover:bg-white/20 text-white'}`}>
                    <Moon size={18} />
                  </button>
                </div>
              </div>

              {/* Body: artwork (left) | info + controls + VU (right) */}
              <div className="relative z-40 flex-1 flex flex-row items-stretch px-5 pb-5 gap-6 min-h-0">

                {/* Left: artwork */}
                <motion.div className="w-[44%] flex items-center justify-center flex-shrink-0"
                  initial={{ x: -20, opacity: 0 }} animate={{ x: 0, opacity: 1 }} transition={{ delay: 0.08 }}>
                  <div className="relative w-full max-w-[320px] aspect-square rounded-2xl overflow-hidden shadow-[0_20px_60px_rgba(0,0,0,0.7)] border border-white/8 bg-hifi-gray">
                    {artworkUrlLg
                      ? <img src={safeUrl(artworkUrlLg)} alt="Album Art" className="w-full h-full object-cover" />
                      : <div className="w-full h-full flex items-center justify-center text-hifi-silver/20"><Music size={80} /></div>}
                  </div>
                </motion.div>

                {/* Right: info + progress + controls + VU */}
                <motion.div className="flex-1 flex flex-col min-w-0 justify-center py-1"
                  initial={{ x: 20, opacity: 0 }} animate={{ x: 0, opacity: 1 }} transition={{ delay: 0.12 }}>

                  {/* Track info */}
                  <div className="mb-2 shrink-0">
                    <div className="flex items-start">
                      <h2 className="text-2xl font-bold text-white leading-tight line-clamp-2 flex-1">{title}</h2>
                      {isPlaying && <PlayingBars />}
                    </div>
                    <p className="text-lg text-hifi-gold truncate mt-0.5 font-medium">{artist}</p>
                    <p className="text-sm text-hifi-silver/70 truncate">{album}</p>
                    {formatLabel && (
                      <span className="inline-block mt-1 px-2 py-0.5 bg-white/5 text-[10px] text-hifi-silver/50 rounded border border-white/5 tracking-wide">
                        {formatLabel}
                      </span>
                    )}
                  </div>

                  {/* Progress */}
                  <div className="w-full mb-3 shrink-0">
                    <div className="flex justify-between text-xs text-hifi-silver/60 font-mono mb-1.5">
                      <span>{formatTime(time)}</span>
                      <span>{formatTime(duration)}</span>
                    </div>
                    <div className="relative h-1.5 bg-white/10 rounded-full overflow-hidden cursor-pointer"
                      onClick={(e) => {
                        if (!duration || !activePlayer) return;
                        const r = e.currentTarget.getBoundingClientRect();
                        handleAction(() => lyrionApi.seek(activePlayer.playerid, duration * ((e.clientX - r.left) / r.width)));
                      }}>
                      <motion.div className="absolute top-0 left-0 h-full bg-gradient-to-r from-hifi-gold to-yellow-400 rounded-full"
                        style={{ width: `${progress}%` }} />
                    </div>
                  </div>

                  {/* Controls row */}
                  <div className="flex items-center space-x-3 mb-3 shrink-0 min-w-0">
                    <button onClick={cycleShuffle} title={t('player.shuffle')}
                      className={`shrink-0 transition-colors ${shuffleMode > 0 ? 'text-hifi-gold' : 'text-hifi-silver/60 hover:text-white'}`}>
                      <Shuffle size={18} />
                    </button>

                    <motion.button whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }}
                      className="shrink-0 text-hifi-silver hover:text-white transition-colors"
                      onClick={() => handleAction(() => lyrionApi.previous(activePlayer?.playerid))}>
                      <SkipBack size={24} />
                    </motion.button>

                    <motion.button whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
                      className="shrink-0 w-14 h-14 flex items-center justify-center bg-hifi-gold text-black rounded-full shadow-[0_0_24px_rgba(212,175,55,0.4)] hover:shadow-[0_0_36px_rgba(212,175,55,0.65)] transition-all"
                      onClick={() => handleAction(() => lyrionApi.togglePause(activePlayer?.playerid))}>
                      {isPlaying ? <Pause size={26} fill="currentColor" /> : <Play size={26} fill="currentColor" className="ml-1" />}
                    </motion.button>

                    <motion.button whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }}
                      className="shrink-0 text-hifi-silver hover:text-white transition-colors"
                      onClick={() => handleAction(() => lyrionApi.next(activePlayer?.playerid))}>
                      <SkipForward size={24} />
                    </motion.button>

                    <button onClick={cycleRepeat} title={t('player.repeat')}
                      className={`shrink-0 transition-colors ${repeatMode > 0 ? 'text-hifi-gold' : 'text-hifi-silver/60 hover:text-white'}`}>
                      {repeatMode === 1 ? <Repeat1 size={18} /> : <Repeat size={18} />}
                    </button>

                    {/* Volume (inline) — flexible width so it never gets clipped */}
                    <div className="flex items-center space-x-2 ml-auto min-w-0 flex-1 max-w-[180px]">
                      <button onClick={() => handleAction(() => lyrionApi.setVolume(activePlayer?.playerid, volume === 0 ? 50 : 0))}
                        className="shrink-0 text-hifi-silver/70 hover:text-hifi-silver transition-colors">
                        {volume === 0 ? <VolumeX size={17} /> : <Volume2 size={17} />}
                      </button>
                      <input type="range" min="0" max="100" value={volume}
                        className="min-w-0 flex-1 h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer accent-hifi-gold"
                        onChange={(e) => {
                          const v = parseInt(e.target.value);
                          setPlayerStatus(prev => ({ ...prev, mixer_volume: v }));
                          handleAction(() => lyrionApi.setVolume(activePlayer?.playerid, v));
                        }} />
                    </div>
                  </div>

                  {/* VU Meters — large, fills remaining vertical space */}
                  <div className="flex-1 min-h-0">
                    <AnalogVUMeter isPlaying={isPlaying} className="w-full h-full" />
                  </div>
                </motion.div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}

      {/* ══════════════════ QUEUE DRAWER (portal) ══════════════════ */}
      {createPortal(
        <AnimatePresence>
          {showQueue && (
            <motion.div className="fixed inset-0 z-[60] flex justify-end"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="absolute inset-0 bg-black/60" onClick={() => setShowQueue(false)} />
              <motion.div
                initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
                transition={{ type: 'spring', damping: 28, stiffness: 240 }}
                className="relative w-[400px] max-w-[85vw] h-full bg-hifi-panel border-l border-hifi-border flex flex-col shadow-2xl">

                {/* Header */}
                <div className="flex items-center justify-between px-4 h-12 shrink-0 border-b border-hifi-border">
                  <div className="flex items-center space-x-2">
                    <ListMusic size={16} className="text-hifi-gold" />
                    <span className="text-sm font-semibold text-white">{t('player.queue')}</span>
                    <span className="text-[11px] text-hifi-silver/50">({queue.length})</span>
                  </div>
                  <button onClick={() => setShowQueue(false)}
                    className="p-1.5 text-hifi-silver/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
                    <X size={16} />
                  </button>
                </div>

                {/* List */}
                <div className="flex-1 overflow-y-auto content-scrollbar px-2 py-2">
                  {queue.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-hifi-silver/40 text-sm">
                      {t('player.queueEmpty')}
                    </div>
                  ) : (
                    <ul className="space-y-1">
                      {queue.map((item, idx) => {
                        const isCur = idx === queueIndex;
                        return (
                          <li key={`${item.id || item.url || idx}-${idx}`}
                            className={`flex items-center px-2 py-2 rounded-lg group transition-colors ${isCur ? 'bg-hifi-gold/15 border border-hifi-gold/30' : 'bg-hifi-surface hover:bg-hifi-light border border-transparent'}`}>
                            <button onClick={() => queueJump(idx)}
                              className="flex items-center min-w-0 flex-1 text-left">
                              <span className={`w-6 text-center text-[11px] font-mono flex-shrink-0 ${isCur ? 'text-hifi-gold' : 'text-hifi-silver/40'}`}>
                                {isCur ? '▶' : idx + 1}
                              </span>
                              <div className="min-w-0 ml-1">
                                <p className={`text-sm truncate ${isCur ? 'text-white font-medium' : 'text-white/90'}`}>
                                  {item.title || item.track || '—'}
                                </p>
                                <p className="text-[11px] text-hifi-silver/50 truncate">
                                  {item.artist || t('player.unknownArtist')}
                                </p>
                              </div>
                            </button>
                            <div className="flex items-center opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                              <button onClick={() => queueMove(idx, idx - 1)} disabled={idx === 0}
                                className="p-1 text-hifi-silver/50 hover:text-white disabled:opacity-20">
                                <ArrowUp size={13} />
                              </button>
                              <button onClick={() => queueMove(idx, idx + 1)} disabled={idx === queue.length - 1}
                                className="p-1 text-hifi-silver/50 hover:text-white disabled:opacity-20">
                                <ArrowDown size={13} />
                              </button>
                              <button onClick={() => queueRemove(idx)}
                                className="p-1 text-hifi-silver/50 hover:text-red-400">
                                <Trash2 size={13} />
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>

                {/* Footer actions */}
                <div className="flex items-center gap-2 px-3 py-3 border-t border-hifi-border shrink-0">
                  <button onClick={() => { setQueueName(''); setSaveQueueOpen(true); }}
                    disabled={queue.length === 0}
                    className="flex-1 flex items-center justify-center gap-2 bg-hifi-surface hover:bg-hifi-light disabled:opacity-40 text-white py-2.5 rounded-lg text-sm transition-colors border border-hifi-border">
                    <Save size={15} /> {t('player.saveAsPlaylist')}
                  </button>
                  <button onClick={queueClear} disabled={queue.length === 0}
                    className="flex items-center justify-center gap-2 bg-red-500/10 hover:bg-red-500/20 disabled:opacity-40 text-red-300 px-4 py-2.5 rounded-lg text-sm transition-colors border border-red-500/20">
                    <Trash2 size={15} /> {t('player.clearQueue')}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}

      {/* ══════════════════ SAVE QUEUE DIALOG (portal) ══════════════════ */}
      {createPortal(
        <AnimatePresence>
          {saveQueueOpen && (
            <motion.div className="fixed inset-0 z-[70] flex items-center justify-center p-6"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="absolute inset-0 bg-black/70" onClick={() => setSaveQueueOpen(false)} />
              <motion.div initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.92, opacity: 0 }}
                className="relative w-full max-w-sm bg-hifi-panel border border-hifi-border rounded-2xl p-5 shadow-2xl">
                <p className="text-sm font-semibold text-white mb-3">{t('player.saveAsPlaylist')}</p>
                <input type="text" value={queueName} autoFocus
                  onChange={(e) => { setQueueName(e.target.value); setSaveMsg(''); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') saveQueue(); }}
                  placeholder={t('player.playlistNamePlaceholder')}
                  className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-3 text-white focus:outline-none focus:border-hifi-gold mb-4" />
                {saveMsg && (
                  <p className="text-sm text-red-300 mb-3 text-center">{saveMsg}</p>
                )}
                <div className="flex gap-2">
                  <button onClick={() => { setSaveQueueOpen(false); setSaveMsg(''); }}
                    className="flex-1 bg-hifi-light hover:bg-hifi-accent text-white py-2.5 rounded-lg text-sm font-medium transition-colors">
                    {t('common.cancel')}
                  </button>
                  <button onClick={saveQueue} disabled={!queueName.trim()}
                    className="flex-1 bg-hifi-gold hover:bg-yellow-600 disabled:opacity-40 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
                    {t('common.confirm')}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}

      {/* ══════════════════ SLEEP TIMER MENU (portal) ══════════════════ */}
      {createPortal(
        <AnimatePresence>
          {sleepMenuOpen && (
            <motion.div className="fixed inset-0 z-[70] flex items-center justify-center p-6"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="absolute inset-0 bg-black/70" onClick={() => setSleepMenuOpen(false)} />
              <motion.div initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.92, opacity: 0 }}
                className="relative w-full max-w-xs bg-hifi-panel border border-hifi-border rounded-2xl p-5 shadow-2xl">
                <div className="flex items-center space-x-2 mb-3">
                  <Moon size={16} className="text-hifi-gold" />
                  <p className="text-sm font-semibold text-white">{t('player.sleep')}</p>
                </div>
                {willSleepIn > 0 && (
                  <p className="text-[12px] text-hifi-gold mb-3">
                    {t('player.sleepActive', { min: Math.ceil(willSleepIn / 60) })}
                  </p>
                )}
                <div className="grid grid-cols-3 gap-2 mb-3">
                  {[15, 30, 45, 60, 90, 120].map((m) => (
                    <button key={m} onClick={() => setSleepTimer(m)}
                      className="py-2.5 bg-hifi-surface hover:bg-hifi-light text-white rounded-lg text-sm transition-colors border border-hifi-border">
                      {m}m
                    </button>
                  ))}
                </div>
                <button onClick={() => setSleepTimer(0)}
                  className="w-full py-2.5 bg-red-500/10 hover:bg-red-500/20 text-red-300 rounded-lg text-sm transition-colors border border-red-500/20">
                  {t('player.sleepOff')}
                </button>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body
      )}
    </div>
  );
};

export default LyrionServer;
