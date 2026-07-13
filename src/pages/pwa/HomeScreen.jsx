import React, { useState, useEffect } from 'react';
import { Home, ChevronRight, Music, Radio, AppWindow, Settings as SettingsIcon } from 'lucide-react';
import { useI18n } from '../../i18n';
import LibraryList from './LibraryList';

const TABS = [
  { id: 'musica', labelKey: 'player.tabs.music', Icon: Music },
  { id: 'radio',  labelKey: 'player.tabs.radio',  Icon: Radio },
  { id: 'apps',   labelKey: 'player.tabs.apps',   Icon: AppWindow },
];

// Home/library screen: top TabLayout-style tab row + breadcrumb + flat list,
// replicating android-companion's home_group.xml (see phone-screenshots/
// 1-home.png). The kiosk's fourth "settings" tab becomes a full top-level
// screen here (see SettingsHub.jsx / AppPwa.jsx router) rather than an
// in-place tab, since Android settings is its own screen, not a tab panel.
const HomeScreen = ({ player, serverUrl, onOpenSettings }) => {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState('musica');
  const { currentView, navigationStack, goHome, goBack, goToBreadcrumb, openTabView } = player;

  useEffect(() => { openTabView('musica'); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleTabSwitch = (tabId) => {
    setActiveTab(tabId);
    openTabView(tabId);
  };

  const showBreadcrumb = navigationStack.length > 1;

  return (
    <div className="flex flex-col h-full bg-hifi-dark">
      {/* Tab row */}
      <div className="flex shrink-0 pwa-divider bg-hifi-gray overflow-x-auto">
        {TABS.map(({ id, labelKey, Icon }) => {
          const active = activeTab === id;
          return (
            <button key={id} onClick={() => handleTabSwitch(id)}
              className={`relative flex items-center gap-1.5 px-4 h-12 text-[13px] font-medium whitespace-nowrap transition-colors ${
                active ? 'text-hifi-gold' : 'text-hifi-silver/60'
              }`}>
              <Icon size={15} />
              <span>{t(labelKey)}</span>
              {active && <span className="absolute bottom-0 left-3 right-3 h-[2px] bg-hifi-gold" />}
            </button>
          );
        })}
        <button onClick={onOpenSettings}
          className="flex items-center px-4 h-12 text-hifi-silver/60 ml-auto">
          <SettingsIcon size={17} />
        </button>
      </div>

      {/* Breadcrumb */}
      {showBreadcrumb && (
        <div className="flex items-center gap-1 px-2 h-9 shrink-0 pwa-divider overflow-x-auto">
          <button onClick={goHome} className="p-1.5 text-hifi-silver/60">
            <Home size={14} />
          </button>
          {navigationStack.map((nav, idx) => (
            <React.Fragment key={idx}>
              {idx > 0 && <ChevronRight size={11} className="text-hifi-silver/30 shrink-0" />}
              <span
                onClick={() => goToBreadcrumb(idx)}
                className={`text-xs truncate max-w-[110px] ${
                  idx === navigationStack.length - 1 ? 'text-white font-medium' : 'text-hifi-silver/60'
                }`}>
                {nav.title}
              </span>
            </React.Fragment>
          ))}
          <button onClick={goBack} className="ml-auto shrink-0 text-xs px-2 text-hifi-silver/60">
            {t('common.back')}
          </button>
        </div>
      )}

      <LibraryList player={player} serverUrl={serverUrl} activeTab={activeTab} />
    </div>
  );
};

export default HomeScreen;
