import React, { useState } from 'react';
import { AnimatePresence } from 'framer-motion';

// Import pages
import Settings from './pages/Settings';
import YouTube from './pages/YouTube';
import Spotify from './pages/Spotify';
import LyrionServer from './pages/LyrionServer';

// Import components
import Sidebar from './components/Sidebar';
import VirtualKeyboard from './components/VirtualKeyboard';
import Screensaver from './components/Screensaver';

// Import contexts
import { KeyboardProvider, useKeyboard } from './contexts/KeyboardContext';

// Import lyrion API for playback state
import { lyrionApi } from './utils/lyrionApi';

// Main app component with simple state-based navigation
const AppContent = () => {
  const [currentPage, setCurrentPage] = useState('lyrion'); // Default to local library
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const { showKeyboard } = useKeyboard();
  const [isScreensaverActive, setIsScreensaverActive] = useState(false);
  const inactivityTimer = React.useRef(null);

  // Screensaver logic
  const resetInactivityTimer = React.useCallback(() => {
    setIsScreensaverActive(false);
    if (inactivityTimer.current) {
      clearTimeout(inactivityTimer.current);
    }

    inactivityTimer.current = setTimeout(async () => {
      // Check if music is playing before showing screensaver
      let isPlaying = false;
      try {
        const status = await lyrionApi.getServerStatus();
        const players = status?.players_loop || [];
        if (players.length > 0) {
          const playerStatus = await lyrionApi.getPlayerStatus(players[0].playerid);
          isPlaying = playerStatus?.mode === 'play';
        }
      } catch (err) {
        console.error("Failed to check player status for screensaver:", err);
      }

      if (!isPlaying) {
        setIsScreensaverActive(true);
      } else {
        // If playing, check again in 5 minutes
        resetInactivityTimer();
      }
    }, 5 * 60 * 1000); // 5 minutes
  }, []);

  React.useEffect(() => {
    // Start initial timer
    resetInactivityTimer();

    const activityEvents = [
      'mousedown', 'mousemove', 'keydown',
      'scroll', 'touchstart', 'click'
    ];

    const handleActivity = () => {
      resetInactivityTimer();
    };

    activityEvents.forEach(eventName => {
      document.addEventListener(eventName, handleActivity, true);
    });

    return () => {
      if (inactivityTimer.current) {
        clearTimeout(inactivityTimer.current);
      }
      activityEvents.forEach(eventName => {
        document.removeEventListener(eventName, handleActivity, true);
      });
    };
  }, [resetInactivityTimer]);

  React.useEffect(() => {
    const handleFocus = (e) => {
      const target = e.target;
      if (
        (target.tagName === 'INPUT' && (target.type === 'text' || target.type === 'password' || target.type === 'email' || target.type === 'number' || target.type === 'search' || target.type === 'tel' || target.type === 'url')) ||
        target.tagName === 'TEXTAREA'
      ) {
        // Store original inputmode before changing it
        if (!target.hasAttribute('data-original-inputmode')) {
          target.setAttribute('data-original-inputmode', target.getAttribute('inputmode') || '');
        }

        // Prevent default mobile keyboard without breaking selection/typing
        target.setAttribute('inputmode', 'none');

        const inputRef = { current: target };
        showKeyboard(inputRef, target.value || '');
      }
    };

    const handleClick = (e) => {
      const target = e.target;
      if (
        (target.tagName === 'INPUT' && (target.type === 'text' || target.type === 'password' || target.type === 'email' || target.type === 'number' || target.type === 'search' || target.type === 'tel' || target.type === 'url')) ||
        target.tagName === 'TEXTAREA'
      ) {
        const inputRef = { current: target };
        showKeyboard(inputRef, target.value || '');
      }
    };

    const handleFocusOut = (e) => {
      const target = e.target;
      if (
        (target.tagName === 'INPUT' && (target.type === 'text' || target.type === 'password' || target.type === 'email' || target.type === 'number' || target.type === 'search' || target.type === 'tel' || target.type === 'url')) ||
        target.tagName === 'TEXTAREA'
      ) {
        // Restore original inputmode state
        if (target.hasAttribute('data-original-inputmode')) {
          const original = target.getAttribute('data-original-inputmode');
          if (original) {
            target.setAttribute('inputmode', original);
          } else {
            target.removeAttribute('inputmode');
          }
          target.removeAttribute('data-original-inputmode');
        }
      }
    };

    // Use capturing phase to ensure we catch events before they are stopped
    document.addEventListener('focusin', handleFocus, true);
    document.addEventListener('focusout', handleFocusOut, true);
    document.addEventListener('click', handleClick, true);

    return () => {
      document.removeEventListener('focusin', handleFocus, true);
      document.removeEventListener('focusout', handleFocusOut, true);
      document.removeEventListener('click', handleClick, true);
    };
  }, [showKeyboard]);

  const renderPage = () => {
    switch (currentPage) {
      case 'settings':
        return <Settings />;
      case 'youtube':
        return <YouTube />;
      case 'spotify':
        return <Spotify />;
      case 'lyrion':
      default:
        return <LyrionServer onNavigate={setCurrentPage} />;
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-hifi-dark overflow-hidden relative">
      <Sidebar
        onNavigate={setCurrentPage}
        currentPage={currentPage}
        isOpen={isSidebarOpen}
        setIsOpen={setIsSidebarOpen}
      />
      
      <main className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {renderPage()}
        </AnimatePresence>
      </main>

      <Screensaver
        isActive={isScreensaverActive}
        onWake={() => setIsScreensaverActive(false)}
      />
    </div>
  );
};

function App() {
  return (
    <KeyboardProvider>
      <AppContent />
      <VirtualKeyboard />
    </KeyboardProvider>
  );
}

export default App;

