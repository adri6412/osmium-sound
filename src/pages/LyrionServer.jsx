import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Play, Pause, SkipBack, SkipForward,
  Volume2, VolumeX, Music, AlertCircle, RefreshCw,
  Folder, User, Disc, Home, ChevronRight, ChevronDown, ChevronUp,
  Radio, AppWindow, Compass,
  Settings as SettingsIcon, Maximize2,
  Shuffle, Repeat, Repeat1, ListMusic, Moon,
  Trash2, X, Save, GripVertical, ListPlus, ListStart,
  Mic2, AudioLines, Heart, Search
} from 'lucide-react';
import { lyrionApi } from '../utils/lyrionApi';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';
import AnalogVUMeter from '../components/AnalogVUMeter';
import LedBar from '../components/LedBar';
import CdRip from '../components/CdRip';
import Discover from '../components/Discover';
import ContextMenu from '../components/ContextMenu';
import { useLongPress } from '../hooks/useLongPress';
import { SCALED_CANVAS_ID } from '../components/ScaledCanvas';
import SettingsPage from './Settings';
import { useLyrionPlayer, safeUrl, formatTime, LIST_PAGE } from '../hooks/useLyrionPlayer';

// ── Tab definitions ──────────────────────────────────────────
// `labelKey` is resolved through i18n at render time (null = icon-only tab).
const TABS = [
  { id: 'musica',   labelKey: 'player.tabs.music',    Icon: Music },
  { id: 'radio',    labelKey: 'player.tabs.radio',    Icon: Radio },
  { id: 'apps',     labelKey: 'player.tabs.apps',     Icon: AppWindow },
  { id: 'scopri',   labelKey: 'player.tabs.discover', Icon: Compass },
  { id: 'settings', labelKey: null,                   Icon: SettingsIcon },
];

// ── Artwork with error fallback ───────────────────────────────
// For a remote/radio track, the cover URL gets a fresh cache-buster every
// ~10s (see the trackKey/heartbeat comment in useLyrionPlayer.js) even
// though the artwork itself is usually unchanged — swapping the visible
// <img>'s src straight to the new URL forced the browser to blank it out
// for the fetch+decode gap, a real one-frame-per-heartbeat white flash
// confirmed on camera during steady playback. Preload the new URL in a
// background Image() and only swap the visible <img> once it's actually
// ready, so the old (still valid) artwork keeps showing with zero gap.
// A load failure gets one retry, shortly after, before falling back to the
// generic icon — a station that genuinely has no art still ends up there,
// just one retry later.
const ARTWORK_RETRY_MS = 2000;
// A cover-art fetch with no AbortController/timeout that gets "superseded" by
// a newer poll only stops being *looked at* (requestIdRef mismatch) — the
// underlying network request keeps running against LMS regardless. Over
// hours of ~10s heartbeat polling that piles up abandoned-but-live requests
// and can exhaust the browser's per-origin connection pool, at which point
// even a brand-new station/track's fetch queues behind the dead ones and the
// art appears permanently stuck. Same fix already applied to the JSON-RPC
// client for the same reason, see lyrionApi.js's request().
const ARTWORK_FETCH_TIMEOUT_MS = 8000;
const ArtworkImage = ({ src, alt, className, FallbackIcon }) => {
  const safeSrc = src ? safeUrl(src) : null;
  const [displayedSrc, setDisplayedSrc] = useState(safeSrc);
  const [err, setErr] = useState(!safeSrc);
  const loaderRef = useRef(null); // in-flight preloader; guards stale onload/onerror from an abandoned load

  useEffect(() => {
    if (!safeSrc) {
      loaderRef.current = null;
      setDisplayedSrc(null);
      setErr(true);
      return;
    }
    const attemptLoad = (isRetry) => {
      const img = new Image();
      loaderRef.current = img;
      img.onload = () => {
        if (loaderRef.current !== img) return;
        setDisplayedSrc(safeSrc);
        setErr(false);
      };
      img.onerror = () => {
        if (loaderRef.current !== img) return;
        if (!isRetry) setTimeout(() => { if (loaderRef.current === img) attemptLoad(true); }, ARTWORK_RETRY_MS);
        else setErr(true);
      };
      img.src = safeSrc;
    };
    attemptLoad(false);
    return () => { loaderRef.current = null; };
  }, [safeSrc]);

  if (err || !displayedSrc) {
    return (
      <div className="absolute inset-0 flex items-center justify-center text-hifi-silver/20 bg-gradient-to-br from-hifi-gray to-hifi-dark">
        <FallbackIcon size={40} />
      </div>
    );
  }
  // loading="lazy" so an album grid with hundreds of covers only fetches the
  // ones scrolled into view; harmless here since displayedSrc is only ever
  // set once already loaded (served from cache on the actual <img> mount).
  return <img src={displayedSrc} alt={alt} className={className} loading="lazy" decoding="async" />;
};

