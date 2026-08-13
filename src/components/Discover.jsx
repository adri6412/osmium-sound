import React, { useState, useEffect, useRef } from 'react';
import { Shuffle, Disc, User, Infinity as InfinityIcon, BookOpen, Play, Filter, Trash2 } from 'lucide-react';
import { lyrionApi } from '../utils/lyrionApi';
import { useI18n } from '../i18n';
import { useKeyboardActions } from '../contexts/KeyboardContext';

// "Discover" tab: endless-mix controls (Random Mix + Don't Stop The Music) and
// context for the current artist (similar artists, biography) via the
// MusicArtistInfo plugin. Every section hides itself when its plugin/data is
// missing, so the tab degrades gracefully on a bare LMS install.
const DSTM_LAST_PROVIDER_KEY = 'hifiDstmLastProvider';

// Saved genre presets for the mix panel: [{ id, name, genres: [string] }].
// App-local only — LMS itself only tracks one live include/exclude state per
// player, not named sets, so presets can't be synced from/to the server.
const MIX_GENRE_PRESETS_KEY = 'hifiMixGenrePresets';

const loadGenrePresets = () => {
  try {
    const raw = JSON.parse(localStorage.getItem(MIX_GENRE_PRESETS_KEY) || '[]');
    return Array.isArray(raw) ? raw : [];
  } catch (_) { return []; }
};

const saveGenrePresets = (presets) => {
  try { localStorage.setItem(MIX_GENRE_PRESETS_KEY, JSON.stringify(presets)); } catch (_) { /* storage full/unavailable */ }
};

