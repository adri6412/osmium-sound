import React, { useState, useEffect } from 'react';
import { Shuffle, Disc, User, Infinity as InfinityIcon, BookOpen, Play } from 'lucide-react';
import { lyrionApi } from '../utils/lyrionApi';
import { useI18n } from '../i18n';

// "Discover" tab: endless-mix controls (Random Mix + Don't Stop The Music) and
// context for the current artist (similar artists, biography) via the
// MusicArtistInfo plugin. Every section hides itself when its plugin/data is
// missing, so the tab degrades gracefully on a bare LMS install.
const DSTM_LAST_PROVIDER_KEY = 'hifiDstmLastProvider';

const Discover = ({ playerMac, artist, onPlayArtist }) => {
  const { t } = useI18n();
  // undefined = probing, null = plugin missing, string = current provider
  const [dstmProvider, setDstmProvider] = useState(undefined);
  const [dstmBusy, setDstmBusy] = useState(false);
  const [mixMsg, setMixMsg] = useState('');
  const [similar, setSimilar] = useState([]);
  const [libraryArtists, setLibraryArtists] = useState(null); // name(lower) -> id
  const [bio, setBio] = useState(null);
  const [bioOpen, setBioOpen] = useState(false);

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
        <p className="text-xs font-semibold tracking-wider text-hifi-silver/60 uppercase mb-2">
          {t('player.discover.mixes')}
        </p>
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