// Fast non-cryptographic hash (FNV-1a) over raw bytes — only needs to detect
// "same content as last time", not resist tampering.
const fnv1aHash = (bytes) => {
  let h = 0x811c9dc5;
  for (let i = 0; i < bytes.length; i++) {
    h ^= bytes[i];
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
};

// Cover art for the "now playing" view (mini-player + fullscreen), for
// *remote* tracks only (radio/Qobuz/Tidal/on-demand plugins) — local tracks
// have a stable DB id and just use <ArtworkImage> directly with the static,
// race-free /music/{id}/cover URL (see useLyrionPlayer's artworkUrl), the
// same one the library browse grid already uses without this class of bug.
//
// Remote tracks have no such id: the URL is LMS's stateful
// /music/current/cover.jpg, re-keyed by useLyrionPlayer's trackKey, which
// bundles two very different kinds of change:
//   - `identityKey` changes: LMS told us something concrete changed
//     (id/title/artist/album/current_title) — a *confirmed* track change.
//   - heartbeat-only changes: a coarse ~10s poll to catch on-demand plugins
//     (Qobuz/Tidal "radio" mixes) that silently advance to a new song
//     without updating any of the above — a *probe*, not a confirmation.
// Those two need different handling: on a confirmed change, the art on
// screen is now known-stale and must not linger — hold a loading state
// instead. On a probe, there's no evidence anything's actually wrong, so the
// current art stays up and only gets swapped if the refetched bytes hash
// differently (still fetch+hash+dedupe here rather than trusting the URL:
// the cache-buster changes every heartbeat even when the art is
// byte-identical, and swapping the <img>/backgroundImage to a
// freshly-fetched-but-identical resource was still enough to cause a
// visible flash on this hardware).
const usePolledArtwork = (url, identityKey) => {
  const safeSrc = url ? safeUrl(url) : null;
  const [objectUrl, setObjectUrl] = useState(null);
  const [failed, setFailed] = useState(!safeSrc);
  const hashRef = useRef(null);
  const objectUrlRef = useRef(null);
  const requestIdRef = useRef(0);
  const controllerRef = useRef(null);
  // Sentinel (not a value identityKey can ever equal) so the very first
  // fetch after mount is always treated as a confirmed change — it gets the
  // full retry budget, same as any other genuine track change, rather than
  // being mistaken for a probe on an already-showing (nonexistent) cover.
  const lastIdentityRef = useRef(Symbol('initial'));

  useEffect(() => {
    const isConfirmedChange = identityKey !== lastIdentityRef.current;
    lastIdentityRef.current = identityKey;

    if (!safeSrc) {
      requestIdRef.current += 1;
      hashRef.current = null;
      if (objectUrlRef.current) { URL.revokeObjectURL(objectUrlRef.current); objectUrlRef.current = null; }
      setObjectUrl(null);
      setFailed(true);
      return;
    }
    const myRequestId = ++requestIdRef.current;

    if (isConfirmedChange) {
      // LMS told us this is a different track than what's on screen — that
      // art is now known-wrong. Drop it immediately instead of leaving a
      // confidently-wrong image up while the replacement loads.
      hashRef.current = null;
      if (objectUrlRef.current) { URL.revokeObjectURL(objectUrlRef.current); objectUrlRef.current = null; }
      setObjectUrl(null);
      setFailed(false); // loading, not failed yet
    }

    // Confirmed changes retry harder: LMS resizes cover art itself
    // (Image::Scale, a native Perl module) on demand, which can genuinely
    // take several seconds on a loaded/slower box (squeezelite/CamillaDSP
    // sharing the CPU) — worth waiting out before giving up to the
    // placeholder. A heartbeat probe has no evidence anything changed, so it
    // isn't worth hammering retries over — one retry and move on to the next
    // probe cycle.
    const MAX_ATTEMPTS = isConfirmedChange ? 6 : 2;
    const attempt = async (attemptNum) => {
      const controller = new AbortController();
      controllerRef.current = controller;
      const timer = setTimeout(() => controller.abort(), ARTWORK_FETCH_TIMEOUT_MS);
      try {
        const res = await fetch(safeSrc, { signal: controller.signal });
        if (!res.ok) throw new Error(`http ${res.status}`);
        const buf = await res.arrayBuffer();
        if (requestIdRef.current !== myRequestId) return; // superseded by a newer poll
        const hash = fnv1aHash(new Uint8Array(buf));
        setFailed(false);
        if (hash === hashRef.current) return; // identical cover — no DOM change at all
        const nextObjectUrl = URL.createObjectURL(new Blob([buf]));
        const prevObjectUrl = objectUrlRef.current;
        hashRef.current = hash;
        objectUrlRef.current = nextObjectUrl;
        setObjectUrl(nextObjectUrl);
        if (prevObjectUrl) URL.revokeObjectURL(prevObjectUrl);
      } catch {
        if (requestIdRef.current !== myRequestId) return;
        if (attemptNum < MAX_ATTEMPTS) {
          setTimeout(() => { if (requestIdRef.current === myRequestId) attempt(attemptNum + 1); }, ARTWORK_RETRY_MS);
        } else if (isConfirmedChange) {
          // Every retry failed on a track we know changed — this isn't a
          // one-off blip. Fall back to the placeholder icon instead of
          // leaving a stale (or already-cleared) image up indefinitely.
          hashRef.current = null;
          if (objectUrlRef.current) { URL.revokeObjectURL(objectUrlRef.current); objectUrlRef.current = null; }
          setObjectUrl(null);
          setFailed(true);
        }
        // A failed probe (not a confirmed change) leaves the current art
        // exactly as-is — there's no evidence it's wrong, so there's nothing
        // to correct until the next probe or a confirmed change.
      } finally {
        clearTimeout(timer);
      }
    };
    attempt(1);
    // Actually cancel the in-flight request (not just ignore its result) the
    // moment it's superseded — by a newer heartbeat/track (effect re-run) or
    // by this instance going away — instead of leaving it running to eat a
    // connection slot. See ARTWORK_FETCH_TIMEOUT_MS above for why this matters.
    return () => { if (controllerRef.current) controllerRef.current.abort(); };
  }, [safeSrc, identityKey]);

  // Release the last object URL when this instance goes away entirely.
  useEffect(() => () => { if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current); }, []);

  return { objectUrl, failed };
};

// Accent/case-insensitive normalization, shared by the artist/album search
// filter and the A-Z index's per-letter bucketing below.
// \p{Mn} = Unicode "nonspacing mark" category — matches the combining accent
// marks left behind by NFD decomposition (é → e + ́), so this strips accents
// without hardcoding a specific Unicode code-point range.
const normalize = (s) => (s || '').normalize('NFD').replace(/\p{Mn}/gu, '').toLowerCase();

// ── A-Z quick-jump sidebar (artists/albums only) ────────────────
// Touch-friendly like iOS Contacts: tap a letter, or drag vertically across
// the strip to "scrub" through letters without lifting the finger.
const AZ_LETTERS = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')];
const AzIndex = ({ items, keyField, onJump }) => {
  // First index at which each letter starts, in the already-sorted `items`.
  const letterIndex = React.useMemo(() => {
    const map = {};
    items.forEach((item, idx) => {
      const raw = normalize(item[keyField] || '');
      const ch = raw ? raw[0].toUpperCase() : '';
      const letter = /[A-Z]/.test(ch) ? ch : '#';
      if (!(letter in map)) map[letter] = idx;
    });
    return map;
  }, [items, keyField]);

  const stripRef = React.useRef(null);
  const lastLetterRef = React.useRef(null);
  // Which letter the finger/pointer is currently over, and its vertical
  // position (0-1) — drives the big magnified callout below. 27 discrete
  // targets in ~450px of a 1024x600 panel are individually finger-sized no
  // matter the font (~16px each), so precision comes from continuously
  // dragging while watching a large readout, not from landing exactly on a
  // tiny label — the same trick iOS Contacts uses for the same reason.
  const [activeLetter, setActiveLetter] = React.useState(null);
  const [activeRatio, setActiveRatio] = React.useState(0);

  const handlePoint = (clientY) => {
    const el = stripRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientY - r.top) / r.height));
    const idx = Math.min(AZ_LETTERS.length - 1, Math.floor(ratio * AZ_LETTERS.length));
    const letter = AZ_LETTERS[idx];
    setActiveLetter(letter);
    setActiveRatio((idx + 0.5) / AZ_LETTERS.length);
    if (letter === lastLetterRef.current) return; // avoid re-jumping every pixel of a drag
    lastLetterRef.current = letter;
    if (letter in letterIndex) onJump(letterIndex[letter]);
  };
  const endTouch = () => { setActiveLetter(null); lastLetterRef.current = null; };

  return (
    <div ref={stripRef}
      className="relative flex flex-col items-center justify-between w-8 shrink-0 select-none py-1"
      style={{ touchAction: 'none' }}
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); handlePoint(e.clientY); }}
      onPointerMove={(e) => { if (e.buttons === 1 || e.pointerType === 'touch') handlePoint(e.clientY); }}
      onPointerUp={endTouch}
      onPointerCancel={endTouch}
      onLostPointerCapture={endTouch}>
      {AZ_LETTERS.map((letter) => (
        <span key={letter}
          className={`text-[10px] font-bold leading-none transition-colors ${
            letter === activeLetter ? 'text-hifi-gold' : letter in letterIndex ? 'text-hifi-silver/70' : 'text-hifi-silver/20'}`}>
          {letter}
        </span>
      ))}
      {activeLetter && (
        <div className="absolute right-full mr-2 -translate-y-1/2 w-12 h-12 flex items-center justify-center rounded-full bg-hifi-gold text-black text-xl font-bold shadow-lg pointer-events-none"
          style={{ top: `${activeRatio * 100}%` }}>
          {activeLetter}
        </div>
      )}
    </div>
  );
};

// ── Track row with long-press context menu (Musica tab track lists) ────
// A dedicated component (not inline in the .map()) because useLongPress is a
// hook — it needs one call per mounted row instance, which only works if
// each row is its own component (a hook call inside the parent's .map()
// callback would violate the rules of hooks as the list length changes).
// Memoized, and takes onPlay/onOpenMenu called with the track id/coords from
// inside rather than pre-bound per-row closures, so a stable function
// reference can be shared across all rows (see call site) instead of a fresh
// closure being created for every row on every rebuild of the library list.
const TrackRow = React.memo(({ item, onPlay, onOpenMenu }) => {
  const { handlers, didLongPress } = useLongPress((x, y) => onOpenMenu(x, y, item));
  return (
    <li {...handlers}
      onClick={() => { if (didLongPress()) return; onPlay(item.id); }}
      className="flex items-center px-3 py-3 bg-hifi-surface hover:bg-hifi-light active:bg-hifi-light rounded-lg cursor-pointer border border-transparent hover:border-hifi-border transition-colors select-none">
      <Music size={13} className="text-hifi-silver/60 mr-3 flex-shrink-0" />
      <span className="text-sm text-white truncate">{item.title}</span>
    </li>
  );
});