const Discover = ({ playerMac, artist, onPlayArtist }) => {
  const { t } = useI18n();
  const { showKeyboard } = useKeyboardActions();
  // undefined = probing, null = plugin missing, string = current provider
  const [dstmProvider, setDstmProvider] = useState(undefined);
  const [dstmBusy, setDstmBusy] = useState(false);
  const [mixMsg, setMixMsg] = useState('');
  const [similar, setSimilar] = useState([]);
  const [libraryArtists, setLibraryArtists] = useState(null); // name(lower) -> id
  const [bio, setBio] = useState(null);
  const [bioOpen, setBioOpen] = useState(false);

  // Genre filter panel for the mix buttons below.
  const [genrePanelOpen, setGenrePanelOpen] = useState(false);
  const [genres, setGenres] = useState(null); // null = not fetched yet
  const [genresLoading, setGenresLoading] = useState(false);
  const [genresError, setGenresError] = useState(false);
  const [genresBusy, setGenresBusy] = useState(false); // toggle/select-all/apply in flight
  const [presets, setPresets] = useState(() => loadGenrePresets());
  const [presetNameDraft, setPresetNameDraft] = useState('');
  const [presetToDelete, setPresetToDelete] = useState(null); // preset id pending confirm
  const presetNameInputRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    if (!playerMac) return undefined;
    lyrionApi.getDstmProvider(playerMac)
      .then((p) => { if (!cancelled) setDstmProvider(p); });
    return () => { cancelled = true; };
  }, [playerMac]);

  // Similar artists + bio for whoever is playing now.
  useEffect(() => {
    let cancelled = false;
    setSimilar([]);
    setBio(null);
    setBioOpen(false);
    if (!artist || artist === t('player.unknownArtist')) return undefined;
    lyrionApi.getSimilarArtists(playerMac, artist)
      .then((list) => { if (!cancelled) setSimilar(list.slice(0, 12)); });
    lyrionApi.getArtistBio(playerMac, artist)
      .then((text) => { if (!cancelled) setBio(text); });
    return () => { cancelled = true; };
  }, [playerMac, artist]);

  // Library artist index, fetched once: lets a similar-artist chip play the
  // artist directly when they're in the local library.
  useEffect(() => {
    let cancelled = false;
    if (!similar.length || libraryArtists) return undefined;
    lyrionApi.getArtists().then((r) => {
      if (cancelled) return;
      const map = {};
      (r?.artists_loop || []).forEach((a) => { map[(a.artist || '').toLowerCase()] = a.id; });
      setLibraryArtists(map);
    }).catch(() => { if (!cancelled) setLibraryArtists({}); });
    return () => { cancelled = true; };
  }, [similar.length, libraryArtists]);

  const startMix = async (mode, msgKey) => {
    setMixMsg('');
    try {
      await lyrionApi.randomPlay(playerMac, mode);
      setMixMsg(t(msgKey));
    } catch (_) {
      setMixMsg(t('player.discover.mixError'));
    }
  };

  // Fetch current genre state whenever the panel opens, so it stays in sync
  // if selection changed elsewhere (e.g. LMS's own web UI) between opens.
  useEffect(() => {
    let cancelled = false;
    if (!genrePanelOpen || !playerMac) return undefined;
    setGenresLoading(true);
    setGenresError(false);
    lyrionApi.getRandomPlayGenres(playerMac)
      .then((list) => { if (!cancelled) setGenres(list); })
      .catch(() => { if (!cancelled) setGenresError(true); })
      .finally(() => { if (!cancelled) setGenresLoading(false); });
    return () => { cancelled = true; };
  }, [genrePanelOpen, playerMac]);

  const toggleGenre = async (genre) => {
    if (genresBusy || !playerMac) return;
    const next = !genre.included;
    setGenresBusy(true);
    setGenres((list) => list.map((g) => (g.name === genre.name ? { ...g, included: next } : g)));
    try {
      await lyrionApi.setRandomPlayGenre(playerMac, genre.name, next);
    } catch (_) {
      setGenres((list) => list.map((g) => (g.name === genre.name ? { ...g, included: !next } : g)));
    }
    setGenresBusy(false);
  };

  const quickSetAllGenres = async (included) => {
    if (genresBusy || !playerMac || !genres) return;
    setGenresBusy(true);
    const prev = genres;
    setGenres((list) => list.map((g) => ({ ...g, included })));
    try {
      await lyrionApi.setAllRandomPlayGenres(playerMac, included);
    } catch (_) {
      setGenres(prev);
    }
    setGenresBusy(false);
  };

  const applyGenrePreset = async (preset) => {
    if (genresBusy || !playerMac) return;
    setGenresBusy(true);
    const prev = genres;
    setGenres((list) => (list || []).map((g) => ({ ...g, included: preset.genres.includes(g.name) })));
    try {
      await lyrionApi.applyRandomPlayGenreSet(playerMac, preset.genres);
    } catch (_) {
      setGenres(prev);
    }
    setGenresBusy(false);
  };

  const saveCurrentAsGenrePreset = () => {
    const name = presetNameDraft.trim();
    if (!name || !genres || !genres.some((g) => g.included)) return;
    const included = genres.filter((g) => g.included).map((g) => g.name);
    const next = [...presets, {
      id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      name, genres: included,
    }];
    setPresets(next);
    saveGenrePresets(next);
    setPresetNameDraft('');
  };

  const deleteGenrePreset = (id) => {
    const next = presets.filter((p) => p.id !== id);
    setPresets(next);
    saveGenrePresets(next);
    setPresetToDelete(null);
  };

  const includedCount = genres ? genres.filter((g) => g.included).length : null;
  const genreFilterLabel = !genres
    ? t('player.discover.genresFilter')
    : includedCount === genres.length
      ? t('player.discover.genresAll')
      : t('player.discover.genresCount', { count: includedCount, total: genres.length });

  const dstmOn = typeof dstmProvider === 'string' && dstmProvider !== '' && dstmProvider !== '0';
  const savedProvider = localStorage.getItem(DSTM_LAST_PROVIDER_KEY) || '';
  const dstmAvailable = dstmProvider !== null && dstmProvider !== undefined;
  const dstmCanEnable = dstmOn || savedProvider !== '';

  const toggleDstm = async () => {
    if (dstmBusy || !playerMac) return;
    setDstmBusy(true);
    try {
      if (dstmOn) {
        localStorage.setItem(DSTM_LAST_PROVIDER_KEY, dstmProvider);
        await lyrionApi.setDstmProvider(playerMac, '');
        setDstmProvider('');
      } else if (savedProvider) {
        await lyrionApi.setDstmProvider(playerMac, savedProvider);
        setDstmProvider(savedProvider);
      }
    } catch (_) { /* leave state as is */ }
    setDstmBusy(false);
  };

  return (
    <div className="flex-1 overflow-y-auto content-scrollbar px-4 py-4 space-y-5">

      {/* ── Endless mixes ── */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold tracking-wider text-hifi-silver/60 uppercase">
            {t('player.discover.mixes')}
          </p>
          <button onClick={() => setGenrePanelOpen((v) => !v)} disabled={!playerMac}
            className="flex items-center gap-1 text-[11px] text-hifi-silver/60 hover:text-hifi-gold disabled:opacity-40">
            <Filter size={13} className={includedCount != null && genres && includedCount < genres.length ? 'text-hifi-gold' : ''} />
            <span>{genreFilterLabel}</span>
          </button>
        </div>

        {genrePanelOpen && (
          <div className="bg-hifi-surface border border-hifi-border rounded-xl p-3 mb-3 space-y-3">
            {genresLoading && <p className="text-xs text-hifi-silver/50">{t('player.discover.genresLoading')}</p>}
            {genresError && <p className="text-xs text-hifi-silver/50">{t('player.discover.genresError')}</p>}
            {genres && genres.length === 0 && !genresLoading && (
              <p className="text-xs text-hifi-silver/40">{t('player.discover.genresEmpty')}</p>
            )}

            {genres && genres.length > 0 && (
              <>
                <div className="flex gap-2">
                  <button onClick={() => quickSetAllGenres(true)} disabled={genresBusy}
                    className="text-[11px] px-2 py-1 rounded-full bg-hifi-dark text-hifi-silver hover:bg-hifi-light/40 disabled:opacity-50">
                    {t('player.discover.genresSelectAll')}
                  </button>
                  <button onClick={() => quickSetAllGenres(false)} disabled={genresBusy}
                    className="text-[11px] px-2 py-1 rounded-full bg-hifi-dark text-hifi-silver hover:bg-hifi-light/40 disabled:opacity-50">
                    {t('player.discover.genresSelectNone')}
                  </button>
                </div>

                {presets.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {presets.map((p) => (
                      <button key={p.id} onClick={() => applyGenrePreset(p)} disabled={genresBusy}
                        className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-full bg-hifi-dark text-hifi-silver hover:bg-hifi-light/40 disabled:opacity-50">
                        <span>{p.name}</span>
                        <Trash2 size={12} className="hover:text-red-400"
                          onClick={(e) => { e.stopPropagation(); setPresetToDelete(p.id); }} />
                      </button>
                    ))}
                  </div>
                )}
                {presetToDelete && (
                  <div className="flex items-center justify-between bg-hifi-dark rounded-lg p-2 text-xs text-white">
                    <span>{t('player.discover.genresPresetDeleteConfirm',
                      { name: presets.find((p) => p.id === presetToDelete)?.name || '' })}</span>
                    <div className="flex gap-2">
                      <button onClick={() => deleteGenrePreset(presetToDelete)} className="text-red-400 hover:text-red-300 px-2">
                        {t('player.discover.genresPresetDelete')}
                      </button>
                      <button onClick={() => setPresetToDelete(null)} className="text-hifi-silver px-2">×</button>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto content-scrollbar">
                  {genres.map((g) => (
                    <button key={g.name} onClick={() => toggleGenre(g)} disabled={genresBusy}
                      className={`text-xs px-3 py-1.5 rounded-full border transition-colors disabled:opacity-50 ${
                        g.included
                          ? 'bg-hifi-gold/20 border-hifi-gold text-hifi-gold'
                          : 'bg-hifi-dark border-transparent text-hifi-silver/70 hover:border-hifi-border'}`}>
                      {g.name}
                    </button>
                  ))}
                </div>

                <div onClick={() => showKeyboard(presetNameInputRef, presetNameDraft)} className="flex items-center gap-2 pt-1">
                  <input ref={presetNameInputRef} type="text" value={presetNameDraft}
                    onChange={(e) => setPresetNameDraft(e.target.value)}
                    placeholder={t('player.discover.genresPresetNamePlaceholder')}
                    className="flex-1 bg-hifi-surface border border-hifi-accent rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-hifi-gold cursor-pointer" />
                  <button onClick={saveCurrentAsGenrePreset}
                    disabled={!presetNameDraft.trim() || !genres.some((g) => g.included)}
                    className="text-xs bg-hifi-light text-white px-3 py-2 rounded-lg disabled:opacity-50 hover:bg-hifi-accent transition-colors">
                    {t('player.discover.genresPresetSaveAs')}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        <div className="grid grid-cols-3 gap-3">
          {[
            { mode: 'tracks', label: t('player.discover.mixTracks'), Icon: Shuffle },
            { mode: 'albums', label: t('player.discover.mixAlbums'), Icon: Disc },
            { mode: 'contributors', label: t('player.discover.mixArtists'), Icon: User },
          ].map(({ mode, label, Icon }) => (
            <button key={mode} onClick={() => startMix(mode, 'player.discover.mixStarted')}
              disabled={!playerMac}
              className="flex flex-col items-center justify-center py-5 bg-hifi-surface hover:bg-hifi-light disabled:opacity-40 rounded-xl border border-hifi-border hover:border-hifi-accent transition-colors">
              <Icon size={24} className="text-hifi-gold mb-2" />
              <span className="text-xs font-medium text-white">{label}</span>
            </button>
          ))}
        </div>
        {mixMsg && <p className="text-xs text-hifi-silver/60 mt-2">{mixMsg}</p>}
      </div>

      {/* ── Don't Stop The Music ── */}
      {dstmAvailable && (
        <div className="flex items-center justify-between px-4 py-3 bg-hifi-surface rounded-xl border border-hifi-border">
          <div className="flex items-center space-x-3 min-w-0">
            <InfinityIcon size={18} className={dstmOn ? 'text-hifi-gold' : 'text-hifi-silver/50'} />
            <div className="min-w-0">
              <p className="text-sm text-white">{t('player.discover.dstm')}</p>
              <p className="text-[11px] text-hifi-silver/50 truncate">
                {dstmOn
                  ? t('player.discover.dstmOn', { provider: dstmProvider })
                  : dstmCanEnable ? t('player.discover.dstmOff') : t('player.discover.dstmSetupHint')}
              </p>
            </div>
          </div>
          {dstmCanEnable && (
            <button onClick={toggleDstm} disabled={dstmBusy}
              className={`w-11 h-6 rounded-full transition-colors relative shrink-0 ${dstmOn ? 'bg-hifi-gold' : 'bg-white/15'}`}>
              <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-all ${dstmOn ? 'left-[22px]' : 'left-0.5'}`} />
            </button>
          )}
        </div>
      )}

      {/* ── Similar artists ── */}
      {similar.length > 0 && (
        <div>
          <p className="text-xs font-semibold tracking-wider text-hifi-silver/60 uppercase mb-2">
            {t('player.discover.similarTo', { artist })}
          </p>
          <div className="flex flex-wrap gap-2">
            {similar.map((name) => {
              const id = libraryArtists?.[name.toLowerCase()];
              return (
                <button key={name} onClick={() => id && onPlayArtist(id)}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-full text-xs border transition-colors
                    ${id
                      ? 'bg-hifi-surface hover:bg-hifi-light text-white border-hifi-border hover:border-hifi-gold cursor-pointer'
                      : 'bg-white/5 text-hifi-silver/60 border-transparent cursor-default'}`}>
                  {id && <Play size={10} className="text-hifi-gold" fill="currentColor" />}
                  {name}
                </button>
              );
            })}
          </div>
          <p className="text-[10px] text-hifi-silver/40 mt-1.5">{t('player.discover.similarHint')}</p>
        </div>
      )}

      {/* ── Artist biography ── */}
      {bio && (
        <div className="bg-hifi-surface rounded-xl border border-hifi-border p-4">
          <button onClick={() => setBioOpen((v) => !v)} className="flex items-center space-x-2 w-full text-left">
            <BookOpen size={15} className="text-hifi-gold shrink-0" />
            <p className="text-sm font-medium text-white flex-1">{t('player.discover.bio', { artist })}</p>
            <span className="text-[11px] text-hifi-silver/50">{bioOpen ? '−' : '+'}</span>
          </button>
          <p className={`text-xs text-hifi-silver/80 leading-relaxed whitespace-pre-line mt-2 ${bioOpen ? '' : 'line-clamp-3'}`}>
            {bio}
          </p>
        </div>
      )}

      {/* Empty-state when nothing contextual is available */}
      {!similar.length && !bio && (
        <p className="text-xs text-hifi-silver/40">{t('player.discover.hint')}</p>
      )}
    </div>
  );
};

// Memoized for the same reason as Settings (see that file's export comment):
// isolates this tab from LyrionServer's 1s playback-poll re-render.
export default React.memo(Discover);
