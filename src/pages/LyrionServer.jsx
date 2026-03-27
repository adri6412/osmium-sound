import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Server, Settings, Play, Pause, SkipBack, SkipForward,
  Volume2, VolumeX, Music, AlertCircle, RefreshCw
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

  const urlInputRef = useRef(null);
  const { showKeyboard } = useKeyboard();
  const pollIntervalRef = useRef(null);

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
  }, [activePlayer]); // This ensures the interval always has the latest activePlayer context

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

  // Render components

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

  const renderPlayerContent = () => {
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

    // Main Player UI
    const playlistIndex = playerStatus?.playlist_cur_index ? parseInt(playerStatus.playlist_cur_index) : 0;
    const currentTrack = playerStatus?.playlist_loop?.[playlistIndex] || {};

    const title = currentTrack.title || 'Nessuna traccia';
    const artist = currentTrack.artist || 'Artista Sconosciuto';
    const album = currentTrack.album || 'Album Sconosciuto';
    const isPlaying = playerStatus?.mode === 'play';
    const volume = playerStatus?.mixer_volume || 0;
    const duration = currentTrack.duration || 0;
    const time = playerStatus?.time || 0;
    const progress = duration > 0 ? (time / duration) * 100 : 0;

    // Attempt to get artwork
    const artworkUrl = currentTrack.id ? lyrionApi.getArtworkUrl(currentTrack.id, 600) : null;

    return (
      <div className="flex-1 relative flex flex-col overflow-hidden bg-black">
        {/* Dynamic Background */}
        <div
          className="absolute inset-0 opacity-20 bg-cover bg-center blur-3xl scale-110 transition-all duration-1000"
          style={{ backgroundImage: artworkUrl ? `url(${artworkUrl})` : 'none' }}
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black via-black/60 to-transparent" />

        <div className="relative z-10 flex-1 flex flex-col p-8">

          {/* Main Content Area (Cover + Info) */}
          <div className="flex-1 flex flex-row items-center justify-center gap-12 max-w-6xl mx-auto w-full">

            {/* Cover Art */}
            <motion.div
              className="w-80 h-80 sm:w-96 sm:h-96 rounded-2xl overflow-hidden shadow-2xl flex-shrink-0 bg-hifi-dark border border-white/10"
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: 0.5 }}
            >
              {artworkUrl ? (
                <img
                  src={artworkUrl}
                  alt="Album Art"
                  className="w-full h-full object-cover"
                  onError={(e) => { e.target.style.display = 'none'; e.target.nextSibling.style.display = 'flex'; }}
                />
              ) : null}
              {/* Fallback Cover */}
              <div
                className="w-full h-full bg-gradient-to-br from-hifi-gray to-hifi-dark flex flex-col items-center justify-center text-hifi-silver/30"
                style={{ display: artworkUrl ? 'none' : 'flex' }}
              >
                <Music size={80} className="mb-4" />
                <span className="text-xl font-medium tracking-widest uppercase">Lyrion</span>
              </div>
            </motion.div>

            {/* Track Info */}
            <div className="flex flex-col justify-center max-w-xl min-w-[300px]">
              <motion.div
                initial={{ x: 20, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                transition={{ duration: 0.5, delay: 0.1 }}
              >
                <h2 className="text-5xl font-bold text-white mb-4 line-clamp-2 leading-tight">
                  {title}
                </h2>
                <p className="text-2xl text-hifi-gold mb-2 font-medium truncate">
                  {artist}
                </p>
                <p className="text-xl text-hifi-silver/80 truncate">
                  {album}
                </p>
              </motion.div>

              {/* Bitrate / Info tags if available */}
              {(currentTrack.bitrate || currentTrack.type) && (
                <div className="mt-6 flex flex-wrap gap-2">
                  {currentTrack.type && (
                    <span className="px-3 py-1 bg-white/10 rounded-full text-xs font-semibold text-white/80 uppercase tracking-wider backdrop-blur-md">
                      {currentTrack.type}
                    </span>
                  )}
                  {currentTrack.bitrate && (
                    <span className="px-3 py-1 bg-white/10 rounded-full text-xs font-semibold text-white/80 backdrop-blur-md">
                      {currentTrack.bitrate}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Controls Area */}
          <div className="mt-8 max-w-4xl mx-auto w-full">

            {/* Progress Bar */}
            <div className="mb-8">
              <div className="flex justify-between text-sm text-hifi-silver font-medium mb-3">
                <span>{formatTime(time)}</span>
                <span>{formatTime(duration)}</span>
              </div>
              <div className="relative h-2 bg-white/10 rounded-full overflow-hidden cursor-pointer"
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

            {/* Transport Controls & Volume */}
            <div className="flex items-center justify-between">

              {/* Empty space for balance */}
              <div className="w-1/4"></div>

              {/* Center Controls */}
              <div className="flex-1 flex justify-center items-center space-x-8">
                <motion.button
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  className="p-4 text-white hover:text-hifi-gold transition-colors"
                  onClick={() => handleAction(() => lyrionApi.previous(activePlayer.playerid))}
                >
                  <SkipBack size={36} />
                </motion.button>

                <motion.button
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                  className="w-20 h-20 flex items-center justify-center bg-hifi-gold text-black rounded-full shadow-[0_0_30px_rgba(212,175,55,0.3)] hover:shadow-[0_0_40px_rgba(212,175,55,0.5)] transition-shadow"
                  onClick={() => handleAction(() => lyrionApi.togglePause(activePlayer.playerid))}
                >
                  {isPlaying ? <Pause size={40} fill="currentColor" /> : <Play size={40} fill="currentColor" className="ml-2" />}
                </motion.button>

                <motion.button
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.9 }}
                  className="p-4 text-white hover:text-hifi-gold transition-colors"
                  onClick={() => handleAction(() => lyrionApi.next(activePlayer.playerid))}
                >
                  <SkipForward size={36} />
                </motion.button>
              </div>

              {/* Volume Control */}
              <div className="w-1/4 flex items-center justify-end space-x-4">
                <button
                  onClick={() => handleAction(() => lyrionApi.setVolume(activePlayer.playerid, volume === 0 ? 50 : 0))}
                  className="text-hifi-silver hover:text-white transition-colors"
                >
                  {volume === 0 ? <VolumeX size={24} /> : <Volume2 size={24} />}
                </button>
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={volume}
                  onChange={(e) => {
                    const newVol = parseInt(e.target.value);
                    // Optimistic update for smoother UI
                    setPlayerStatus(prev => ({...prev, mixer_volume: newVol}));
                    handleAction(() => lyrionApi.setVolume(activePlayer.playerid, newVol));
                  }}
                  className="w-32 h-2 bg-white/10 rounded-lg appearance-none cursor-pointer accent-hifi-gold"
                />
              </div>
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
      className="h-full w-full flex flex-col font-sans"
    >
      {renderHeader()}
      {renderPlayerContent()}
    </motion.div>
  );
};

export default LyrionServer;
