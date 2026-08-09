import React from 'react';
import { createPortal } from 'react-dom';

import LyrionServer from './pages/LyrionServer';
import SetupWizard from './pages/SetupWizard';
import InstallWizard from './pages/InstallWizard';
import VirtualKeyboard from './components/VirtualKeyboard';
import Screensaver from './components/Screensaver';
import BootIntro from './components/BootIntro';
import UsbDetectedModal from './components/UsbDetectedModal';
import UpdatePlanOverlay from './components/UpdatePlanOverlay';
import { SCALED_CANVAS_ID } from './components/ScaledCanvas';
import { KeyboardProvider, useKeyboardActions } from './contexts/KeyboardContext';
import { I18nProvider } from './i18n';
import { lyrionApi } from './utils/lyrionApi';
import { systemAPI } from './utils/api';

// Mirrors useLyrionPlayer's connectToServer player-selection logic (see
// src/hooks/useLyrionPlayer.js): `players_loop` isn't necessarily "this
// appliance first" — the companion app auto-launches Squeezelite/
// SqueezePlayer on the phone as a second LMS player, and LMS can list it
// ahead of this kiosk's own player. The screensaver wake/sleep checks below
// used to just take `players_loop[0]` — on a setup with a second player,
// that's a coinflip on whether it lands on the kiosk's own player or the
// phone's, and if it lands on the phone's (stopped) player, playback started
// remotely on the *kiosk* keeps reading as "not playing" and the screensaver
// never wakes. Resolve the same way the rest of the app does: prefer the
// player matching this device's own squeezelite name.
const isLocalPlayerPlaying = async () => {
  const status = await lyrionApi.getServerStatus();
  const players = status?.players_loop || [];
  if (players.length === 0) return false;
  const nameRes = await systemAPI.getPlayerName().catch(() => null);
  const localName = nameRes?.success ? nameRes.data?.name : null;
  const player = (localName && players.find(p => p.name === localName)) || players[0];
  const ps = await lyrionApi.getPlayerStatus(player.playerid);
  return ps?.mode === 'play';
};

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

  // Boot mode: this live session may have started from the "Install Osmium
  // Sound" boot entry (kernel param hifi.installer=1) instead of "Try Osmium
  // Sound" — see api_server.py get_boot_mode(). null = not resolved yet
  // (render nothing rather than flash the normal kiosk UI first).
  const [bootMode, setBootMode] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    (async () => {
      // hifi-api.service isn't ordered before the X session, so on a cold
      // live boot this can race Flask still starting up — a single failed
      // fetch here used to silently fall back to 'live' and drop straight
      // into the kiosk UI instead of the installer. Retry for a few seconds
      // instead of giving up after one attempt.
      let mode = 'live';
      for (let attempt = 0; attempt < 20 && alive; attempt++) {
        const res = await systemAPI.getBootMode();
        if (res.success && res.data?.mode) { mode = res.data.mode; break; }
        await new Promise((r) => setTimeout(r, 500));
      }
      if (alive) setBootMode(mode);
    })();
    return () => { alive = false; };
  }, []);

  // The localStorage flag only records a wizard completed ON THIS SCREEN. If
  // setup ran through the provisioning flow from the web instead (headless
  // first, GUI re-enabled later), the flag was never written here — ask the
  // system whether setup is already done and skip the wizard if so. Feature-
  // detected: on older systems the endpoint is missing and nothing changes.
  React.useEffect(() => {
    if (!showWizard) return;
    let alive = true;
    (async () => {
      try {
        const res = await systemAPI.getProvisionStatus();
        if (alive && res.success && res.data?.pending === false && res.data?.completed === true) {
          localStorage.setItem('firstSetupComplete', 'true');
          setShowWizard(false);
        }
      } catch (_) {}
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const inactivityTimer = React.useRef(null);
  // Bumped on every resetInactivityTimer() call (any activity, or the timer
  // re-arming itself). The 5-minute callback below is async — clearTimeout
  // can't cancel it once it has started running — so without this token a
  // callback started right before playback began could resolve `isPlaying`
  // from a stale read and pop the screensaver over active audio. Any call
  // that supersedes this one bumps the token, and the callback checks it's
  // still current before acting on what it found.
  const inactivityTokenRef = React.useRef(0);
  const { showKeyboard } = useKeyboardActions();

  const resetInactivityTimer = React.useCallback(() => {
    setIsScreensaverActive(false);
    if (inactivityTimer.current) clearTimeout(inactivityTimer.current);
    const myToken = ++inactivityTokenRef.current;
    inactivityTimer.current = setTimeout(async () => {
      let isPlaying = false;
      try {
        isPlaying = await isLocalPlayerPlaying();
      } catch (_) {}
      if (inactivityTokenRef.current !== myToken) return; // superseded — discard this stale read
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

  // Playback can start remotely (companion app, Lyrion web UI, another
  // controller) with no touch/mouse activity on the kiosk itself. Once the
  // screensaver is up, poll for that case and wake it — otherwise it would
  // keep covering the screen for the whole track.
  React.useEffect(() => {
    if (!isScreensaverActive) return;
    const poll = setInterval(async () => {
      try {
        if (await isLocalPlayerPlaying()) resetInactivityTimer();
      } catch (_) {}
    }, 10 * 1000);
    return () => clearInterval(poll);
  }, [isScreensaverActive, resetInactivityTimer]);

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
  // Installer sessions always show the cursor (no touchscreen yet, no saved
  // preference to read either) — this CSS-level hide is independent of, and
  // otherwise overrides, the X11/unclutter check in .xsession.
  React.useEffect(() => {
    if (bootMode === 'installer') {
      document.documentElement.classList.remove('hifi-hide-cursor');
      return;
    }
    const show = localStorage.getItem('hifiShowPointer') === '1';
    document.documentElement.classList.toggle('hifi-hide-cursor', !show);
  }, [bootMode]);

  // Allow re-opening the setup wizard from Settings
  React.useEffect(() => {
    const open = () => setShowWizard(true);
    window.addEventListener('hifi-open-wizard', open);
    return () => window.removeEventListener('hifi-open-wizard', open);
  }, []);

  // Global "USB drive just plugged in" prompt (offers to jump to Settings →
  // Music sources to adopt it). Runs regardless of which screen is showing —
  // SourcesManager.jsx's own poll only runs while that screen is open. Polls
  // sources_server.py directly (not through api.js) to match the pattern
  // SourcesManager/InternalDisks already use for that service.
  const [usbPrompt, setUsbPrompt] = React.useState(null);
  const seenUsbRef = React.useRef(new Set());
  const dismissedUsbRef = React.useRef(new Set());
  // The very first poll just establishes the baseline (whatever's already
  // plugged in at that point) — only insertions seen on a *later* poll are
  // "new", so a stick left in the appliance across a reboot doesn't prompt.
  const usbBaselineDoneRef = React.useRef(false);
  // Suppressed while the user is already on Settings → Music sources (they
  // can see and adopt the drive right there — a popup on top would be
  // redundant) — SourcesManager.jsx dispatches this on mount/unmount.
  const [sourcesPageActive, setSourcesPageActive] = React.useState(false);
  React.useEffect(() => {
    const handler = (e) => setSourcesPageActive(!!e.detail);
    window.addEventListener('hifi-sources-page-active', handler);
    return () => window.removeEventListener('hifi-sources-page-active', handler);
  }, []);
  React.useEffect(() => {
    // Don't start prompting mid-setup or during the boot animation.
    if (showWizard || showIntro) return undefined;
    const poll = async () => {
      let disks = [];
      try {
        const r = await fetch('http://localhost:8080/api/usb');
        const d = await r.json();
        disks = d.disks || [];
      } catch (_) { return; }
      const currentIds = new Set(disks.map((dk) => dk.path || dk.mountpoint));
      // Forget dismissals for drives that are no longer connected, so
      // unplugging and reinserting the same stick prompts again.
      for (const id of dismissedUsbRef.current) {
        if (!currentIds.has(id)) dismissedUsbRef.current.delete(id);
      }
      if (!usbBaselineDoneRef.current) {
        usbBaselineDoneRef.current = true;
      } else if (!sourcesPageActive) {
        const fresh = disks.find((dk) => {
          const id = dk.path || dk.mountpoint;
          return id && !seenUsbRef.current.has(id) && !dismissedUsbRef.current.has(id);
        });
        if (fresh) setUsbPrompt(fresh);
      }
      seenUsbRef.current = currentIds;
    };
    poll();
    const id = setInterval(poll, 4000);
    return () => clearInterval(id);
  }, [showWizard, showIntro, sourcesPageActive]);

  const dismissUsbPrompt = () => {
    if (usbPrompt) dismissedUsbRef.current.add(usbPrompt.path || usbPrompt.mountpoint);
    setUsbPrompt(null);
  };
  const mountUsbPrompt = () => {
    setUsbPrompt(null);
    window.dispatchEvent(new CustomEvent('hifi-open-settings-section', { detail: 'custom-sources' }));
  };

  // Boot mode not resolved yet: render nothing rather than flash the normal
  // kiosk UI before we know whether this is an installer session.
  if (bootMode === null) {
    return <div className="h-full w-full overflow-hidden bg-hifi-dark relative" />;
  }
  // Installer session: replace the whole app tree — there's no player/
  // sources content to show underneath while installing to disk.
  if (bootMode === 'installer') {
    return (
      <div className="h-full w-full overflow-hidden bg-hifi-dark relative">
        <InstallWizard />
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-hidden bg-hifi-dark relative">
      <LyrionServer />
      {showWizard && <SetupWizard onComplete={() => setShowWizard(false)} />}
      <Screensaver isActive={isScreensaverActive && !showWizard} onWake={() => setIsScreensaverActive(false)} />
      {usbPrompt && <UsbDetectedModal disk={usbPrompt} onMount={mountUsbPrompt} onCancel={dismissUsbPrompt} />}
      <UpdatePlanOverlay />
      {showIntro && createPortal(
        <div
          className="absolute inset-0 z-[10000] bg-black"
          style={{ opacity: introFading ? 0 : 1, transition: 'opacity 600ms ease', pointerEvents: introFading ? 'none' : 'auto' }}
        >
          <BootIntro onDone={handleIntroDone} />
        </div>,
        document.getElementById(SCALED_CANVAS_ID) || document.body
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
