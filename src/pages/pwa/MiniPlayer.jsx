import React from 'react';
import { Play, Pause, SkipBack, SkipForward, Music } from 'lucide-react';
import { safeUrl } from '../../hooks/useLyrionPlayer';
import { lyrionApi } from '../../utils/lyrionApi';

// 48dp docked bar shown on Home/library while something is playing,
// replicating now_playing_fragment_mini.xml: thin progress line on top,
// small square art, 2-line title/artist, prev/play/next icon buttons.
const MiniPlayer = ({ player, onExpand }) => {
  const { activePlayer, title, artist, isPlaying, progress, artworkUrl, handleAction } = player;

  if (!activePlayer) return null;

  const previous = (e) => { e.stopPropagation(); handleAction(() => lyrionApi.previous(activePlayer.playerid)); };
  const next = (e) => { e.stopPropagation(); handleAction(() => lyrionApi.next(activePlayer.playerid)); };
  const togglePlayPause = (e) => { e.stopPropagation(); handleAction(() => lyrionApi.togglePause(activePlayer.playerid)); };

  return (
    <div onClick={onExpand} className="relative flex items-center gap-3 h-[52px] px-2 bg-hifi-gray shrink-0 cursor-pointer">
      <div className="absolute top-0 left-0 h-[2px] bg-hifi-gold" style={{ width: `${progress}%` }} />
      <div className="w-9 h-9 shrink-0 bg-hifi-light overflow-hidden">
        {artworkUrl
          ? <img src={safeUrl(artworkUrl)} alt="" className="w-full h-full object-cover" />
          : <div className="w-full h-full flex items-center justify-center text-hifi-silver/30"><Music size={16} /></div>}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-white truncate">{title}</p>
        <p className="text-[11px] text-hifi-silver/60 truncate">{artist}</p>
      </div>
      <button onClick={previous} className="p-2 text-hifi-gold shrink-0"><SkipBack size={16} fill="currentColor" /></button>
      <button onClick={togglePlayPause} className="p-2 text-hifi-gold shrink-0">
        {isPlaying ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
      </button>
      <button onClick={next} className="p-2 text-hifi-gold shrink-0"><SkipForward size={16} fill="currentColor" /></button>
    </div>
  );
};

export default MiniPlayer;