// ── Queue drawer row: drag handle to reorder, swipe-left to remove ─────
// Reordering needs to shuffle SIBLING rows too, so the drag handle reports
// start/move/end up to the parent (which owns `queue`/`queueOverride`) via
// props rather than managing array order itself. Swipe-to-remove only ever
// affects this one row, so that gesture stays fully local. Pointer capture on
// the handle keeps routing move/up events to it for the whole drag even as
// the finger crosses over other rows — exactly the behavior a reorder needs.
// Memoized + takes the stable, non-curried actions (onJump/onRemove called
// with idx/uid from inside, rather than pre-bound closures per row) so the
// parent can pass the SAME function reference to every row across renders —
// letting React.memo actually skip re-rendering rows the 1s playback-poll
// tick (or an unrelated row's drag) doesn't affect.
const QueueRow = React.memo(({ item, idx, isCurrent, unknownArtistLabel, onJump, onRemove, onDragStart, onDragMove, onDragEnd }) => {
  const rowRef = useRef(null);
  const [swipeX, setSwipeX] = useState(0);
  const swipeStartRef = useRef(null); // {x,y} while a candidate gesture is being watched
  const swipingRef = useRef(false);   // true once horizontal intent is confirmed
  const didSwipeRef = useRef(false);  // suppresses the tap-to-jump click after a swipe

  const onRowPointerDown = (e) => {
    if (e.target.closest('[data-drag-handle]')) return;
    swipeStartRef.current = { x: e.clientX, y: e.clientY };
    swipingRef.current = false;
    didSwipeRef.current = false;
  };
  const onRowPointerMove = (e) => {
    const start = swipeStartRef.current;
    if (!start) return;
    const dx = e.clientX - start.x;
    const dy = e.clientY - start.y;
    if (!swipingRef.current) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (Math.abs(dx) <= Math.abs(dy)) { swipeStartRef.current = null; return; } // vertical → leave it to native scroll
      swipingRef.current = true;
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    didSwipeRef.current = true;
    setSwipeX(Math.min(0, dx)); // left-only swipe to reveal/commit remove
  };
  const endSwipe = (e) => {
    if (!swipingRef.current) { swipeStartRef.current = null; return; }
    swipingRef.current = false;
    swipeStartRef.current = null;
    if (swipeX < -96) onRemove(item._uid);
    else setSwipeX(0);
  };

  return (
    <li className="relative overflow-hidden rounded-lg">
      <div className="absolute inset-0 flex items-center justify-end pr-4 bg-red-500/20">
        <Trash2 size={16} className="text-red-300" />
      </div>
      <motion.div
        ref={rowRef}
        layout="position"
        transition={{ type: 'tween', duration: 0.18 }}
        onPointerDown={onRowPointerDown}
        onPointerMove={onRowPointerMove}
        onPointerUp={endSwipe}
        onPointerCancel={endSwipe}
        style={{ touchAction: 'pan-y', transform: `translateX(${swipeX}px)` }}
        onClick={() => { if (!didSwipeRef.current) onJump(idx); }}
        className={`relative flex items-center px-2 py-2 rounded-lg transition-colors ${isCurrent ? 'bg-hifi-gold/15 border border-hifi-gold/30' : 'bg-hifi-surface border border-transparent'}`}>
        <span data-drag-handle
          onPointerDown={(e) => {
            e.stopPropagation();
            e.currentTarget.setPointerCapture(e.pointerId);
            onDragStart(idx, e.clientY);
          }}
          onPointerMove={(e) => { e.stopPropagation(); onDragMove(e.clientY, rowRef.current); }}
          onPointerUp={(e) => { e.stopPropagation(); onDragEnd(rowRef.current); }}
          onPointerCancel={(e) => { e.stopPropagation(); onDragEnd(rowRef.current); }}
          style={{ touchAction: 'none' }}
          className="p-2 -ml-1 mr-0.5 text-hifi-silver/40 active:text-white cursor-grab flex-shrink-0">
          <GripVertical size={15} />
        </span>
        <span className={`w-6 text-center text-[11px] font-mono flex-shrink-0 ${isCurrent ? 'text-hifi-gold' : 'text-hifi-silver/40'}`}>
          {isCurrent ? '▶' : idx + 1}
        </span>
        <div className="min-w-0 ml-1 flex-1">
          <p className={`text-sm truncate ${isCurrent ? 'text-white font-medium' : 'text-white/90'}`}>
            {item.title || item.track || '—'}
          </p>
          <p className="text-[11px] text-hifi-silver/50 truncate">
            {item.artist || unknownArtistLabel}
          </p>
        </div>
      </motion.div>
    </li>
  );
});

