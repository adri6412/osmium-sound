import React, { useState } from 'react';
import {
  ChevronDown, Play, Pause, SkipBack, SkipForward,
  Volume2, VolumeX, Music, Shuffle, Repeat, Repeat1, ListMusic, Moon,
} from 'lucide-react';
import { useI18n } from '../../i18n';
import { safeUrl, formatTime } from '../../hooks/useLyrionPlayer';
import { lyrionApi } from '../../utils/lyrionApi';
import AnalogVUMeter from '../../components/AnalogVUMeter';
import QueueSheet from './QueueSheet';
import SleepSheet from './SleepSheet';

// Full-screen Now Playing, replicating now_playing_fragment_full.xml: square
// artwork, stacked title/artist/album (no card), seek bar with time labels,
// a plain-icon transport row (not boxed buttons — see phone-screenshots/
// 2-now-playing.png), volume row. No filled circles/gradients/glow — flat,
// matching the Android app rather than the kiosk's desktop styling.
const NowPlayingScreen = ({ player, onClose }) => {
  const { t } = useI18n();
  const [queueOpen, setQueueOpen] = useState(false);
  const [sleepOpen, setSleepOpen] = useState(false);
  const {
    activePlayer, title, artist, album, isPlaying, volume, repeatMode, shuffleMode,
    willSleepIn, duration, time, progress, artworkUrlLg, formatLabel,
    setVolume, toggleMute, seek, cycleShuffle, cycleRepeat, handleAction,
  } = player;

  const previous = () => handleAction(() => lyrionApi.previous(activePlayer?.playerid));
  const next = () => handleAction(() => lyrionApi.next(activePlayer?.playerid));
  const togglePlayPause = () => handleAction(() => lyrionApi.togglePause(activePlayer?.playerid));

  return (
    <div className="flex flex-col h-full bg-hifi-dark">
      {/* Top bar */}
      <div className="flex items-center justify-between h-12 px-2 shrink-0">
        <button onClick={onClose} className="p-2 text-white">
          <ChevronDown size={22} />
        </button>
        <p className="text-[11px] tracking-[0.2em] text-hifi-silver/60 uppercase">{t('player.nowPlaying')}</p>
        <button onClick={() => setQueueOpen(true)} className="p-2 text-white">
          <ListMusic size={19} />
        </button>
      </div>

      {/* Artwork */}
      <div className="flex justify-center px-6 pt-2 pb-4">
        <div className="w-full max-w-[320px] aspect-square bg-hifi-gray overflow-hidden">
          {artworkUrlLg
            ? <img src={safeUrl(artworkUrlLg)} alt="" className="w-full h-full object-cover" />
            : <div className="w-full h-full flex items-center justify-center text-hifi-silver/20"><Music size={72} /></div>}
        </div>
      </div>

      {/* Track info */}
      <div className="px-6 shrink-0">
        <h1 className="text-xl font-semibold text-white leading-tight">{title}</h1>
        <p className="text-[15px] text-hifi-silver mt-1">{artist}</p>
        {album && <p className="text-sm text-hifi-silver/60">{album}</p>}
        {formatLabel && <p className="text-[11px] text-hifi-silver/40 font-mono mt-1">{formatLabel}</p>}
      </div>

      {/* Seek bar */}
      <div className="px-6 pt-5 shrink-0">
        <div className="relative h-1 bg-hifi-divider cursor-pointer"
          onClick={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            seek((e.clientX - r.left) / r.width);
          }}>
          <div className="absolute top-0 left-0 h-full bg-hifi-gold" style={{ width: `${progress}%` }} />
        </div>
        <div className="flex justify-between text-[11px] text-hifi-silver/60 font-mono mt-1.5">
          <span>{formatTime(time)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      </div>

      {/* Transport row */}
      <div className="flex items-center justify-center gap-8 px-6 pt-3 shrink-0">
        <button onClick={cycleShuffle} disabled={!activePlayer}
          className={shuffleMode > 0 ? 'text-hifi-gold' : 'text-hifi-silver/60'}>
          <Shuffle size={17} />
        </button>
        <button onClick={previous} className="text-hifi-gold">
          <SkipBack size={26} fill="currentColor" />
        </button>
        <button onClick={togglePlayPause} className="text-hifi-gold">
          {isPlaying ? <Pause size={38} fill="currentColor" /> : <Play size={38} fill="currentColor" />}
        </button>
        <button onClick={next} className="text-hifi-gold">
          <SkipForward size={26} fill="currentColor" />
        </button>
        <button onClick={cycleRepeat} disabled={!activePlayer}
          className={repeatMode > 0 ? 'text-hifi-gold' : 'text-hifi-silver/60'}>
          {repeatMode === 1 ? <Repeat1 size={17} /> : <Repeat size={17} />}
        </button>
      </div>

      {/* Volume row */}
      <div className="flex items-center gap-3 px-6 py-4 shrink-0">
        <button onClick={toggleMute} className="text-hifi-silver/70 shrink-0">
          {volume === 0 ? <VolumeX size={17} /> : <Volume2 size={17} />}
        </button>
        <input type="range" min="0" max="100" value={volume}
          className="flex-1 h-1 accent-hifi-gold"
          onChange={(e) => setVolume(parseInt(e.target.value))} />
        <span className="text-[11px] text-hifi-silver/50 font-mono w-7 text-right shrink-0">{volume}</span>
        <button onClick={() => setSleepOpen(true)} className={willSleepIn > 0 ? 'text-hifi-gold shrink-0' : 'text-hifi-silver/50 shrink-0'}>
          <Moon size={16} />
        </button>
      </div>

      {/* VU meters fill whatever vertical space remains — same real-time
          WebSocket component the kiosk uses, degrades to its own fallback
          animation if unreachable, no changes needed for the PWA. */}
      <div className="flex-1 min-h-0 px-6 pb-4">
        <AnalogVUMeter isPlaying={isPlaying} className="w-full h-full" />
      </div>

      <QueueSheet player={player} open={queueOpen} onClose={() => setQueueOpen(false)} />
      <SleepSheet player={player} open={sleepOpen} onClose={() => setSleepOpen(false)} />
    </div>
  );
};

export default NowPlayingScreen;
