import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Server, Settings, Play, Pause, SkipBack, SkipForward,
  Volume2, VolumeX, Music, AlertCircle, RefreshCw,
  Folder, User, Disc, Library, Home, ChevronRight, ListMusic,
  ChevronUp, ChevronDown
} from 'lucide-react';
import { lyrionApi } from '../utils/lyrionApi';
import AnalogVUMeter from '../components/AnalogVUMeter';

/**
 * Artwork Component with local error state
 */
const ArtworkImage = ({ src, alt, className, fallbackIcon: FallbackIcon }) => {
  const [hasError, setHasError] = useState(false);

  // Reset error state if src changes
  useEffect(() => {
    setHasError(false);
  }, [src]);

  if (!src || hasError) {
    return (
      <div className={`absolute inset-0 flex items-center justify-center text-hifi-silver/30 bg-hifi-gray`}>
        <FallbackIcon size={48} />
      </div>
    );
  }

  return (
    <img
      src={src}
      alt={alt}
      className={className}
      onError={() => setHasError(true)}
    />
  );
};

/**
 * Native Lyrion Server Player
 * Interfaces with LMS via JSON-RPC
 */
const LyrionServer = ({ onNavigate }) => {
  const [serverUrl, setServerUrl] = useState(localStorage.getItem('lyrionUrl') || 'http://localhost:9000');

  // LMS State
  const [isConnected, setIsConnected] = useState(false);
  const [players, setPlayers] = useState([]);
  const [activePlayer, setActivePlayer] = useState(null);
  const [playerStatus, setPlayerStatus] = useState(null);
  const [error, setError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // Library State
  const [currentView, setCurrentView] = useState('home'); // home, artists, albums, folders, tracks
  const [libraryData, setLibraryData] = useState([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [navigationStack, setNavigationStack] = useState([{ view: 'home', title: 'Home', data: null }]);

  // UI State
  const [isPlayerExpanded, setIsPlayerExpanded] = useState(false);


  // Initialize and connect
  useEffect(() => {
    lyrionApi.setBaseUrl(serverUrl);

    // Add a 10-second delay before attempting to connect
    const timer = setTimeout(() => {
      connectToServer();
    }, 10000);

    return () => clearTimeout(timer);
  }, [serverUrl]);

  const connectToServer = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const serverStatus = await lyrionApi.getServerStatus();
      setIsConnected(true);

      const availablePlayers = serverStatus?.players_loop || [];
      setPlayers(availablePlayers);

      if (availablePlayers.length > 0) {
        // Select first player if none selected, or keep current if it still exists
        if (!activePlayer || !availablePlayers.find(p => p.playerid === activePlayer.playerid)) {
          setActivePlayer(availablePlayers[0]);
        }
      } else {
        setActivePlayer(null);
        setPlayerStatus(null);
      }
    } catch (err) {
      console.error("Failed to connect to Lyrion Server:", err);
      setIsConnected(false);
      setError("Impossibile connettersi al server. Verifica l'URL.");
    } finally {
      setIsLoading(false);
    }
  };

  const fetchStatus = async () => {
    if (!activePlayer) return;
    try {
      const status = await lyrionApi.getPlayerStatus(activePlayer.playerid);
      setPlayerStatus(status);
    } catch (err) {
      console.error("Failed to fetch player status:", err);
    }
  };

  // Polling logic for player status
  useEffect(() => {
    if (!activePlayer) return;

    fetchStatus(); // Fetch immediately on player change
    const interval = setInterval(fetchStatus, 1000);

    return () => clearInterval(interval);
  }, [activePlayer]);

  // Immediate update after an action
  const handleAction = async (actionFn) => {
    try {
      await actionFn();
      fetchStatus(); // Immediately fetch new status to update UI
    } catch (err) {
      console.error("Action failed:", err);
    }
  };


  // Helper to format time (seconds to m:ss)
  const formatTime = (seconds) => {
    if (!seconds || isNaN(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  // --- Library Navigation Methods ---

  const navigateTo = async (view, title, params = null) => {
    setLibraryLoading(true);
    let data = [];
    try {
      if (view === 'artists') {
        const res = await lyrionApi.getArtists();
        data = res?.artists_loop || [];
      } else if (view === 'albums') {
        const res = await lyrionApi.getAlbums(9999, 0, params?.artistId);
        data = res?.albums_loop || [];
      } else if (view === 'tracks') {
        const res = await lyrionApi.getTracks(9999, 0, params?.albumId);
        data = res?.titles_loop || [];
      } else if (view === 'folders') {
        const res = await lyrionApi.getMusicFolders(params?.folderId);
        data = res?.folder_loop || [];
      }

      const newStack = [...navigationStack, { view, title, params }];
      setNavigationStack(newStack);
      setCurrentView(view);
      setLibraryData(data);
    } catch (err) {
      console.error(`Failed to load ${view}:`, err);
    } finally {
      setLibraryLoading(false);
    }
  };

  const goBack = async () => {
    if (navigationStack.length <= 1) return;
    const newStack = navigationStack.slice(0, -1);
    const prevState = newStack[newStack.length - 1];

    setNavigationStack(newStack);
    setCurrentView(prevState.view);

    if (prevState.view !== 'home') {
      setLibraryLoading(true);
      try {
        let data = [];
        if (prevState.view === 'artists') {
          const res = await lyrionApi.getArtists();
          data = res?.artists_loop || [];
        } else if (prevState.view === 'albums') {
          const res = await lyrionApi.getAlbums(9999, 0, prevState.params?.artistId);
          data = res?.albums_loop || [];
        } else if (prevState.view === 'tracks') {
          const res = await lyrionApi.getTracks(9999, 0, prevState.params?.albumId);
          data = res?.titles_loop || [];
        } else if (prevState.view === 'folders') {
          const res = await lyrionApi.getMusicFolders(prevState.params?.folderId);
          data = res?.folder_loop || [];
        }
        setLibraryData(data);
      } catch (err) {
        console.error(`Failed to load ${prevState.view}:`, err);
      } finally {
        setLibraryLoading(false);
      }
    }
  };

  const goHome = () => {
    setNavigationStack([{ view: 'home', title: 'Home', data: null }]);
    setCurrentView('home');
  };

  const handlePlayItem = (type, id) => {
    if (!activePlayer) return;
    handleAction(() => lyrionApi.playItem(activePlayer.playerid, type, id));
  };


  // --- Render Methods ---


  const renderLibraryContent = () => {
    if (libraryLoading) {
      return (
        <div className="flex-1 flex items-center justify-center">
           <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
              className="w-12 h-12 border-4 border-hifi-gold border-t-transparent rounded-full"
            />
        </div>
      );
    }

    if (currentView === 'home') {
      return (
        <div className="grid grid-cols-2 gap-4 p-6">
          <button onClick={() => navigateTo('artists', 'Artisti')} className="flex flex-col items-center justify-center p-8 bg-hifi-light/30 hover:bg-hifi-light/50 rounded-xl border border-white/5 transition-colors">
            <User size={48} className="text-hifi-silver mb-4" />
            <span className="text-xl font-medium text-white">Artisti</span>
          </button>
          <button onClick={() => navigateTo('albums', 'Album')} className="flex flex-col items-center justify-center p-8 bg-hifi-light/30 hover:bg-hifi-light/50 rounded-xl border border-white/5 transition-colors">
            <Disc size={48} className="text-hifi-silver mb-4" />
            <span className="text-xl font-medium text-white">Album</span>
          </button>
          <button onClick={() => navigateTo('folders', 'Cartelle')} className="flex flex-col items-center justify-center p-8 bg-hifi-light/30 hover:bg-hifi-light/50 rounded-xl border border-white/5 transition-colors">
            <Folder size={48} className="text-hifi-silver mb-4" />
            <span className="text-xl font-medium text-white">Cartelle</span>
          </button>
        </div>
      );
    }

    return (
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {currentView === 'albums' ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 md:gap-6">
            {libraryData.map((item, idx) => {
              const artworkId = item.artwork_track_id || item.id;
              const artworkUrl = artworkId ? lyrionApi.getArtworkUrl(artworkId, 300) : null;
              return (
                <div key={item.id || idx} className="bg-hifi-light/10 hover:bg-hifi-light/20 rounded-xl overflow-hidden group cursor-pointer transition-colors" onClick={() => navigateTo('tracks', item.album, { albumId: item.id })}>
                  <div className="relative aspect-square bg-hifi-gray">
                    <ArtworkImage src={artworkUrl} alt={item.album} className="w-full h-full object-cover" fallbackIcon={Disc} />
                    <div className="absolute inset-0 bg-black/40 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                      <button onClick={(e) => { e.stopPropagation(); handlePlayItem('album_id', item.id); }} className="p-4 bg-hifi-gold text-black rounded-full hover:scale-110 transition-transform shadow-lg"><Play size={24} fill="currentColor" /></button>
                    </div>
                  </div>
                  <div className="p-3">
                    <h3 className="text-white font-medium truncate" title={item.album}>{item.album}</h3>
                    <p className="text-hifi-silver text-sm truncate" title={item.artist}>{item.artist}</p>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
        <ul className="space-y-2">
          {libraryData.map((item, idx) => {
            if (currentView === 'artists') {
              return (
                <li key={idx} className="flex items-center justify-between p-4 bg-hifi-light/20 hover:bg-hifi-light/40 rounded-lg group cursor-pointer" onClick={() => navigateTo('albums', item.artist, { artistId: item.id })}>
                  <span className="text-lg text-white">{item.artist}</span>
                  <div className="flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={(e) => { e.stopPropagation(); handlePlayItem('artist_id', item.id); }} className="p-2 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors"><Play size={20} fill="currentColor" /></button>
                  </div>
                </li>
              );
            }
            if (currentView === 'tracks') {
              return (
                <li key={idx} className="flex items-center justify-between p-4 bg-hifi-light/20 hover:bg-hifi-light/40 rounded-lg group cursor-pointer" onClick={() => handlePlayItem('track_id', item.id)}>
                   <span className="text-lg text-white">{item.title}</span>
                </li>
              );
            }
            if (currentView === 'folders') {
              const isDir = item.type === 'folder';
              return (
                <li key={idx} className="flex items-center justify-between p-4 bg-hifi-light/20 hover:bg-hifi-light/40 rounded-lg group cursor-pointer" onClick={() => isDir ? navigateTo('folders', item.filename, { folderId: item.id }) : handlePlayItem('track_id', item.id)}>
                  <div className="flex items-center space-x-3">
                    {isDir ? <Folder size={24} className="text-hifi-silver" /> : <Music size={24} className="text-hifi-silver" />}
                    <span className="text-lg text-white truncate max-w-sm">{item.filename || item.title}</span>
                  </div>
                   <div className="flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={(e) => { e.stopPropagation(); handlePlayItem(isDir ? 'folder_id' : 'track_id', item.id); }} className="p-2 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors"><Play size={20} fill="currentColor" /></button>
                  </div>
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

  const renderContent = () => {
    if (isLoading && !isConnected) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center bg-black/50">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
            className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full mb-6"
          />
          <h2 className="text-2xl font-bold text-white mb-2">Connessione in corso...</h2>
          <p className="text-hifi-silver">{serverUrl}</p>
        </div>
      );
    }

    if (error) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center bg-black/50 px-8 text-center">
          <div className="w-24 h-24 bg-red-500/10 rounded-full flex items-center justify-center mb-6">
            <AlertCircle size={48} className="text-red-500" />
          </div>
          <h2 className="text-2xl font-bold text-white mb-4">Errore di Connessione</h2>
          <p className="text-hifi-silver max-w-md mb-8">{error}</p>
          <motion.button
            onClick={connectToServer}
            className="flex items-center space-x-2 bg-hifi-light hover:bg-hifi-accent px-6 py-3 rounded-lg text-white transition-colors"
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <RefreshCw size={20} />
            <span>Riprova</span>
          </motion.button>
        </div>
      );
    }

    if (!activePlayer) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center bg-black/50">
          <div className="w-24 h-24 bg-hifi-light rounded-full flex items-center justify-center mb-6 border border-hifi-accent">
            <Music size={48} className="text-hifi-silver" />
          </div>
          <h2 className="text-2xl font-bold text-white mb-2">Nessun Player Trovato</h2>
          <p className="text-hifi-silver">Assicurati che ci sia almeno un player Lyrion attivo.</p>
        </div>
      );
    }

    // Now Playing State
    // The API request in getPlayerStatus returns only 1 track (the current one) in playlist_loop
    const currentTrack = playerStatus?.playlist_loop?.[0] || {};

    const title = currentTrack.title || 'Nessuna traccia';
    const artist = currentTrack.artist || 'Artista Sconosciuto';
    const album = currentTrack.album || 'Album Sconosciuto';
    const isPlaying = playerStatus?.mode === 'play';
    const volume = playerStatus?.mixer_volume || 0;
    const duration = currentTrack.duration || 0;
    const time = playerStatus?.time || 0;
    const progress = duration > 0 ? (time / duration) * 100 : 0;
    const artworkUrl = currentTrack.id ? lyrionApi.getArtworkUrl(currentTrack.id, 200) : null;

    return (
      <div className="flex-1 flex flex-col overflow-hidden bg-hifi-dark relative">
        {/* Main Content Area: Library Browser (Full width now) */}
        <div className="flex-1 flex overflow-hidden">
            <div className="flex-1 flex flex-col bg-black/40">
              {/* Library Breadcrumbs/Header */}
              <div className="flex items-center px-4 md:px-6 py-4 border-b border-hifi-accent/30 bg-hifi-dark/80 backdrop-blur-sm sticky top-0 z-10 shrink-0">
                 {onNavigate && (
                   <button onClick={() => onNavigate('home')} className="p-2 mr-2 md:mr-4 bg-hifi-light/50 text-white hover:bg-hifi-accent rounded-lg shadow transition-colors flex items-center">
                     <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
                   </button>
                 )}
                 <button onClick={goHome} className="p-2 text-hifi-silver hover:text-white hover:bg-white/10 rounded-lg transition-colors">
                    <Home size={20} />
                 </button>
                 {navigationStack.length > 1 && (
                   <div className="flex items-center ml-2 space-x-2 text-sm">
                      {navigationStack.map((nav, idx) => (
                        <React.Fragment key={idx}>
                          {idx > 0 && <ChevronRight size={16} className="text-hifi-silver/50" />}
                          <span className={`truncate max-w-[150px] ${idx === navigationStack.length - 1 ? 'text-white font-medium' : 'text-hifi-silver cursor-pointer hover:text-white'}`} onClick={() => {
                            if (idx < navigationStack.length - 1) {
                               const newStack = navigationStack.slice(0, idx + 1);
                               setNavigationStack(newStack);
                               setCurrentView(newStack[newStack.length-1].view);
                               navigateTo(newStack[newStack.length-1].view, newStack[newStack.length-1].title, newStack[newStack.length-1].params);
                            }
                          }}>
                            {nav.title}
                          </span>
                        </React.Fragment>
                      ))}
                   </div>
                 )}
                 <div className="flex-1"></div>
                 {navigationStack.length > 1 && (
                    <button onClick={goBack} className="px-4 py-2 text-sm bg-white/5 hover:bg-white/10 text-white rounded-lg transition-colors">
                      Indietro
                    </button>
                 )}
              </div>

              {/* Library Content */}
              {renderLibraryContent()}
            </div>
        </div>

        {/* Full Screen Player Overlay (Using Portal to cover entire app) */}
        {createPortal(
          <AnimatePresence>
            {isPlayerExpanded && (
              <motion.div
                initial={{ y: "100%" }}
                animate={{ y: 0 }}
                exit={{ y: "100%" }}
                transition={{ type: "spring", damping: 25, stiffness: 200 }}
                className="fixed inset-0 z-50 flex flex-col bg-hifi-dark"
              >
               {/* Blurred background */}
               <div
                  className="absolute inset-0 opacity-20 bg-cover bg-center blur-3xl scale-125 transition-all duration-1000 pointer-events-none"
                  style={{ backgroundImage: artworkUrl ? `url(${artworkUrl})` : 'none' }}
                />
               <div className="absolute inset-0 bg-gradient-to-t from-black via-black/80 to-transparent pointer-events-none" />

               {/* Top Bar (Collapse Button) */}
               <div className="relative z-40 p-2 md:p-4 flex justify-between items-center shrink-0">
                 <button
                   onClick={() => setIsPlayerExpanded(false)}
                   className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
                 >
                   <ChevronDown size={24} />
                 </button>
                 <div className="text-center flex-1">
                   <p className="text-[10px] md:text-xs tracking-widest text-hifi-silver uppercase">In Riproduzione</p>
                 </div>
                 <div className="w-10"></div> {/* Spacer for centering */}
               </div>

               {/* Main Expanded Player Content (Restyled split layout) */}
               <div className="relative z-40 flex-1 flex flex-col md:flex-row items-center justify-center p-2 sm:p-4 max-w-7xl mx-auto w-full min-h-0 overflow-y-auto md:overflow-hidden gap-4 md:gap-8">
                  {/* Left Side: Large Album Cover */}
                  <motion.div
                    className="w-full md:w-1/2 flex items-center justify-center shrink-0 min-h-0"
                    initial={{ x: -20, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    transition={{ delay: 0.1, duration: 0.5 }}
                  >
                     <div className="relative w-full h-full max-h-[70vh] aspect-square max-w-md rounded-2xl overflow-hidden shadow-[0_20px_50px_rgba(0,0,0,0.5)] border border-white/10 bg-hifi-gray shrink-1">
                        {artworkUrl ? (
                          <img
                            src={artworkUrl}
                            alt="Album Art"
                            className="w-full h-full object-cover"
                            onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }}
                          />
                        ) : null}
                        <div
                          className="absolute inset-0 bg-gradient-to-br from-hifi-gray to-hifi-dark flex flex-col items-center justify-center text-hifi-silver/30"
                          style={{ display: artworkUrl ? 'none' : 'flex' }}
                        >
                          <Music size={80} className="md:w-32 md:h-32 mb-4" />
                        </div>
                     </div>
                  </motion.div>

                  {/* Right Side: Info, Progress, Controls, and VU Meter */}
                  <motion.div
                    className="w-full md:w-1/2 flex flex-col justify-start md:justify-center h-full shrink-0 min-w-0 max-w-xl text-center md:text-left py-2"
                    initial={{ x: 20, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    transition={{ delay: 0.2, duration: 0.5 }}
                  >
                    {/* Track Info */}
                    <div className="mb-1 shrink-0 pt-2">
                      <h2 className="text-2xl md:text-3xl lg:text-4xl font-bold text-white mb-1 line-clamp-2 leading-tight">
                        {title}
                      </h2>
                      <p className="text-lg md:text-xl lg:text-2xl text-hifi-gold mb-1 font-medium truncate">
                        {artist}
                      </p>
                      <p className="text-base md:text-lg text-hifi-silver/80 truncate">
                        {album}
                      </p>
                    </div>

                    {/* Big Progress Bar */}
                    <div className="w-full mb-3 md:mb-4 shrink-0">
                      <div className="flex justify-between text-xs md:text-sm text-hifi-silver font-medium mb-1">
                        <span>{formatTime(time)}</span>
                        <span>{formatTime(duration)}</span>
                      </div>
                      <div className="relative h-2 bg-white/10 rounded-full overflow-hidden cursor-pointer shadow-inner"
                           onClick={(e) => {
                             if (!duration) return;
                             const rect = e.currentTarget.getBoundingClientRect();
                             const clickX = e.clientX - rect.left;
                             const percentage = clickX / rect.width;
                             const newTime = duration * percentage;
                             handleAction(() => lyrionApi.seek(activePlayer.playerid, newTime));
                           }}>
                        <motion.div
                          className="absolute top-0 left-0 h-full bg-gradient-to-r from-hifi-gold to-yellow-500 rounded-full shadow-[0_0_15px_currentColor]"
                          style={{ width: `${progress}%` }}
                          layoutId="progressBar"
                        />
                      </div>
                    </div>

                    {/* Big Controls */}
                    <div className="flex items-center justify-center md:justify-start space-x-6 sm:space-x-8 shrink-0 mb-2">
                      <motion.button
                        whileHover={{ scale: 1.1 }}
                        whileTap={{ scale: 0.9 }}
                        className="p-2 text-hifi-silver hover:text-white transition-colors"
                        onClick={() => handleAction(() => lyrionApi.previous(activePlayer.playerid))}
                      >
                        <SkipBack size={28} className="md:w-8 md:h-8" />
                      </motion.button>

                      <motion.button
                        whileHover={{ scale: 1.05 }}
                        whileTap={{ scale: 0.95 }}
                        className="w-14 h-14 md:w-16 md:h-16 lg:w-20 lg:h-20 flex items-center justify-center bg-hifi-gold text-black rounded-full shadow-[0_0_20px_rgba(212,175,55,0.4)] hover:shadow-[0_0_35px_rgba(212,175,55,0.6)] transition-all border-4 border-black/20"
                        onClick={() => handleAction(() => lyrionApi.togglePause(activePlayer.playerid))}
                      >
                        {isPlaying ? <Pause size={28} className="md:w-10 md:h-10" fill="currentColor" /> : <Play size={28} className="md:w-10 md:h-10 ml-1" fill="currentColor" />}
                      </motion.button>

                      <motion.button
                        whileHover={{ scale: 1.1 }}
                        whileTap={{ scale: 0.9 }}
                        className="p-2 text-hifi-silver hover:text-white transition-colors"
                        onClick={() => handleAction(() => lyrionApi.next(activePlayer.playerid))}
                      >
                        <SkipForward size={28} className="md:w-8 md:h-8" />
                      </motion.button>
                    </div>

                    {/* VU Meter */}
                    <div className="w-full shrink-0 flex justify-center md:justify-start mt-1 flex-1 min-h-0 pb-2">
                       <AnalogVUMeter isPlaying={isPlaying} className="w-full max-w-lg lg:max-w-xl h-full max-h-[180px] md:max-h-[200px]" />
                    </div>
                  </motion.div>
                 </div>
              </motion.div>
            )}
          </AnimatePresence>,
          document.body
        )}

        {/* Persistent Bottom Player Bar (Mini Player) */}
        <div className="relative h-24 bg-hifi-dark border-t border-hifi-accent shadow-[0_-10px_30px_rgba(0,0,0,0.5)] z-20 shrink-0">
            {/* Progress Bar (Absolute positioned at top of bar) */}
            <div className="absolute top-0 left-0 right-0 h-1 bg-white/5 cursor-pointer z-30"
                 onClick={(e) => {
                   if (!duration) return;
                   const rect = e.currentTarget.getBoundingClientRect();
                   const clickX = e.clientX - rect.left;
                   const percentage = clickX / rect.width;
                   const newTime = duration * percentage;
                   handleAction(() => lyrionApi.seek(activePlayer.playerid, newTime));
                 }}>
              <motion.div
                className="h-full bg-hifi-gold"
                style={{ width: `${progress}%` }}
                layoutId="bottomProgressBar"
              />
            </div>

            <div className="flex items-center justify-between h-full px-4 sm:px-6">
                {/* Left: Mini Track Info (Clickable to expand) */}
                <div
                  className="w-1/3 flex items-center group cursor-pointer"
                  onClick={() => setIsPlayerExpanded(true)}
                >
                  <div className="relative w-14 h-14 rounded overflow-hidden mr-4 flex-shrink-0 bg-hifi-gray">
                    {artworkUrl ? (
                      <img src={artworkUrl} alt="" className="w-full h-full object-cover group-hover:opacity-50 transition-opacity" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-hifi-silver/30 group-hover:opacity-50 transition-opacity"><Music size={24} /></div>
                    )}
                    <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                      <ChevronUp size={24} className="text-white drop-shadow-md" />
                    </div>
                  </div>
                  <div className="flex flex-col min-w-0">
                     <span className="text-white font-medium truncate">{title}</span>
                     <span className="text-sm text-hifi-silver truncate">{artist}</span>
                  </div>
                </div>

                {/* Center: Playback Controls */}
                <div className="w-1/3 flex justify-center items-center space-x-4 sm:space-x-6">
                   <motion.button
                      whileHover={{ scale: 1.1 }}
                      whileTap={{ scale: 0.9 }}
                      className="p-2 text-hifi-silver hover:text-white transition-colors"
                      onClick={() => handleAction(() => lyrionApi.previous(activePlayer.playerid))}
                    >
                      <SkipBack size={24} />
                    </motion.button>

                    <motion.button
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                      className="w-12 h-12 flex items-center justify-center bg-white text-black rounded-full hover:bg-hifi-gold transition-all"
                      onClick={() => handleAction(() => lyrionApi.togglePause(activePlayer.playerid))}
                    >
                      {isPlaying ? <Pause size={24} fill="currentColor" /> : <Play size={24} fill="currentColor" className="ml-1" />}
                    </motion.button>

                    <motion.button
                      whileHover={{ scale: 1.1 }}
                      whileTap={{ scale: 0.9 }}
                      className="p-2 text-hifi-silver hover:text-white transition-colors"
                      onClick={() => handleAction(() => lyrionApi.next(activePlayer.playerid))}
                    >
                      <SkipForward size={24} />
                    </motion.button>
                </div>

                {/* Right: Volume */}
                <div className="w-1/3 flex items-center justify-end space-x-3 hidden sm:flex">
                   <button
                      onClick={() => handleAction(() => lyrionApi.setVolume(activePlayer.playerid, volume === 0 ? 50 : 0))}
                      className="text-hifi-silver hover:text-white transition-colors"
                    >
                      {volume === 0 ? <VolumeX size={20} /> : <Volume2 size={20} />}
                    </button>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      value={volume}
                      onChange={(e) => {
                        const newVol = parseInt(e.target.value);
                        setPlayerStatus(prev => ({...prev, mixer_volume: newVol}));
                        handleAction(() => lyrionApi.setVolume(activePlayer.playerid, newVol));
                      }}
                      className="w-24 h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-hifi-gold"
                    />
                </div>
            </div>
        </div>
      </div>
    );
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="h-full w-full flex flex-col font-sans bg-hifi-dark"
    >
      {renderContent()}
    </motion.div>
  );
};

export default LyrionServer;