// ── Main component ────────────────────────────────────────────
// Kiosk-only: the PWA build has its own screens (src/pages/pwa/) and does not
// mount this component. All LMS control state/logic lives in useLyrionPlayer
// (shared with those PWA screens) — this component owns only kiosk-specific
// UI-open state and the two-pane desktop presentation.
const LyrionServer = () => {
  const { t } = useI18n();
  const {
    serverUrl, isConnected, activePlayer, error, isLoading,
    connectToServer, handleAction,
    currentTrack, title, artist, album, isPlaying, volume, repeatMode, shuffleMode,
    willSleepIn, duration, time, progress, artworkUrl, artworkUrlLg, formatLabel,
    playbackMode,
    isRemoteTrack, artworkIdentityKey,
    setVolume: setPlayerVolume, toggleMute, seek, cycleShuffle, cycleRepeat,
    setSleepTimer: applySleepTimer,
    queue, queueIndex, loadQueue, queueJump, queueRemove, queueMove, queueClear,
    queueAddTrack, queuePlayNext,
    saveQueue: saveQueueToLms,
    currentView, libraryData, libraryLoading, visibleCount, setVisibleCount, navigationStack,
    menuSearch, setMenuSearch, searchText, setSearchText, menuBase,
    listScrollRef, handleLibraryScroll,
    navigateTo, goBack, goHome, goToBreadcrumb, handlePlayItem,
    resolveMenuIcon, handleMenuItem, submitMenuSearch, openTabView,
  } = useLyrionPlayer();

  // Now-playing cover, remote-track case only: hash-deduped, shared by the
  // mini-player's <img> + glow background and the fullscreen <img> + blurred
  // backdrop below — see usePolledArtwork's own comment. One fetch per poll
  // tick per size, reused for both the image and its background twin instead
  // of fetching twice. Local tracks skip this hook entirely and render
  // <ArtworkImage> directly off the static per-id URL further down.
  const npArtwork = usePolledArtwork(isRemoteTrack ? artworkUrl : null, artworkIdentityKey);
  const npArtworkLg = usePolledArtwork(isRemoteTrack ? artworkUrlLg : null, artworkIdentityKey);

  // `handlePlayItem` is a plain function redefined on every useLyrionPlayer()
  // call (every 1s playback-poll tick, not wrapped in useCallback there), so
  // anything that needs a PERMANENTLY stable "play this id" callback (to let
  // React.memo'd rows like TrackRow actually skip re-rendering) routes
  // through this ref instead of closing over handlePlayItem directly.
  const handlePlayItemRef = useRef(handlePlayItem);
  handlePlayItemRef.current = handlePlayItem;
  const playTrackById = React.useCallback((id) => handlePlayItemRef.current('track_id', id), []);

  // ── Kiosk-only UI state (not part of the shared hook) ──────
  const [isPlayerExpanded, setIsPlayerExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState('musica');
  // Lets something outside Settings (the global "USB detected" prompt in
  // App.jsx) jump straight to a Settings sub-section — Settings.jsx has no
  // props/route otherwise, since this app has no router. Consumed once by
  // SettingsPage on mount, then cleared here so re-entering Settings later
  // (without a fresh event) lands back on the section list as normal.
  const [pendingSettingsSection, setPendingSettingsSection] = useState(null);
  useEffect(() => {
    const handler = (e) => { setActiveTab('settings'); setPendingSettingsSection(e.detail || null); };
    window.addEventListener('hifi-open-settings-section', handler);
    return () => window.removeEventListener('hifi-open-settings-section', handler);
  }, []);
  const [showQueue, setShowQueue] = useState(false);
  const [saveQueueOpen, setSaveQueueOpen] = useState(false);
  const [queueName, setQueueName] = useState('');
  const [saveMsg, setSaveMsg] = useState('');

  // ── Queue drawer: drag-to-reorder + swipe-to-remove (kiosk-only) ──
  // `queueOverride`, when set, is the optimistic local order shown instead of
  // `queue` while a drag/swipe is in flight — avoids a rubber-band snap-back
  // while waiting for the LMS round-trip that `queueMove`/`queueRemove`
  // trigger. `dragRef` tracks the in-progress drag without re-rendering on
  // every pointermove; only crossing into a new target slot touches state.
  const [queueOverride, setQueueOverride] = useState(null);
  const displayQueue = queueOverride || queue;
  const dragRef = useRef({ uid: null, originalIdx: null, lastTarget: null });

  // queueMove/queueJump/queueRemove come from useLyrionPlayer() and, like
  // handlePlayItem above, are recreated every 1s poll tick — routed through
  // refs so the useCallback-wrapped functions below (and jumpToQueueIndex)
  // can stay permanently stable without depending on them directly.
  const queueMoveRef = useRef(queueMove);
  queueMoveRef.current = queueMove;
  const queueRemoveRef = useRef(queueRemove);
  queueRemoveRef.current = queueRemove;
  const queueJumpRef = useRef(queueJump);
  queueJumpRef.current = queueJump;
  const jumpToQueueIndex = React.useCallback((idx) => queueJumpRef.current(idx), []);

  const startQueueDrag = React.useCallback((idx, clientY) => {
    const list = queueOverride || queue;
    dragRef.current = { uid: list[idx]?._uid, originalIdx: idx, lastTarget: idx, startY: clientY };
    if (!queueOverride) setQueueOverride(list);
  }, [queue, queueOverride]);
  // Only depends on `queue` (the fallback) — the in-progress override is read
  // via the functional setQueueOverride updater's `prev`, not closed over
  // directly, so this stays referentially stable for the whole drag gesture
  // (called on every pointermove) instead of changing every time the
  // override itself changes.
  const moveQueueDrag = React.useCallback((clientY, rowEl) => {
    const d = dragRef.current;
    if (d.uid == null) return;
    const deltaY = clientY - d.startY;
    if (rowEl) rowEl.style.transform = `translateY(${deltaY}px)`;
    const rowH = rowEl?.offsetHeight || 56;
    const rawTarget = d.originalIdx + Math.round(deltaY / rowH);
    setQueueOverride((prev) => {
      const list = prev || queue;
      const target = Math.min(Math.max(rawTarget, 0), list.length - 1);
      if (target === d.lastTarget) return prev;
      const from = list.findIndex((it) => it._uid === d.uid);
      if (from === -1 || from === target) { d.lastTarget = target; return prev; }
      const next = list.slice();
      const [moved] = next.splice(from, 1);
      next.splice(target, 0, moved);
      d.lastTarget = target;
      return next;
    });
  }, [queue]);
  const endQueueDrag = React.useCallback((rowEl) => {
    const d = dragRef.current;
    if (rowEl) rowEl.style.transform = '';
    const from = d.originalIdx;
    dragRef.current = { uid: null, originalIdx: null, lastTarget: null };
    if (from == null) { setQueueOverride(null); return; }
    const list = queueOverride || queue;
    const to = list.findIndex((it) => it._uid === d.uid);
    if (to === -1 || to === from) { setQueueOverride(null); return; }
    queueMoveRef.current(from, to).then(() => setQueueOverride(null));
  }, [queue, queueOverride]);
  const removeQueueItem = React.useCallback((uid) => {
    const list = queueOverride || queue;
    const idx = list.findIndex((it) => it._uid === uid);
    if (idx === -1) return;
    setQueueOverride(list.filter((it) => it._uid !== uid));
    queueRemoveRef.current(idx).then(() => setQueueOverride(null));
  }, [queue, queueOverride]);

  // ── Track long-press context menu (kiosk-only) ─────────────────
  const [contextMenu, setContextMenu] = useState(null); // { x, y, item } | null
  const openTrackContextMenu = React.useCallback((x, y, item) => setContextMenu({ x, y, item }), []);

  // ── Artists/Albums search + A-Z jump (kiosk-only, presentation state) ──
  // The search box is deliberately UNCONTROLLED (defaultValue + a ref, not
  // value={...}): filtering re-sorts/re-filters the FULL library (up to 9999
  // items, see fetchViewData) and rebuilds every visible row, and that
  // rebuild is gated behind the `libraryContent` useMemo below. If the input
  // were a controlled field feeding that same memoized tree, every keystroke
  // would have to bust the memo just to reflect the typed character — which
  // defeats the memo (full re-sort/re-render per keystroke, the single most
  // expensive re-render path in this screen on weaker iGPUs). Uncontrolled
  // means the browser owns the visible text natively; only the debounced
  // value (committed ~200ms after typing pauses) feeds the memo/filtering.
  const libFilterInputRef = useRef(null);
  const libFilterTimerRef = useRef(null);
  const [libFilterDebounced, setLibFilterDebounced] = useState('');
  const onLibFilterChange = (e) => {
    const val = e.target.value;
    clearTimeout(libFilterTimerRef.current);
    libFilterTimerRef.current = setTimeout(() => setLibFilterDebounced(val), 200);
  };
  const clearLibFilter = () => {
    if (libFilterInputRef.current) libFilterInputRef.current.value = '';
    clearTimeout(libFilterTimerRef.current);
    setLibFilterDebounced('');
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { clearLibFilter(); }, [currentView, navigationStack.length]);
  // Jump the progressive-render window past `idx` so the target row is
  // actually mounted, then scroll it into view once the DOM reflects that.
  const jumpToIndex = (idx) => {
    setVisibleCount(c => Math.max(c, idx + LIST_PAGE));
    requestAnimationFrame(() => {
      listScrollRef.current?.querySelector(`[data-az-index="${idx}"]`)?.scrollIntoView({ block: 'start' });
    });
  };
  const [sleepMenuOpen, setSleepMenuOpen] = useState(false);

  const openQueue = () => { setShowQueue(true); loadQueue(); };

  const handleSaveQueue = async () => {
    setSaveMsg('');
    const result = await saveQueueToLms(queueName);
    if (!result.success) { setSaveMsg(result.error || t('player.saveError')); return; }
    setSaveQueueOpen(false);
    setQueueName('');
    setShowQueue(false);
    setIsPlayerExpanded(false);
    setActiveTab('musica');
  };

  const setSleepTimer = (minutes) => {
    setSleepMenuOpen(false);
    applySleepTimer(minutes);
  };

  // ── Tab switch ─────────────────────────────────────────────
  const handleTabSwitch = (tabId) => {
    setActiveTab(tabId);
    openTabView(tabId);
  };

  // ── Now-playing panel: VU meters ⇄ lyrics toggle ────────────
  // 'vu' | 'lyrics'; persisted so the choice survives navigation/reloads.
  // The VU meter itself can be disabled from Settings (GPU cost on weak
  // iGPUs) — in that case this view always resolves to lyrics.
  const [vuMeterEnabled, setVuMeterEnabled] = useState(
    localStorage.getItem('hifiVuMeterEnabled') !== 'false'
  );
  useEffect(() => {
    // The localStorage value above is just a same-device cache — it can be
    // stale if the preference was last changed remotely (companion app / web
    // admin on a headless unit) rather than from this Settings page. Refresh
    // from api_server on mount, then keep polling: this view normally stays
    // mounted for the whole kiosk session, so without polling a remote
    // toggle would never reach the on-screen display until next reboot —
    // the 'hifi-vu-meter-enabled' event below only fires for a toggle made
    // from this same Electron process's own Settings page.
    let alive = true;
    const refresh = () => systemAPI.getVuMeter().then((res) => {
      if (alive && res.success && typeof res.data?.enabled === 'boolean') {
        setVuMeterEnabled(res.data.enabled);
        localStorage.setItem('hifiVuMeterEnabled', res.data.enabled ? 'true' : 'false');
      }
    });
    refresh();
    const poll = setInterval(refresh, 5000);
    const onChange = (e) => setVuMeterEnabled(!!e.detail);
    window.addEventListener('hifi-vu-meter-enabled', onChange);
    return () => { alive = false; clearInterval(poll); window.removeEventListener('hifi-vu-meter-enabled', onChange); };
  }, []);

  // Now-playing auto-expand: same fetch-on-mount + poll + broadcast-event
  // shape as vuMeterEnabled above (see its comment for why the poll exists).
  const [autoExpandSeconds, setAutoExpandSeconds] = useState(
    Number(localStorage.getItem('hifiNowPlayingAutoExpandSeconds')) || 0
  );
  useEffect(() => {
    let alive = true;
    const refresh = () => systemAPI.getNowPlayingAutoExpand().then((res) => {
      if (alive && res.success && typeof res.data?.seconds === 'number') {
        setAutoExpandSeconds(res.data.seconds);
        localStorage.setItem('hifiNowPlayingAutoExpandSeconds', String(res.data.seconds));
      }
    });
    refresh();
    const poll = setInterval(refresh, 5000);
    const onChange = (e) => setAutoExpandSeconds(Number(e.detail) || 0);
    window.addEventListener('hifi-nowplaying-autoexpand-changed', onChange);
    return () => { alive = false; clearInterval(poll); window.removeEventListener('hifi-nowplaying-autoexpand-changed', onChange); };
  }, []);
  // Song this auto-expand feature has already acted on (auto-opened for, OR
  // the user manually dismissed while it was playing) — either way, don't
  // touch isPlayerExpanded again until a *different* song starts. Ref, not
  // state: this must never itself trigger a re-render/re-schedule.
  const autoExpandHandledKeyRef = useRef(null);
  useEffect(() => {
    if (!isPlaying || !autoExpandSeconds || !activePlayer) return;
    if (autoExpandHandledKeyRef.current === artworkIdentityKey) return;
    const timer = setTimeout(() => {
      autoExpandHandledKeyRef.current = artworkIdentityKey;
      setIsPlayerExpanded(true);
    }, autoExpandSeconds * 1000);
    return () => clearTimeout(timer);
  }, [isPlaying, artworkIdentityKey, autoExpandSeconds, activePlayer]);
  // Manual collapse (the ChevronDown close button) counts as "the user moved
  // away on purpose" — mark this song handled so a still-pending timer (user
  // closed before it fired) can't pop the view back open on its own.
  const collapsePlayer = () => {
    autoExpandHandledKeyRef.current = artworkIdentityKey;
    setIsPlayerExpanded(false);
  };

  const [nowPlayingView, setNowPlayingView] = useState(
    localStorage.getItem('hifiNowPlayingView') === 'lyrics' ? 'lyrics' : 'vu'
  );
  const effectiveNowPlayingView = vuMeterEnabled ? nowPlayingView : 'lyrics';
  // undefined = not fetched yet, null = no lyrics found, string = lyrics text
  const [lyricsText, setLyricsText] = useState(undefined);
  const toggleNowPlayingView = () => {
    setNowPlayingView((v) => {
      const next = v === 'vu' ? 'lyrics' : 'vu';
      localStorage.setItem('hifiNowPlayingView', next);
      return next;
    });
  };
  useEffect(() => {
    if (effectiveNowPlayingView !== 'lyrics' || !isPlayerExpanded) return;
    if (!currentTrack.id && !(artist && title)) { setLyricsText(null); return; }
    let cancelled = false;
    setLyricsText(undefined);
    lyrionApi.getLyrics(activePlayer?.playerid, { trackId: currentTrack.id, artist, title })
      .then((text) => { if (!cancelled) setLyricsText(text); });
    return () => { cancelled = true; };
  }, [effectiveNowPlayingView, isPlayerExpanded, currentTrack.id]);

  // ── Library content renderer ───────────────────────────────
  const renderLibraryContent = () => {
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
            { label: t('player.titles.favorites'), Icon: Heart,     action: () => navigateTo('plugin_items', t('player.titles.favorites'), { pluginCmd: 'favorites' }) },
          ].map(({ label, Icon, action }) => (
            <button key={label} onClick={action}
              className="flex flex-col items-center justify-center py-7 bg-hifi-surface hover:bg-hifi-light active:bg-hifi-light rounded-xl border border-hifi-border hover:border-hifi-accent transition-colors">
              <Icon size={30} className="text-hifi-silver mb-2.5" />
              <span className="text-sm font-medium text-white">{label}</span>
            </button>
          ))}
        </div>
      );
    }

    // Artists / Albums: dedicated search box + A-Z quick-jump sidebar. The
    // full result set is already in `libraryData` (fetchViewData always uses
    // limit=9999), so sorting/filtering/indexing are all client-side — no
    // extra network round-trip as the user types or scrubs the sidebar.
    if (currentView === 'artists' || currentView === 'albums') {
      const field = currentView === 'artists' ? 'artist' : 'album';
      const sorted = [...libraryData].sort((a, b) =>
        (a[field] || '').localeCompare(b[field] || '', undefined, { sensitivity: 'base' }));
      const norm = normalize(libFilterDebounced);
      const filtered = norm
        ? sorted.filter((item) => normalize(currentView === 'artists' ? item.artist : `${item.album} ${item.artist || ''}`).includes(norm))
        : sorted;
      const visibleItems = filtered.slice(0, visibleCount);

      const renderRow = (item, idx) => {
        if (currentView === 'albums') {
          const aId  = item.artwork_track_id || item.id;
          const aUrl = aId ? lyrionApi.getArtworkUrl(aId, 200) : null;
          return (
            <div key={item.id || idx} data-az-index={idx}
              onClick={() => navigateTo('tracks', item.album, { albumId: item.id })}
              className="bg-hifi-surface hover:bg-hifi-light rounded-xl overflow-hidden group cursor-pointer border border-hifi-border hover:border-hifi-accent transition-colors">
              <div className="relative aspect-square bg-hifi-gray">
                <ArtworkImage src={aUrl} alt={item.album} className="w-full h-full object-cover" FallbackIcon={Disc} />
                <button onClick={(e) => { e.stopPropagation(); handlePlayItem('album_id', item.id); }}
                  className="absolute bottom-1.5 right-1.5 p-2 flex items-center justify-center bg-black/60 active:bg-hifi-gold active:text-black text-white rounded-full shadow-lg transition-colors">
                  <Play size={14} fill="currentColor" className="ml-0.5" />
                </button>
              </div>
              <div className="p-2">
                <p className="text-white text-xs font-medium truncate">{item.album}</p>
                <p className="text-hifi-silver/70 text-xs truncate">{item.artist}</p>
              </div>
            </div>
          );
        }
        return (
          <li key={item.id ?? idx} data-az-index={idx}
            onClick={() => navigateTo('albums', item.artist, { artistId: item.id })}
            className="flex items-center justify-between px-3 py-3 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
            <div className="flex items-center space-x-3">
              <div className="w-7 h-7 rounded-full bg-hifi-light flex items-center justify-center flex-shrink-0">
                <User size={13} className="text-hifi-silver" />
              </div>
              <span className="text-sm text-white">{item.artist}</span>
            </div>
            <div className="opacity-70 active:opacity-100 transition-opacity">
              <button onClick={(e) => { e.stopPropagation(); handlePlayItem('artist_id', item.id); }}
                className="p-2 flex items-center justify-center bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                <Play size={12} fill="currentColor" className="ml-0.5" />
              </button>
            </div>
          </li>
        );
      };

      return (
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-3 pt-2 pb-1 shrink-0">
            <div className="relative">
              <input
                type="text"
                ref={libFilterInputRef}
                defaultValue=""
                onChange={onLibFilterChange}
                placeholder={t(currentView === 'artists' ? 'player.filterArtistsPlaceholder' : 'player.filterAlbumsPlaceholder')}
                className="hifi-input w-full text-sm py-2 pr-9"
              />
              {libFilterDebounced && (
                <button onClick={clearLibFilter}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-hifi-silver/50 hover:text-white active:text-white transition-colors">
                  <X size={14} />
                </button>
              )}
            </div>
          </div>
          <div className="flex-1 flex overflow-hidden">
            <div ref={listScrollRef} onScroll={handleLibraryScroll}
              className="flex-1 overflow-y-auto content-scrollbar px-3 pb-3">
              {filtered.length === 0 ? (
                <p className="text-center text-hifi-silver/40 text-sm py-8">{t('common.noResults')}</p>
              ) : currentView === 'albums' ? (
                <div className="album-grid grid grid-cols-3 gap-3 pt-1">
                  {visibleItems.map((item, idx) => renderRow(item, idx))}
                </div>
              ) : (
                <ul className="lib-list space-y-1 pt-1">
                  {visibleItems.map((item, idx) => renderRow(item, idx))}
                </ul>
              )}
            </div>
            <AzIndex items={filtered} keyField={field} onJump={jumpToIndex} />
          </div>
        </div>
      );
    }

    const visibleItems = libraryData.slice(0, visibleCount);
    return (
      <div ref={listScrollRef} onScroll={handleLibraryScroll}
        className="flex-1 overflow-y-auto content-scrollbar px-3 pb-3">
        <ul className="lib-list space-y-1 pt-1">
          {visibleItems.map((item, idx) => {
            if (currentView === 'tracks' || currentView === 'playlist_tracks') return (
              <TrackRow key={item.id ?? idx} item={item}
                onPlay={playTrackById}
                onOpenMenu={openTrackContextMenu} />
            );

            if (currentView === 'playlists') return (
              <li key={item.id || idx}
                onClick={() => navigateTo('playlist_tracks', item.playlist, { playlistId: item.id })}
                className="flex items-center justify-between px-3 py-3 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                <div className="flex items-center space-x-3 min-w-0">
                  <div className="w-7 h-7 rounded-lg bg-hifi-light flex items-center justify-center flex-shrink-0">
                    <ListMusic size={14} className="text-hifi-silver" />
                  </div>
                  <span className="text-sm text-white truncate">{item.playlist}</span>
                </div>
                <div className="opacity-70 active:opacity-100 transition-opacity flex-shrink-0">
                  <button onClick={(e) => { e.stopPropagation(); handlePlayItem('playlist_id', item.id); }}
                    className="p-2 flex items-center justify-center bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                    <Play size={12} fill="currentColor" className="ml-0.5" />
                  </button>
                </div>
              </li>
            );

            if (currentView === 'folders') {
              const isDir = item.type === 'folder';
              return (
                <li key={idx}
                  onClick={() => isDir ? navigateTo('folders', item.filename, { folderId: item.id }) : handlePlayItem('track_id', item.id)}
                  className="flex items-center justify-between px-3 py-3 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
                  <div className="flex items-center space-x-3 min-w-0">
                    {isDir
                      ? <Folder size={15} className="text-hifi-gold flex-shrink-0" />
                      : <Music size={15} className="text-hifi-silver/60 flex-shrink-0" />}
                    <span className="text-sm text-white truncate">{item.filename || item.title}</span>
                  </div>
                  <div className="opacity-70 active:opacity-100 transition-opacity flex-shrink-0">
                    <button onClick={(e) => { e.stopPropagation(); handlePlayItem(isDir ? 'folder_id' : 'track_id', item.id); }}
                      className="p-2 flex items-center justify-center bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                      <Play size={12} fill="currentColor" className="ml-0.5" />
                    </button>
                  </div>
                </li>
              );
            }

            if (currentView === 'radios' || currentView === 'apps') return (
              <li key={idx}
                onClick={() => navigateTo('plugin_items', item.name, { pluginCmd: item.cmd })}
                className="flex items-center px-3 py-3 bg-hifi-surface hover:bg-hifi-light rounded-lg cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
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
              const base = menuBase;
              const play = lyrionApi.resolveMenuAction(base, item, 'play')
                || lyrionApi.resolveMenuAction(base, item, 'playall');
              const isNav = !!(lyrionApi.resolveMenuAction(base, item, 'go') || item.input);
              return (
                <li key={item.id || idx}
                  onClick={() => handleMenuItem(item)}
                  className="flex items-center justify-between px-3 py-3 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
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
                    <div className="opacity-70 active:opacity-100 transition-opacity flex-shrink-0">
                      <button onClick={(e) => { e.stopPropagation(); handleAction(() => lyrionApi.menuDo(activePlayer.playerid, play)); }}
                        className="p-2 flex items-center justify-center bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                        <Play size={12} fill="currentColor" className="ml-0.5" />
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
                  className="flex items-center justify-between px-3 py-3 bg-hifi-surface hover:bg-hifi-light rounded-lg group cursor-pointer border border-transparent hover:border-hifi-border transition-colors">
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
                    <div className="opacity-70 active:opacity-100 transition-opacity flex-shrink-0">
                      <button onClick={(e) => { e.stopPropagation(); handleAction(() => lyrionApi.playPluginItem(activePlayer.playerid, pluginCmd, item.id || item.play)); }}
                        className="p-2 flex items-center justify-center bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors">
                        <Play size={12} fill="currentColor" className="ml-0.5" />
                      </button>
                    </div>
                  )}
                </li>
              );
            }

            return null;
          })}
        </ul>
      </div>
    );
  };

  // Memoise the library list so it is NOT rebuilt on every status poll (1s while
  // playing). The list only depends on the values below — notably NOT on
  // playerStatus — so excluding it stops the per-second re-render that made
  // scrolling a big album grid stutter. activePlayer is keyed by playerid so the
  // item click handlers (which capture it) refresh when the player changes.
  const libraryContent = React.useMemo(
    renderLibraryContent,
    [libraryLoading, currentView, libraryData,
     visibleCount, navigationStack, activePlayer?.playerid, serverUrl, t, libFilterDebounced]
  );

  // ── Right-panel content ────────────────────────────────────
  // Settings/Discover are wrapped in React.memo (see their own files) so the
  // 1s playback-poll re-render doesn't reach them — that only works if the
  // props handed to them don't change identity every render too, hence the
  // stable callbacks below (handlePlayItemRef declared up top, near the hook).
  const handleSettingsSectionConsumed = React.useCallback(() => setPendingSettingsSection(null), []);
  const handleDiscoverPlayArtist = React.useCallback((id) => handlePlayItemRef.current('artist_id', id), []);
  const renderTabContent = () => {
    if (activeTab === 'settings') {
      return (
        <SettingsPage
          initialSection={pendingSettingsSection}
          onSectionConsumed={handleSettingsSectionConsumed}
        />
      );
    }
    if (activeTab === 'scopri') return (
      <Discover playerMac={activePlayer?.playerid} artist={currentTrack.artist}
        onPlayArtist={handleDiscoverPlayArtist} />
    );

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
        {activeTab === 'musica' && <CdRip />}
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
                        goToBreadcrumb(idx);
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

        {/* Persistent search bar (Qobuz/Tidal-style) for any Lyrion menu node
            that needs text input (RadioNet station search, global Search, …).
            Stays open across submits — see submitMenuSearch — instead of the
            old one-shot modal that closed (and lost the query) as soon as you
            searched. */}
        {menuSearch && (
          <div className="flex items-center gap-2 px-3 py-2 border-b border-hifi-border/50 shrink-0 bg-hifi-panel/40">
            <Search size={15} className="text-hifi-silver/50 flex-shrink-0" />
            <input
              type="text"
              autoFocus
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') submitMenuSearch(); }}
              placeholder={menuSearch.title || t('player.searchPlaceholder')}
              className="flex-1 min-w-0 bg-hifi-dark border border-hifi-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-hifi-gold"
            />
            <button onClick={submitMenuSearch} disabled={!searchText.trim()}
              className="p-1.5 bg-hifi-gold/20 text-hifi-gold rounded-lg hover:bg-hifi-gold hover:text-black disabled:opacity-40 disabled:hover:bg-hifi-gold/20 disabled:hover:text-hifi-gold transition-colors flex-shrink-0"
              title={t('common.search')}>
              <Search size={15} />
            </button>
            <button onClick={() => { setMenuSearch(null); setSearchText(''); }}
              className="p-1.5 text-hifi-silver/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors flex-shrink-0"
              title={t('common.cancel')}>
              <X size={15} />
            </button>
          </div>
        )}

        {libraryContent}
      </div>
    );
  };

  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <div className="h-full w-full flex overflow-hidden bg-hifi-dark font-display">
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
              <button onClick={() => setIsPlayerExpanded(true)} title={t('player.expand')}
                className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors">
                <ChevronUp size={22} />
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
            {isRemoteTrack ? (
              <>
                {npArtwork.objectUrl && (
                  <div className="artwork-glow" style={{ backgroundImage: `url(${npArtwork.objectUrl})` }} />
                )}
                {npArtwork.failed || !npArtwork.objectUrl ? (
                  <div className="absolute inset-0 flex items-center justify-center text-hifi-silver/20 bg-gradient-to-br from-hifi-gray to-hifi-dark">
                    <Music size={40} />
                  </div>
                ) : (
                  // key=identity: on some weak-iGPU kiosks (reported: Intel Gemini
                  // Lake; not reproduced on a VM or an older Intel box) Chromium's
                  // compositor has been seen to leave the PREVIOUS track's pixels
                  // on screen after only the <img> src attribute changes — the
                  // element itself never got a new paint layer. Forcing a real
                  // DOM remount (a fresh <img>, not an attribute mutation on the
                  // same node) on every confirmed track change sidesteps that,
                  // at the cost of a brief blank frame instead of a silently
                  // wrong cover.
                  <img key={artworkIdentityKey} src={npArtwork.objectUrl} alt="Album Art" className="w-full h-full object-cover relative z-10" decoding="async" />
                )}
              </>
            ) : (
              <>
                {artworkUrl && (
                  <div className="artwork-glow" style={{ backgroundImage: `url(${artworkUrl})` }} />
                )}
                <ArtworkImage key={artworkIdentityKey} src={artworkUrl} alt="Album Art" className="w-full h-full object-cover relative z-10" FallbackIcon={Music} />
              </>
            )}
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
              const r = e.currentTarget.getBoundingClientRect();
              seek((e.clientX - r.left) / r.width);
            }}>
            <div className="absolute inset-0 bg-white/5 rounded-full" />
            {/* scaleX, not width: this repaints every 1s from the playback
                poll while playing, and animating `width` makes each tick a
                real layout reflow (tracked as a CLS shift even though the
                element is `absolute` and moves no siblings) — a 2-minute
                track alone accounted for ~120 of the shifts behind a 0.51
                CLS score seen live. transform never touches layout. */}
            <motion.div className="absolute top-0 left-0 w-full h-full bg-gradient-to-r from-hifi-gold to-yellow-400 rounded-full"
              style={{ scaleX: progress / 100, transformOrigin: 'left' }} />
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
            onClick={toggleMute}
            className="text-hifi-silver/60 hover:text-hifi-silver transition-colors flex-shrink-0">
            {volume === 0 ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </button>
          <input type="range" min="0" max="100" value={volume}
            className="vol-slider flex-1"
            onChange={(e) => setPlayerVolume(parseInt(e.target.value))} />
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
              className="absolute inset-0 z-50 flex flex-col bg-hifi-dark overflow-hidden">

              {/* Blurred art background. Kept as a cheap-ish `blur-lg` (not the
                  original blur-3xl): this div covers the whole canvas, and
                  since the canvas is zoomed to fill the real screen, a large
                  blur radius here means a much bigger Gaussian kernel over a
                  much bigger painted area — costly to rasterize on the
                  slide-up entrance transition (translateY), especially on
                  weak/virtualized GPUs (e.g. VMware SVGA in the test VM). */}
              <div className="absolute inset-0 opacity-20 bg-cover bg-center blur-lg scale-125 pointer-events-none transition-all duration-1000"
                style={{ backgroundImage: (isRemoteTrack ? npArtworkLg.objectUrl : artworkUrlLg) ? `url(${isRemoteTrack ? npArtworkLg.objectUrl : artworkUrlLg})` : 'none' }} />
              <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/60 to-transparent pointer-events-none" />

              {/* Close button row */}
              <div className="relative z-40 flex items-center justify-between px-5 pt-3 pb-1 shrink-0">
                <button onClick={collapsePlayer}
                  className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors">
                  <ChevronDown size={22} />
                </button>
                <p className="text-[10px] tracking-[0.25em] text-hifi-silver/70 uppercase">{t('player.nowPlaying')}</p>
                <div className="flex items-center space-x-2">
                  {vuMeterEnabled && (
                    <button onClick={toggleNowPlayingView}
                      title={nowPlayingView === 'vu' ? t('player.lyrics') : t('player.vuMeters')}
                      className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors">
                      {nowPlayingView === 'vu' ? <Mic2 size={18} /> : <AudioLines size={18} />}
                    </button>
                  )}
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

                {/* Left: artwork + LED status bar */}
                <motion.div className="w-[44%] flex items-center justify-center flex-shrink-0"
                  initial={{ x: -20, opacity: 0 }} animate={{ x: 0, opacity: 1 }} transition={{ delay: 0.08 }}>
                  <div className="w-full flex flex-col items-center gap-8">
                    <div className="relative w-full max-w-[320px] aspect-square rounded-2xl overflow-hidden shadow-[0_20px_60px_rgba(0,0,0,0.7)] border border-white/8 bg-hifi-gray">
                      {isRemoteTrack ? (
                        npArtworkLg.failed || !npArtworkLg.objectUrl ? (
                          <div className="absolute inset-0 flex items-center justify-center text-hifi-silver/20 bg-gradient-to-br from-hifi-gray to-hifi-dark">
                            <Music size={40} />
                          </div>
                        ) : (
                          // key=identity — see the mini-player artwork's own comment
                          // (same weak-iGPU stale-compositor workaround).
                          <img key={artworkIdentityKey} src={npArtworkLg.objectUrl} alt="Album Art" className="w-full h-full object-cover" decoding="async" />
                        )
                      ) : (
                        <ArtworkImage key={artworkIdentityKey} src={artworkUrlLg} alt="Album Art" className="w-full h-full object-cover" FallbackIcon={Music} />
                      )}
                    </div>
                    <LedBar mode={playbackMode} formatLabel={formatLabel} className="w-full max-w-[330px]" />
                  </div>
                </motion.div>

                {/* Right: info + progress + controls + VU */}
                <motion.div className="flex-1 flex flex-col min-w-0 justify-center py-1"
                  initial={{ x: 20, opacity: 0 }} animate={{ x: 0, opacity: 1 }} transition={{ delay: 0.12 }}>

                  {/* Track info */}
                  <div className="mb-2 shrink-0">
                    <div className="flex items-start">
                      <h2 className="text-2xl font-bold text-white leading-tight line-clamp-2 flex-1">{title}</h2>
                    </div>
                    <p className="text-lg text-hifi-gold truncate mt-0.5 font-medium">{artist}</p>
                    <p className="text-sm text-hifi-silver/70 truncate">{album}</p>
                  </div>

                  {/* Progress */}
                  <div className="w-full mb-3 shrink-0">
                    <div className="flex justify-between text-xs text-hifi-silver/60 font-mono mb-1.5">
                      <span>{formatTime(time)}</span>
                      <span>{formatTime(duration)}</span>
                    </div>
                    <div className="relative h-1.5 bg-white/10 rounded-full overflow-hidden cursor-pointer"
                      onClick={(e) => {
                        const r = e.currentTarget.getBoundingClientRect();
                        seek((e.clientX - r.left) / r.width);
                      }}>
                      <motion.div className="absolute top-0 left-0 w-full h-full bg-gradient-to-r from-hifi-gold to-yellow-400 rounded-full"
                        style={{ scaleX: progress / 100, transformOrigin: 'left' }} />
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
                      <button onClick={toggleMute}
                        className="shrink-0 text-hifi-silver/70 hover:text-hifi-silver transition-colors">
                        {volume === 0 ? <VolumeX size={17} /> : <Volume2 size={17} />}
                      </button>
                      <input type="range" min="0" max="100" value={volume}
                        className="min-w-0 flex-1 h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer accent-hifi-gold"
                        onChange={(e) => setPlayerVolume(parseInt(e.target.value))} />
                    </div>
                  </div>

                  {/* VU Meters (default) or Lyrics — fills remaining vertical space */}
                  <div className="flex-1 min-h-0">
                    {effectiveNowPlayingView === 'vu' ? (
                      <AnalogVUMeter isPlaying={isPlaying} className="w-full h-full" />
                    ) : (
                      <div className="w-full h-full overflow-y-auto rounded-xl bg-black/20 px-4 py-3">
                        {lyricsText === undefined && (
                          <p className="text-sm text-hifi-silver/50 text-center mt-4">{t('common.loading')}</p>
                        )}
                        {lyricsText === null && (
                          <p className="text-sm text-hifi-silver/50 text-center mt-4">{t('player.lyricsNone')}</p>
                        )}
                        {typeof lyricsText === 'string' && (
                          <p className="text-sm text-white/90 whitespace-pre-line leading-relaxed">{lyricsText}</p>
                        )}
                      </div>
                    )}
                  </div>
                </motion.div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.getElementById(SCALED_CANVAS_ID) || document.body
      )}

      {/* ══════════════════ QUEUE DRAWER (portal) ══════════════════ */}
      {createPortal(
        <AnimatePresence>
          {showQueue && (
            <motion.div className="absolute inset-0 z-[60] flex justify-end"
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
                    <span className="text-[11px] text-hifi-silver/50">({displayQueue.length})</span>
                  </div>
                  <button onClick={() => setShowQueue(false)}
                    className="p-1.5 text-hifi-silver/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
                    <X size={16} />
                  </button>
                </div>

                {/* List */}
                <div className="flex-1 overflow-y-auto content-scrollbar px-2 py-2">
                  {displayQueue.length === 0 ? (
                    <div className="flex items-center justify-center h-full text-hifi-silver/40 text-sm">
                      {t('player.queueEmpty')}
                    </div>
                  ) : (
                    <ul className="space-y-1">
                      {displayQueue.map((item, idx) => (
                        <QueueRow key={item._uid} item={item} idx={idx} isCurrent={idx === queueIndex}
                          unknownArtistLabel={t('player.unknownArtist')}
                          onJump={jumpToQueueIndex}
                          onRemove={removeQueueItem}
                          onDragStart={startQueueDrag} onDragMove={moveQueueDrag} onDragEnd={endQueueDrag} />
                      ))}
                    </ul>
                  )}
                </div>

                {/* Footer actions */}
                <div className="flex items-center gap-2 px-3 py-3 border-t border-hifi-border shrink-0">
                  <button onClick={() => { setQueueName(''); setSaveQueueOpen(true); }}
                    disabled={displayQueue.length === 0}
                    className="flex-1 flex items-center justify-center gap-2 bg-hifi-surface hover:bg-hifi-light disabled:opacity-40 text-white py-2.5 rounded-lg text-sm transition-colors border border-hifi-border">
                    <Save size={15} /> {t('player.saveAsPlaylist')}
                  </button>
                  <button onClick={() => { setQueueOverride(null); queueClear(); }} disabled={displayQueue.length === 0}
                    className="flex items-center justify-center gap-2 bg-red-500/10 hover:bg-red-500/20 disabled:opacity-40 text-red-300 px-4 py-2.5 rounded-lg text-sm transition-colors border border-red-500/20">
                    <Trash2 size={15} /> {t('player.clearQueue')}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.getElementById(SCALED_CANVAS_ID) || document.body
      )}

      {/* ══════════════════ SAVE QUEUE DIALOG (portal) ══════════════════ */}
      {createPortal(
        <AnimatePresence>
          {saveQueueOpen && (
            <motion.div className="absolute inset-0 z-[70] flex items-center justify-center p-6"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="absolute inset-0 bg-black/70" onClick={() => setSaveQueueOpen(false)} />
              <motion.div initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.92, opacity: 0 }}
                className="relative w-full max-w-sm bg-hifi-panel border border-hifi-border rounded-2xl p-5 shadow-2xl">
                <p className="text-sm font-semibold text-white mb-3">{t('player.saveAsPlaylist')}</p>
                <input type="text" value={queueName} autoFocus
                  onChange={(e) => { setQueueName(e.target.value); setSaveMsg(''); }}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSaveQueue(); }}
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
                  <button onClick={handleSaveQueue} disabled={!queueName.trim()}
                    className="flex-1 bg-hifi-gold hover:bg-yellow-600 disabled:opacity-40 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
                    {t('common.confirm')}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.getElementById(SCALED_CANVAS_ID) || document.body
      )}

      {/* ══════════════════ SLEEP TIMER MENU (portal) ══════════════════ */}
      {createPortal(
        <AnimatePresence>
          {sleepMenuOpen && (
            <motion.div className="absolute inset-0 z-[70] flex items-center justify-center p-6"
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
        document.getElementById(SCALED_CANVAS_ID) || document.body
      )}

      {/* ══════════════════ TRACK LONG-PRESS CONTEXT MENU ══════════════════ */}
      <ContextMenu
        open={!!contextMenu}
        anchor={contextMenu}
        onClose={() => setContextMenu(null)}
        items={contextMenu ? [
          { key: 'add', label: t('player.addToQueue'), Icon: ListPlus, onSelect: () => queueAddTrack(contextMenu.item.id) },
          { key: 'next', label: t('player.playNext'), Icon: ListStart, onSelect: () => queuePlayNext(contextMenu.item.id) },
        ] : []}
      />
    </div>
  );
};

export default LyrionServer;
