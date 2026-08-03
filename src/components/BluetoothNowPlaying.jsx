import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Bluetooth } from 'lucide-react';
import { systemAPI } from '../utils/api';
import { useI18n } from '../i18n';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

// Bluetooth playback pauses the local Lyrion player (see hifi-bt-watcher.py),
// so the regular Lyrion-driven Now Playing panel has nothing to show while a
// phone is streaming. This is a self-contained overlay — like the "now
// playing" bar CarPlay/Android Auto show for a Bluetooth source — so it
// works from any tab without touching the existing (and fairly involved)
// Lyrion Now Playing layouts. Renders nothing when Bluetooth isn't actively
// streaming.
const BluetoothNowPlaying = () => {
  const { t } = useI18n();
  const [np, setNp] = useState(null);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer = null;
    const poll = async () => {
      const res = await systemAPI.getBluetoothNowPlaying();
      if (!cancelled) {
        if (res.success) setNp(res.data);
        timer = setTimeout(poll, 2000);
      }
    };
    poll();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, []);

  useEffect(() => { setImgError(false); }, [np?.cover_url]);

  const active = !!np?.active;
  const progress = active && np.duration > 0 ? Math.min(100, (np.position / np.duration) * 100) : 0;

  return createPortal(
    <AnimatePresence>
      {active && (
        <motion.div
          initial={{ y: -60, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -60, opacity: 0 }}
          transition={{ type: 'spring', damping: 24, stiffness: 220 }}
          className="absolute top-0 left-0 right-0 z-[60] flex items-center gap-3 px-4 py-2 bg-black/85 backdrop-blur-md border-b border-hifi-gold/20 shadow-[0_4px_20px_rgba(0,0,0,0.5)]"
        >
          <div className="w-9 h-9 rounded-lg overflow-hidden bg-hifi-gray flex items-center justify-center shrink-0">
            {np.cover_url && !imgError ? (
              <img src={np.cover_url} alt="" className="w-full h-full object-cover" onError={() => setImgError(true)} />
            ) : (
              <Bluetooth size={16} className="text-hifi-gold" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-semibold text-white truncate">
              {np.title || t('player.bluetooth.unknownTrack')}
            </p>
            <p className="text-[10px] text-hifi-silver/70 truncate">
              {[np.artist, np.device_name].filter(Boolean).join(' · ') || t('player.bluetooth.streaming')}
            </p>
          </div>
          <Bluetooth size={14} className="text-hifi-gold/70 shrink-0" />
          {np.duration > 0 && (
            <div className="absolute bottom-0 left-0 h-[2px] bg-hifi-gold/60 transition-all" style={{ width: `${progress}%` }} />
          )}
        </motion.div>
      )}
    </AnimatePresence>,
    document.getElementById(SCALED_CANVAS_ID) || document.body
  );
};

export default BluetoothNowPlaying;
