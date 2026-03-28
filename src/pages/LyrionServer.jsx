import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Server, Settings, Play, Pause, SkipBack, SkipForward,
  Volume2, VolumeX, Music, AlertCircle, RefreshCw,
  Folder, User, Disc, Library, Home, ChevronRight, ListMusic,
  ChevronUp, ChevronDown
} from 'lucide-react';
import { useKeyboard } from '../contexts/KeyboardContext';
import { lyrionApi } from '../utils/lyrionApi';

/**
 * Native Lyrion Server Player
 * Interfaces with LMS via JSON-RPC
 */
const LyrionServer = () => {
  const [serverUrl, setServerUrl] = useState('http://localhost:9000');
  const [customUrl, setCustomUrl] = useState('');
  const [showSettings, setShowSettings] = useState(false);

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

  const urlInputRef = useRef(null);
  const { showKeyboard } = useKeyboard();

  // Initialize and connect
  useEffect(() => {
    lyrionApi.setBaseUrl(serverUrl);
    connectToServer();
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

  const handleUrlChange = () => {
    if (customUrl) {
      setServerUrl(customUrl);
      setShowSettings(false);
      setIsLoading(true);
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

  const renderHeader = () => (
    <div className="bg-gradient-to-b from-hifi-gray to-hifi-dark border-b border-hifi-accent px-6 py-4 flex-shrink-0 z-20">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <div className="p-2 rounded-xl bg-blue-600 shadow-lg shadow-blue-600/20">
            <Server size={24} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-white tracking-wide">Lyrion Media Server</h1>
            <div className="flex items-center space-x-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]' : 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.6)]'}`}></span>
              <span className="text-xs text-hifi-silver font-medium">
                {isConnected ? 'Connesso' : 'Disconnesso'}
              </span>
              {!showSettings && (
                <span className="text-xs text-blue-400 opacity-70 ml-2">
                  {serverUrl}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          {players.length > 0 && (
            <select
              value={activePlayer?.playerid || ''}
              onChange={(e) => {
                const p = players.find(p => p.playerid === e.target.value);
                if (p) {
                  setActivePlayer(p);
                  setPlayerStatus(null); // Clear old status while fetching new
                  goHome();
                }
              }}
              className="bg-hifi-dark border border-hifi-accent text-white text-sm rounded-lg focus:ring-hifi-gold focus:border-hifi-gold block w-full p-2.5"
            >
              {players.map(p => (
                <option key={p.playerid} value={p.playerid}>
                  {p.name}
                </option>
              ))}
            </select>
          )}

          <motion.button
            onClick={() => setShowSettings(!showSettings)}
            className={`p-2.5 rounded-xl transition-all duration-200 ${showSettings ? 'bg-hifi-gold text-black' : 'bg-hifi-light hover:bg-hifi-accent text-white'}`}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            <Settings size={20} />
          </motion.button>
        </div>
      </div>

      <AnimatePresence>
        {showSettings && (
          <motion.div
            initial={{ height: 0, opacity: 0, marginTop: 0 }}
            animate={{ height: 'auto', opacity: 1, marginTop: 16 }}
            exit={{ height: 0, opacity: 0, marginTop: 0 }}
            className="overflow-hidden"
          >
            <div className="bg-hifi-light/50 border border-hifi-accent rounded-xl p-4 backdrop-blur-sm">
              <label className="block text-sm font-medium text-hifi-silver mb-2">URL Server (es. http://192.168.1.100:9000)</label>
              <div className="flex items-center space-x-3">
                <div
                  onClick={() => showKeyboard(urlInputRef, customUrl || serverUrl)}
                  className="flex-1 cursor-pointer"
                >
                  <input
                    ref={urlInputRef}
                    type="text"
                    placeholder={serverUrl}
                    value={customUrl}
                    onChange={(e) => setCustomUrl(e.target.value)}
                    className="w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-3 text-white focus:outline-none focus:border-hifi-gold focus:ring-1 focus:ring-hifi-gold cursor-pointer transition-all"
                    readOnly
                  />
                </div>
                <motion.button
                  onClick={handleUrlChange}
                  className="bg-hifi-gold text-black px-6 py-3 rounded-lg font-bold shadow-lg shadow-hifi-gold/20"
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  Connetti
                </motion.button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );

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
            if (currentView === 'albums') {
              return (
                <li key={idx} className="flex items-center justify-between p-4 bg-hifi-light/20 hover:bg-hifi-light/40 rounded-lg group cursor-pointer" onClick={() => navigateTo('tracks', item.album, { albumId: item.id })}>
                  <span className="text-lg text-white">{item.album} <span className="text-sm text-hifi-silver ml-2">{item.artist}</span></span>
                  <div className="flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button onClick={(e) => { e.stopPropagation(); handlePlayItem('album_id', item.id); }} className="p-2 bg-hifi-gold/20 text-hifi-gold rounded-full hover:bg-hifi-gold hover:text-black transition-colors"><Play size={20} fill="currentColor" /></button>
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
      <div className="flex-1 flex overflow-hidden bg-hifi-dark relative">
        {/* Left Side: Library Browser */}
        <div className="flex-1 flex flex-col bg-black/40 overflow-hidden">
          {/* Library Breadcrumbs/Header */}
          <div className="flex items-center px-6 py-4 border-b border-hifi-accent/30 bg-hifi-dark/80 backdrop-blur-sm sticky top-0 z-10 shrink-0">
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

        {/* Right Side: Persistent Player Sidebar */}
        <div className="w-[320px] md:w-[360px] flex-shrink-0 flex flex-col bg-hifi-dark border-l border-hifi-accent shadow-[-10px_0_30px_rgba(0,0,0,0.5)] z-20 relative overflow-hidden">
            {/* Blurred background */}
            <div
              className="absolute inset-0 opacity-20 bg-cover bg-center blur-xl scale-110 pointer-events-none"
              style={{ backgroundImage: artworkUrl ? `url(${artworkUrl})` : 'none' }}
            />
            <div className="absolute inset-0 bg-gradient-to-b from-black/60 via-hifi-dark to-hifi-dark pointer-events-none" />

            <div className="relative z-10 flex-1 flex flex-col p-4 md:p-6 h-full">
               <div className="text-center mb-2 md:mb-4 shrink-0">
                   <p className="text-[10px] md:text-xs tracking-widest text-hifi-silver uppercase">In Riproduzione</p>
               </div>

               {/* Artwork */}
               <div className="w-full flex-1 min-h-0 flex items-center justify-center mb-4 md:mb-6">
                  <motion.div
                    className="relative w-full max-w-[200px] aspect-square rounded-2xl overflow-hidden shadow-2xl border border-white/10 bg-hifi-gray flex items-center justify-center"
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ delay: 0.1 }}
                  >
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
                      <Music size={48} className="mb-2" />
                    </div>
                  </motion.div>
               </div>

               {/* Title & Artist */}
               <div className="text-center w-full mb-4 md:mb-6 shrink-0">
                  <h2 className="text-xl md:text-2xl font-bold text-white mb-1 md:mb-2 line-clamp-1">
                    {title}
                  </h2>
                  <p className="text-base md:text-lg text-hifi-gold mb-0.5 md:mb-1 font-medium truncate">
                    {artist}
                  </p>
                  <p className="text-xs md:text-sm text-hifi-silver/80 truncate">
                    {album}
                  </p>
               </div>

               {/* Progress Bar */}
               <div className="w-full mb-4 md:mb-6 px-2 shrink-0">
                  <div className="flex justify-between text-[10px] md:text-xs text-hifi-silver font-medium mb-1.5 md:mb-2">
                    <span>{formatTime(time)}</span>
                    <span>{formatTime(duration)}</span>
                  </div>
                  <div className="relative h-1.5 md:h-2 bg-white/10 rounded-full overflow-hidden cursor-pointer"
                       onClick={(e) => {
                         if (!duration) return;
                         const rect = e.currentTarget.getBoundingClientRect();
                         const clickX = e.clientX - rect.left;
                         const percentage = clickX / rect.width;
                         const newTime = duration * percentage;
                         handleAction(() => lyrionApi.seek(activePlayer.playerid, newTime));
                       }}>
                    <motion.div
                      className="absolute top-0 left-0 h-full bg-hifi-gold rounded-full"
                      style={{ width: `${progress}%` }}
                      layoutId="progressBar"
                    />
                  </div>
               </div>

               {/* Controls */}
               <div className="flex items-center justify-center space-x-4 md:space-x-6 mb-4 md:mb-6 shrink-0">
                  <motion.button
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.9 }}
                    className="p-2 md:p-3 text-white hover:text-hifi-gold transition-colors"
                    onClick={() => handleAction(() => lyrionApi.previous(activePlayer.playerid))}
                  >
                    <SkipBack size={24} className="md:w-7 md:h-7" />
                  </motion.button>

                  <motion.button
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    className="w-14 h-14 md:w-16 md:h-16 flex items-center justify-center bg-hifi-gold text-black rounded-full shadow-[0_0_15px_rgba(212,175,55,0.3)] hover:shadow-[0_0_25px_rgba(212,175,55,0.5)] transition-shadow"
                    onClick={() => handleAction(() => lyrionApi.togglePause(activePlayer.playerid))}
                  >
                    {isPlaying ? <Pause size={28} fill="currentColor" className="md:w-8 md:h-8" /> : <Play size={28} fill="currentColor" className="ml-1 md:w-8 md:h-8" />}
                  </motion.button>

                  <motion.button
                    whileHover={{ scale: 1.1 }}
                    whileTap={{ scale: 0.9 }}
                    className="p-2 md:p-3 text-white hover:text-hifi-gold transition-colors"
                    onClick={() => handleAction(() => lyrionApi.next(activePlayer.playerid))}
                  >
                    <SkipForward size={24} className="md:w-7 md:h-7" />
                  </motion.button>
               </div>

               {/* Volume */}
               <div className="flex items-center w-full px-2 mt-auto shrink-0 pt-2 border-t border-white/5">
                  <button
                    onClick={() => handleAction(() => lyrionApi.setVolume(activePlayer.playerid, volume === 0 ? 50 : 0))}
                    className="text-hifi-silver hover:text-white transition-colors mr-3"
                  >
                    {volume === 0 ? <VolumeX size={18} className="md:w-5 md:h-5" /> : <Volume2 size={18} className="md:w-5 md:h-5" />}
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
                    className="flex-1 h-1 md:h-1.5 bg-white/10 rounded-lg appearance-none cursor-pointer accent-hifi-gold"
                  />
               </div>
            </div>
        </div>
      </div>
    );  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="h-full w-full flex flex-col font-sans"
    >
      {renderHeader()}
      {renderContent()}
    </motion.div>
  );
};

export default LyrionServer;
