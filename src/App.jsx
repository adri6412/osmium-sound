import React from 'react';

import LyrionServer from './pages/LyrionServer';
import SetupWizard from './pages/SetupWizard';
import VirtualKeyboard from './components/VirtualKeyboard';
import Screensaver from './components/Screensaver';
import BootIntro from './components/BootIntro';
import { KeyboardProvider, useKeyboard } from './contexts/KeyboardContext';
import { I18nProvider } from './i18n';
import { lyrionApi } from './utils/lyrionApi';

const AppContent = () => {
  // Boot intro: a 5s logo animation shown over everything at startup, then
  // faded out to reveal the UI (which mounts/loads underneath meanwhile).
  const [showIntro, setShowIntro] = React.useState(true);
  const [introFading, setIntroFading] = React.useState(false);
  // Run the compositor at 60 FPS while the intro animates (smooth on the x86
  // mini-PC), then drop back to the steady-state 30 FPS cap once it's done.
  React.useEffect(() => {
    if (showIntro) window.electronAPI?.setFrameRate?.(60);
  }, [showIntro]);
  const handleIntroDone = React.useCallback(() => {
    setIntroFading(true);
    setTimeout(() => {
      setShowIntro(false);
      window.electronAPI?.setFrameRate?.(30);
    }, 600);
  }, []);
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

  // Apply the saved mouse-pointer preference app-wide on startup. Default is
  // hidden (touchscreen); Settings → Mouse pointer flips it for mouse users.
  React.useEffect(() => {
    const show = localStorage.getItem('hifiShowPointer') === '1';
    document.documentElement.classList.toggle('hifi-hide-cursor', !show);
  }, []);

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
      {showIntro && (
        <div
          className="fixed inset-0 z-[10000] bg-black"
          style={{ opacity: introFading ? 0 : 1, transition: 'opacity 600ms ease', pointerEvents: introFading ? 'none' : 'auto' }}
        >
          <BootIntro onDone={handleIntroDone} />
        </div>
      )}
    </div>
  );
};

function App() {
  return (
    <I18nProvider>
      <KeyboardProvider>
        <AppContent />
        <VirtualKeyboard />
      </KeyboardProvider>
    </I18nProvider>
  );
}

export default App;
