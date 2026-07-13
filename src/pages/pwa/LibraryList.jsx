import React from 'react';
import {
  User, Disc, Folder, Music, ListMusic, Radio, AppWindow, Play, Search as SearchIcon,
} from 'lucide-react';
import { lyrionApi } from '../../utils/lyrionApi';
import { safeUrl } from '../../hooks/useLyrionPlayer';
import { useI18n } from '../../i18n';

// Flat Android-style row (48dp art/icon + title/subtitle, 1dp divider),
// mirrors android-companion's list_item.xml. One row shape for every
// currentView instead of a bespoke card/grid per view (kiosk's approach) —
// closer to how the real app looks (see phone-screenshots/1-home.png,
// 3-browse-albums-and-context-menu.png).
const Row = ({ art, Icon, title, subtitle, onClick, onPlay }) => (
  <li onClick={onClick} className="pwa-row-clickable pwa-divider">
    <div className="w-11 h-11 shrink-0 rounded-flat bg-hifi-light flex items-center justify-center overflow-hidden">
      {art
        ? <img src={safeUrl(art)} alt="" className="w-full h-full object-cover" loading="lazy" decoding="async"
            onError={(e) => { e.target.style.display = 'none'; }} />
        : <Icon size={20} className="text-hifi-silver/70" />}
    </div>
    <div className="min-w-0 flex-1">
      <p className="text-[15px] text-white truncate">{title}</p>
      {subtitle && <p className="text-[13px] text-hifi-silver/60 truncate">{subtitle}</p>}
    </div>
    {onPlay && (
      <button onClick={(e) => { e.stopPropagation(); onPlay(); }}
        className="shrink-0 p-2 text-hifi-gold">
        <Play size={18} fill="currentColor" />
      </button>
    )}
  </li>
);

// Local top-level sections shown on the "musica" tab's home view — same set
// as the kiosk's tile grid, rendered here as flat rows to match Android.
const MUSIC_HOME_SECTIONS = (t) => [
  { id: 'artists',   Icon: User,      label: t('player.titles.artists') },
  { id: 'albums',    Icon: Disc,      label: t('player.titles.albums') },
  { id: 'folders',   Icon: Folder,    label: t('player.titles.folders') },
  { id: 'playlists', Icon: ListMusic, label: t('player.titles.playlists') },
];

