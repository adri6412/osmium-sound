import React from 'react';

import LyrionServer from './pages/LyrionServer';
import SetupWizard from './pages/SetupWizard';
import VirtualKeyboard from './components/VirtualKeyboard';
import Screensaver from './components/Screensaver';
import { KeyboardProvider, useKeyboard } from './contexts/KeyboardContext';
import { lyrionApi } from './utils/lyrionApi';

const AppContent = () => {
  const [isScreensaverActive, setIsScreensaverActive] = React.useState(false);
  const [showWizard, setShowWizard] = React.useState(
    () => localStorage.getItem('firstSetupComplete') !== 'true'
  );
  const inactivityTimer = React.useRef(null);
  const { showKeyboard } = useKeyboard();

  const resetInactivityTimer = React.useCallback(() => {
    setIsScreensaverActive(false);
    if (inactivityTimer.current) clearTimeout(inactivityTimer.current);
    inactivityTimer.current = setTimeout(async () => {
      let isPlaying = false;
      try {
        const status = await lyrionApi.getServerStatus();
        const players = status?.players_loop || [];
        if (players.length > 0) {
          const ps = await lyrionApi.getPlayerStatus(players[0].playerid);
          isPlaying = ps?.mode === 'play';
        }
      } catch (_) {}
      if (!isPlaying) setIsScreensaverActive(true);
      else resetInactivityTimer();
    }, 5 * 60 * 1000);
  }, []);

  React.useEffect(() => {
    resetInactivityTimer();
    const events = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click'];
    events.forEach(e => document.addEventListener(e, resetInactivityTimer, true));
    return () => {
      if (inactivityTimer.current) clearTimeout(inactivityTimer.current);
      events.forEach(e => document.removeEventListener(e, resetInactivityTimer, true));
    };
  }, [resetInactivityTimer]);

  // Auto-show virtual keyboard on text input focus
  React.useEffect(() => {
    const textTypes = ['text', 'password', 'email', 'number', 'search', 'tel', 'url'];
    const isTextInput = (t) =>
      (t.tagName === 'INPUT' && textTypes.includes(t.type)) || t.tagName === 'TEXTAREA';

    const handleFocus = (e) => {
      if (!isTextInput(e.target)) return;
      const t = e.target;
      if (!t.hasAttribute('data-original-inputmode'))
        t.setAttribute('data-original-inputmode', t.getAttribute('inputmode') || '');
      t.setAttribute('inputmode', 'none');
      showKeyboard({ current: t }, t.value || '');
    };
    const handleClick = (e) => {
      if (!isTextInput(e.target)) return;
      showKeyboard({ current: e.target }, e.target.value || '');
    };
    const handleFocusOut = (e) => {
      if (!isTextInput(e.target)) return;
      const t = e.target;
      if (t.hasAttribute('data-original-inputmode')) {
        const orig = t.getAttribute('data-original-inputmode');
        if (orig) t.setAttribute('inputmode', orig);
        else t.removeAttribute('inputmode');
        t.removeAttribute('data-original-inputmode');
      }
    };

    document.addEventListener('focusin', handleFocus, true);
    document.addEventListener('focusout', handleFocusOut, true);
    document.addEventListener('click', handleClick, true);
    return () => {
      document.removeEventListener('focusin', handleFocus, true);
      document.removeEventListener('focusout', handleFocusOut, true);
      document.removeEventListener('click', handleClick, true);
    };
  }, [showKeyboard]);

  // Allow re-opening the setup wizard from Settings
  React.useEffect(() => {
    const open = () => setShowWizard(true);
    window.addEventListener('hifi-open-wizard', open);
    return () => window.removeEventListener('hifi-open-wizard', open);
  }, []);

  return (
    <div className="h-screen w-screen overflow-hidden bg-hifi-dark relative">
      <LyrionServer />
      {showWizard && <SetupWizard onComplete={() => setShowWizard(false)} />}
      <Screensaver isActive={isScreensaverActive && !showWizard} onWake={() => setIsScreensaverActive(false)} />
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
