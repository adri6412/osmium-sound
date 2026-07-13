import React, { useState, useCallback } from 'react';

import ServerConnect from './pages/ServerConnect';
import HomeScreen from './pages/pwa/HomeScreen';
import NowPlayingScreen from './pages/pwa/NowPlayingScreen';
import MiniPlayer from './pages/pwa/MiniPlayer';
import SettingsHub from './pages/pwa/SettingsHub';
import DspSettings from './pages/pwa/DspSettings';
import Updates from './pages/pwa/Updates';
import SystemAdmin from './pages/pwa/SystemAdmin';
import Multiroom from './pages/pwa/Multiroom';
import { I18nProvider } from './i18n';
import { useLyrionPlayer } from './hooks/useLyrionPlayer';

// PWA shell, parallel to App.jsx (the Electron kiosk shell) but with its own
// Android-style screen flow (Home ⇄ Now Playing ⇄ Settings ⇄ appliance
// screens, each full-screen, with a docked mini player) instead of the
// kiosk's two-pane desktop layout — see the "Copertura iOS" plan's redesign
// pivot. Deliberately does NOT mount BootIntro (kiosk boot splash),
// Screensaver (idle screen on an always-on appliance display — meaningless
// on a phone the OS already locks), or KeyboardProvider/VirtualKeyboard
// (iOS Safari's native keyboard already handles text inputs).
const SCREENS = { HOME: 'home', SETTINGS: 'settings', DSP: 'dsp', UPDATES: 'updates', SYSTEM: 'system', MULTIROOM: 'multiroom' };

const AppPwaContent = () => {
  const [configured, setConfigured] = useState(
    () => localStorage.getItem('hifiPwaServerConfigured') === '1'
  );
  const [screen, setScreen] = useState(SCREENS.HOME);
  const [nowPlayingOpen, setNowPlayingOpen] = useState(false);

  const handleConnected = useCallback(() => setConfigured(true), []);
  const player = useLyrionPlayer();

  if (!configured) {
    return <ServerConnect onConnected={handleConnected} />;
  }

  const backToSettings = () => setScreen(SCREENS.SETTINGS);

  return (
    <div className="h-screen w-full flex flex-col bg-hifi-dark relative overflow-hidden">
      {screen === SCREENS.SETTINGS && (
        <SettingsHub
          onClose={() => setScreen(SCREENS.HOME)}
          onOpenDsp={() => setScreen(SCREENS.DSP)}
          onOpenUpdates={() => setScreen(SCREENS.UPDATES)}
          onOpenMultiroom={() => setScreen(SCREENS.MULTIROOM)}
          onOpenSystemAdmin={() => setScreen(SCREENS.SYSTEM)}
        />
      )}
      {screen === SCREENS.DSP && <DspSettings onClose={backToSettings} />}
      {screen === SCREENS.UPDATES && <Updates onClose={backToSettings} />}
      {screen === SCREENS.SYSTEM && <SystemAdmin onClose={backToSettings} />}
      {screen === SCREENS.MULTIROOM && <Multiroom onClose={backToSettings} />}

      {screen === SCREENS.HOME && (
        <>
          <div className="flex-1 min-h-0">
            <HomeScreen player={player} serverUrl={player.serverUrl} onOpenSettings={() => setScreen(SCREENS.SETTINGS)} />
          </div>
          <MiniPlayer player={player} onExpand={() => setNowPlayingOpen(true)} />
        </>
      )}

      {nowPlayingOpen && (
        <div className="absolute inset-0 z-50">
          <NowPlayingScreen player={player} onClose={() => setNowPlayingOpen(false)} />
        </div>
      )}
    </div>
  );
};

function AppPwa() {
  return (
    <I18nProvider>
      <AppPwaContent />
    </I18nProvider>
  );
}

export default AppPwa;