const LibraryList = ({ player, serverUrl, activeTab }) => {
  const { t } = useI18n();
  const {
    currentView, libraryData, libraryLoading, visibleCount, navigationStack,
    menuSearch, setMenuSearch, searchText, setSearchText, submitMenuSearch,
    listScrollRef, handleLibraryScroll, navigateTo, handlePlayItem,
    resolveMenuIcon, handleMenuItem, menuBase, activePlayer, handleAction,
  } = player;

  if (menuSearch) {
    return (
      <div className="p-4 space-y-3">
        <p className="text-sm font-medium text-white">{menuSearch.title}</p>
        <input
          type="text"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') submitMenuSearch(); }}
          placeholder={t('player.searchPlaceholder')}
          className="pwa-input"
          autoFocus
        />
        <div className="flex gap-2">
          <button onClick={() => { setMenuSearch(null); setSearchText(''); }}
            className="pwa-btn-outlined flex-1">
            {t('common.cancel')}
          </button>
          <button onClick={submitMenuSearch} className="pwa-btn-filled flex-1 flex items-center justify-center gap-2">
            <SearchIcon size={15} /> {t('common.search')}
          </button>
        </div>
      </div>
    );
  }

  if (libraryLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-hifi-gold border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (currentView === 'home' && activeTab === 'musica') {
    return (
      <ul>
        {MUSIC_HOME_SECTIONS(t).map(({ id, Icon, label }) => (
          <Row key={id} Icon={Icon} title={label}
            onClick={() => navigateTo(id, label)} />
        ))}
      </ul>
    );
  }

  const items = libraryData.slice(0, visibleCount);

  const rows = items.map((item, idx) => {
    if (currentView === 'artists') return {
      key: idx, Icon: User, title: item.artist,
      onClick: () => navigateTo('albums', item.artist, { artistId: item.id }),
      onPlay: () => handlePlayItem('artist_id', item.id),
    };
    if (currentView === 'albums') return {
      key: item.id || idx,
      art: (item.artwork_track_id || item.id) ? lyrionApi.getArtworkUrl(item.artwork_track_id || item.id, 100) : null,
      Icon: Disc, title: item.album, subtitle: item.artist,
      onClick: () => navigateTo('tracks', item.album, { albumId: item.id }),
      onPlay: () => handlePlayItem('album_id', item.id),
    };
    if (currentView === 'tracks' || currentView === 'playlist_tracks') return {
      key: idx, Icon: Music, title: item.title,
      onClick: () => handlePlayItem('track_id', item.id),
    };
    if (currentView === 'playlists') return {
      key: item.id || idx, Icon: ListMusic, title: item.playlist,
      onClick: () => navigateTo('playlist_tracks', item.playlist, { playlistId: item.id }),
      onPlay: () => handlePlayItem('playlist_id', item.id),
    };
    if (currentView === 'folders') {
      const isDir = item.type === 'folder';
      return {
        key: idx, Icon: isDir ? Folder : Music, title: item.filename || item.title,
        onClick: () => isDir
          ? navigateTo('folders', item.filename, { folderId: item.id })
          : handlePlayItem('track_id', item.id),
        onPlay: () => handlePlayItem(isDir ? 'folder_id' : 'track_id', item.id),
      };
    }
    if (currentView === 'radios' || currentView === 'apps') return {
      key: idx,
      art: item.icon ? (item.icon.startsWith('http') ? item.icon : `${serverUrl}/${item.icon}`) : null,
      Icon: currentView === 'radios' ? Radio : AppWindow, title: item.name,
      onClick: () => navigateTo('plugin_items', item.name, { pluginCmd: item.cmd }),
    };
    if (currentView === 'menu_home' || currentView === 'menu') {
      const iconUrl = resolveMenuIcon(item);
      const play = lyrionApi.resolveMenuAction(menuBase, item, 'play')
        || lyrionApi.resolveMenuAction(menuBase, item, 'playall');
      const isNav = !!(lyrionApi.resolveMenuAction(menuBase, item, 'go') || item.input);
      return {
        key: item.id || idx, art: iconUrl, Icon: isNav ? AppWindow : Music,
        title: item.text || item.name,
        onClick: () => handleMenuItem(item),
        onPlay: play ? () => handleAction(() => lyrionApi.menuDo(activePlayer.playerid, play)) : null,
      };
    }
    if (currentView === 'plugin_items') {
      const params = navigationStack[navigationStack.length - 1].params;
      const pluginCmd = params?.pluginCmd;
      const hasItems = item.hasitems === 1 || item.type === 'link';
      const isAudio = item.isaudio === 1 || item.type === 'audio';
      const play = () => handleAction(() => lyrionApi.playPluginItem(activePlayer.playerid, pluginCmd, item.id || item.play));
      return {
        key: idx,
        art: item.icon ? (item.icon.startsWith('http') ? item.icon : `${serverUrl}/${item.icon}`) : null,
        Icon: hasItems ? Folder : Music, title: item.name || item.title,
        onClick: () => {
          if (hasItems) navigateTo('plugin_items', item.name || item.title, { pluginCmd, itemId: item.id });
          else if (isAudio || item.play) play();
        },
        onPlay: (isAudio || item.play) ? play : null,
      };
    }
    return null;
  }).filter(Boolean);

  return (
    <div ref={listScrollRef} onScroll={handleLibraryScroll} className="flex-1 overflow-y-auto">
      <ul>
        {rows.map((r) => <Row key={r.key} {...r} />)}
      </ul>
    </div>
  );
};

export default LibraryList;
