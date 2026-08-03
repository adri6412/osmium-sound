import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Disc, X, HardDrive } from 'lucide-react';
import { useI18n } from '../i18n';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

// CD rip: disc-detect banner + rip dialog. Talks to sources_server.py (:8080)
// directly, like the FIR/pairing bits in Settings — the kiosk is loopback so
// no pairing token is needed. Everything degrades to "render nothing" when
// the service is unreachable (dev) or no disc is inserted.
const SOURCES_BASE = 'http://localhost:8080';

const CdRip = () => {
  const { t } = useI18n();
  const [info, setInfo] = useState(null);        // /api/cd/info payload
  const [dismissed, setDismissed] = useState(null); // discid hidden by the X
  const [open, setOpen] = useState(false);
  const [artist, setArtist] = useState('');
  const [album, setAlbum] = useState('');
  const [tracks, setTracks] = useState([]);
  const [destId, setDestId] = useState('');
  const [ripStatus, setRipStatus] = useState(null); // null = not ripping
  const [errMsg, setErrMsg] = useState('');
  const pollRef = useRef(null);

  // Disc presence poll (light: TOC read + cached metadata server-side).
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch(`${SOURCES_BASE}/api/cd/info`);
        const data = await r.json();
        if (!cancelled) setInfo(data && !data.no_disc ? data : null);
      } catch {
        if (!cancelled) setInfo(null);
      }
    };
    poll();
    const id = setInterval(poll, 7000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  // Seed the edit form each time a new disc shows up.
  useEffect(() => {
    if (!info) return;
    setArtist(info.artist || '');
    setAlbum(info.album || '');
    setTracks((info.tracks || []).map((tr) => tr.title));
    setDestId(info.destinations?.[0]?.source_id || '');
    if (info.ripping && !ripStatus) startStatusPoll();
  }, [info?.discid]);

  const startStatusPoll = () => {
    clearInterval(pollRef.current);
    const tick = async () => {
      try {
        const r = await fetch(`${SOURCES_BASE}/api/cd/rip/status`);
        const st = await r.json();
        setRipStatus(st);
        if (st.state === 'done' || st.state === 'error' || st.state === 'idle') {
          clearInterval(pollRef.current);
        }
      } catch {
        clearInterval(pollRef.current);
        setRipStatus(null);
      }
    };
    tick();
    pollRef.current = setInterval(tick, 2000);
  };
  useEffect(() => () => clearInterval(pollRef.current), []);

  const startRip = async () => {
    setErrMsg('');
    try {
      const r = await fetch(`${SOURCES_BASE}/api/cd/rip`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_id: destId, artist, album, tracks }),
      });
      const data = await r.json();
      if (!r.ok || !data.success) {
        setErrMsg(data.message || t('player.cd.ripError'));
        return;
      }
      setRipStatus({ state: 'starting', track: 0, total: tracks.length, progress: 0 });
      startStatusPoll();
    } catch {
      setErrMsg(t('player.cd.ripError'));
    }
  };

  const eject = async () => {
    try { await fetch(`${SOURCES_BASE}/api/cd/eject`, { method: 'POST' }); } catch { /* best effort */ }
    setOpen(false);
    setRipStatus(null);
    setInfo(null);
  };

  const busy = ripStatus && !['done', 'error', 'idle'].includes(ripStatus.state);
  const showBanner = info && info.discid !== dismissed;
  if (!showBanner && !open) return null;

  return (
    <>
      {showBanner && (
        <div className="flex items-center gap-3 mx-3 mt-2 px-3 py-2 bg-hifi-gold/10 border border-hifi-gold/30 rounded-lg shrink-0">
          <Disc size={18} className="text-hifi-gold shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-white truncate">{t('player.cd.detected')}</p>
            <p className="text-xs text-hifi-silver/70 truncate">{info.artist} — {info.album}</p>
          </div>
          <button onClick={() => setOpen(true)}
            className="px-3 py-1.5 bg-hifi-gold hover:bg-yellow-600 text-black rounded-lg text-xs font-semibold transition-colors shrink-0">
            {busy ? t('player.cd.ripProgressShort') : t('player.cd.rip')}
          </button>
          <button onClick={() => setDismissed(info.discid)}
            className="p-1 text-hifi-silver/50 hover:text-white transition-colors shrink-0">
            <X size={14} />
          </button>
        </div>
      )}

      {createPortal(
        <AnimatePresence>
          {open && (
            <motion.div className="absolute inset-0 z-[70] flex items-center justify-center p-6"
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <div className="absolute inset-0 bg-black/70" onClick={() => !busy && setOpen(false)} />
              <motion.div initial={{ scale: 0.94, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.94, opacity: 0 }}
                className="relative w-full max-w-lg max-h-[85vh] bg-hifi-panel border border-hifi-border rounded-2xl p-5 shadow-2xl flex flex-col">
                <div className="flex items-center justify-between mb-3 shrink-0">
                  <div className="flex items-center space-x-2">
                    <Disc size={16} className="text-hifi-gold" />
                    <p className="text-sm font-semibold text-white">{t('player.cd.ripTitle')}</p>
                  </div>
                  {!busy && (
                    <button onClick={() => setOpen(false)}
                      className="p-1.5 text-hifi-silver/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors">
                      <X size={16} />
                    </button>
                  )}
                </div>

                {ripStatus ? (
                  // ── Progress / result view ──
                  <div className="flex flex-col items-center py-4">
                    {busy && (
                      <motion.div animate={{ rotate: 360 }} transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                        className="mb-4 text-hifi-gold"><Disc size={40} /></motion.div>
                    )}
                    <p className="text-sm text-white mb-2 text-center">{ripStatus.message || ''}</p>
                    {busy && (
                      <>
                        <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden mb-2">
                          <div className="h-full bg-gradient-to-r from-hifi-gold to-yellow-400 rounded-full transition-all"
                            style={{ width: `${ripStatus.progress || 0}%` }} />
                        </div>
                        <p className="text-xs text-hifi-silver/60">
                          {t('player.cd.ripProgress', { track: ripStatus.track || 0, total: ripStatus.total || 0 })}
                        </p>
                      </>
                    )}
                    {ripStatus.state === 'done' && (
                      <>
                        <p className="text-sm text-emerald-400 mb-4">{t('player.cd.ripDone')}</p>
                        <button onClick={eject}
                          className="px-4 py-2.5 bg-hifi-gold hover:bg-yellow-600 text-black rounded-lg text-sm font-semibold transition-colors">
                          {t('player.cd.eject')}
                        </button>
                      </>
                    )}
                    {ripStatus.state === 'error' && (
                      <p className="text-sm text-red-300">{ripStatus.message || t('player.cd.ripError')}</p>
                    )}
                  </div>
                ) : (
                  // ── Setup view ──
                  <div className="flex flex-col min-h-0">
                    <div className="grid grid-cols-2 gap-2 mb-2 shrink-0">
                      <input type="text" value={artist} onChange={(e) => setArtist(e.target.value)}
                        placeholder={t('player.cd.artist')}
                        className="bg-hifi-dark border border-hifi-accent rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-hifi-gold" />
                      <input type="text" value={album} onChange={(e) => setAlbum(e.target.value)}
                        placeholder={t('player.cd.album')}
                        className="bg-hifi-dark border border-hifi-accent rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-hifi-gold" />
                    </div>
                    <div className="flex-1 overflow-y-auto content-scrollbar mb-3 min-h-[120px] max-h-[280px]">
                      <ul className="space-y-1">
                        {tracks.map((title, i) => (
                          <li key={i} className="flex items-center gap-2">
                            <span className="w-6 text-right text-[11px] font-mono text-hifi-silver/50 shrink-0">{i + 1}</span>
                            <input type="text" value={title}
                              onChange={(e) => setTracks((prev) => prev.map((tt, j) => (j === i ? e.target.value : tt)))}
                              className="flex-1 bg-hifi-dark border border-hifi-border rounded px-2 py-1.5 text-xs text-white focus:outline-none focus:border-hifi-gold" />
                          </li>
                        ))}
                      </ul>
                    </div>
                    {(info?.destinations?.length || 0) === 0 ? (
                      <p className="text-xs text-amber-300/90 mb-3">{t('player.cd.noDestination')}</p>
                    ) : (
                      <div className="flex items-center gap-2 mb-3 shrink-0">
                        <HardDrive size={14} className="text-hifi-silver/60 shrink-0" />
                        <select value={destId} onChange={(e) => setDestId(e.target.value)}
                          className="flex-1 bg-hifi-dark border border-hifi-accent rounded-lg px-2 py-2 text-sm text-white focus:outline-none focus:border-hifi-gold">
                          {info.destinations.map((d) => (
                            <option key={d.source_id} value={d.source_id}>{d.name}</option>
                          ))}
                        </select>
                      </div>
                    )}
                    {errMsg && <p className="text-xs text-red-300 mb-2">{errMsg}</p>}
                    <div className="flex gap-2 shrink-0">
                      <button onClick={eject}
                        className="px-4 bg-hifi-light hover:bg-hifi-accent text-white py-2.5 rounded-lg text-sm transition-colors">
                        {t('player.cd.eject')}
                      </button>
                      <button onClick={startRip}
                        disabled={(info?.destinations?.length || 0) === 0}
                        className="flex-1 bg-hifi-gold hover:bg-yellow-600 disabled:opacity-40 text-black py-2.5 rounded-lg text-sm font-semibold transition-colors">
                        {t('player.cd.start')}
                      </button>
                    </div>
                  </div>
                )}
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.getElementById(SCALED_CANVAS_ID) || document.body
      )}
    </>
  );
};

export default CdRip;
