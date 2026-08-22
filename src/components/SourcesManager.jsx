import React, { useState, useEffect, useCallback } from 'react';
import {
  ChevronRight, Network, HardDrive, FolderPlus, Trash2, Plus, AlertTriangle,
  ListMusic, Share2, Library, Loader2,
} from 'lucide-react';
import { useI18n } from '../i18n';
import { useKeyboardInput } from '../hooks/useKeyboardInput';
import InternalDisks, { SmbCard } from './InternalDisks';

// The on-device sources manager (mount/list SMB + USB + local folders) runs as a
// small HTTP service on the appliance itself. Talk to it natively so the UI
// matches the rest of Settings (no embedded web page).
const SRC = 'http://localhost:8080';

const isErr = (m) => /error|errore|fallit|fail|non valido|invalid/i.test(m || '');

const j = async (url, opts) => {
  const r = await fetch(SRC + url, opts);
  return r.json();
};
const post = (url, body) =>
  j(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

const fmtBytes = (n) => {
  const gb = Number(n) / 1024 ** 3;
  if (!Number.isFinite(gb) || gb <= 0) return '';
  if (gb >= 1000) return `${(gb / 1024).toFixed(1)} TB`;
  return gb >= 10 ? `${Math.round(gb)} GB` : `${gb.toFixed(1)} GB`;
};

const input = 'w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-3 text-white focus:outline-none focus:border-hifi-gold';
const ghostBtn = 'bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white py-3 px-4 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors';
const smallBtn = 'text-xs py-1.5 px-3 rounded-md bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white';

/**
 * One band of the Music sources page: a tappable header that expands in
 * place. Chosen over a nested drill-down because Settings.jsx already spends
 * one level of back-navigation getting here — a second "back" inside the same
 * screen reads as a dead end. `nested` renders the lighter variant used for
 * the entries inside "Add source" / "Shared folders".
 */
function Section({ icon: Icon, title, summary, open, onToggle, nested = false, children }) {
  return (
    <div className={nested
      ? 'bg-hifi-dark/40 border border-hifi-accent/40 rounded-lg overflow-hidden'
      : 'bg-hifi-dark/60 border border-hifi-accent/60 rounded-xl overflow-hidden'}>
      <button
        onClick={onToggle}
        className={`w-full flex items-center justify-between text-left hover:bg-hifi-light/20 transition-colors ${nested ? 'p-3' : 'p-4'}`}
      >
        <div className="flex items-center space-x-3 min-w-0">
          {Icon && (
            <div className={`rounded-lg bg-hifi-gold/20 shrink-0 ${nested ? 'p-1.5' : 'p-2'}`}>
              <Icon size={nested ? 16 : 20} className="text-hifi-gold" />
            </div>
          )}
          <div className="min-w-0">
            <div className={`text-white ${nested ? 'text-sm' : 'font-medium'}`}>{title}</div>
            {summary && <div className="text-xs text-hifi-silver/70 truncate">{summary}</div>}
          </div>
        </div>
        <ChevronRight
          size={nested ? 16 : 20}
          className={`text-hifi-silver shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
        />
      </button>
      {open && (
        <div className={`border-t border-hifi-accent/40 space-y-4 ${nested ? 'p-3' : 'px-4 pb-4 pt-4'}`}>
          {children}
        </div>
      )}
    </div>
  );
}

/**
 * Folder picker over /api/local/browse — the same widget "add a local folder",
 * "share a local folder" and "playlist folder" all need. Each instance keeps
 * its own browse position, so opening one doesn't move another.
 */
function FolderPicker({ t, startAt = '', onPick, pickLabel, busy, onError }) {
  const [path, setPath] = useState(startAt);
  const [parent, setParent] = useState(null);
  const [dirs, setDirs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newName, setNewName] = useState('');
  const newNameRef = useKeyboardInput(newName, setNewName);

  const browse = useCallback(async (next) => {
    setLoading(true);
    try {
      const d = await j('/api/local/browse?path=' + encodeURIComponent(next || ''));
      if (d.success === false) onError(d.message || t('common.error'));
      else { setDirs(d.dirs || []); setParent(d.parent); setPath(d.path || ''); }
    } catch (_) { onError(t('common.error')); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { browse(startAt); }, [browse, startAt]);

  const createHere = async () => {
    const name = newName.trim();
    if (!name || !path) return;
    setLoading(true);
    try {
      const r = await post('/api/local/mkdir', { path, name });
      if (r.success) { setNewName(''); await browse(r.path); }
      else onError(r.message || t('common.error'));
    } catch (_) { onError(t('common.error')); }
    finally { setLoading(false); }
  };

  return (
    <div className="bg-hifi-dark rounded-lg p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-hifi-silver truncate">{path || '/'}</span>
        <button onClick={() => browse(parent)} disabled={parent === null || parent === undefined} className={`shrink-0 ${smallBtn}`}>
          {t('sources.subpathUp')}
        </button>
      </div>
      {loading ? (
        <p className="text-xs text-hifi-silver/70 mt-2">{t('common.loading')}</p>
      ) : dirs.length === 0 ? (
        <p className="text-xs text-hifi-silver/70 mt-2">{t('sources.subpathNoSubfolders')}</p>
      ) : (
        <div className="space-y-1 mt-2 max-h-40 overflow-y-auto">
          {dirs.map((dir) => (
            <button
              key={dir}
              onClick={() => browse(dir)}
              className="w-full text-left text-sm text-white bg-hifi-accent/40 hover:bg-hifi-accent rounded-md px-3 py-1.5 truncate"
            >
              {dir}
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-2 mt-3">
        <input
          ref={newNameRef}
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          className={input}
          placeholder={t('sources.newFolderPlaceholder')}
        />
        <button onClick={createHere} disabled={loading || !newName.trim() || !path} className={`shrink-0 ${smallBtn}`}>
          {t('sources.newFolderCreate')}
        </button>
      </div>
      <button onClick={() => onPick(path)} disabled={busy || !path} className={`${ghostBtn} w-full mt-3`}>
        <Plus size={18} /><span>{pickLabel}</span>
      </button>
    </div>
  );
}

export default function SourcesManager() {
  const { t } = useI18n();

  // One band open at a time, mirroring the canovaccio: Active sources / Add
  // source / Playlist folder / Shared folders. The old Simple-vs-Advanced
  // toggle is gone — the split it stood for is now the sections themselves.
  const [openSection, setOpenSection] = useState(null);
  const [openAdd, setOpenAdd] = useState(null);      // 'smb' | 'internal' | 'local'
  const [openShare, setOpenShare] = useState(null);  // 'local'

  const [sources, setSources] = useState([]);
  const [usb, setUsb] = useState([]); // USB devices needing attention only — see api_usb()
  const [smbCard, setSmbCard] = useState(null);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  // Playlist folder — where Lyrion saves playlists created from the player.
  // sources_server.py provisions a working default on its own
  // (ensure_playlistdir()); this is the override, and the last thing Lyrion's
  // own setup wizard used to ask for now that the wizard is skipped.
  const [playlistdir, setPlaylistdir] = useState('');
  const [playlistdirDefault, setPlaylistdirDefault] = useState('');
  const [pldOpen, setPldOpen] = useState(false);

  const [smb, setSmb] = useState({ server: '', share: '', username: '', password: '', rw: false });
  const setSmbField = (k) => (e) => setSmb((s) => ({ ...s, [k]: e.target.value }));
  const serverRef = useKeyboardInput(smb.server, () => {});
  const shareRef = useKeyboardInput(smb.share, () => {});
  const userRef = useKeyboardInput(smb.username, () => {});
  const passRef = useKeyboardInput(smb.password, () => {});

  const loadSources = useCallback(async () => {
    try { const d = await j('/api/sources'); setSources(d.sources || []); } catch (_) {}
  }, []);
  const loadUsb = useCallback(async () => {
    try { const d = await j('/api/usb'); setUsb(d.disks || []); } catch (_) {}
  }, []);
  const loadSmbCard = useCallback(async () => {
    try { setSmbCard(await j('/api/internal/smb')); } catch (_) {}
  }, []);
  const loadPlaylistdir = useCallback(async () => {
    try {
      const d = await j('/api/playlistdir');
      if (d && d.success) { setPlaylistdir(d.path || ''); setPlaylistdirDefault(d.default || ''); }
    } catch (_) {}
  }, []);

  useEffect(() => {
    loadSources();
    loadUsb();
    loadSmbCard();
    loadPlaylistdir();
    // sources_server.py auto-adopts every healthy USB drive on its own
    // (read-write + Samba share, no tap needed) — poll both lists so a
    // freshly-inserted drive shows up here live, without navigating away
    // and back.
    const sourcesId = setInterval(loadSources, 4000);
    const usbId = setInterval(loadUsb, 4000);
    return () => { clearInterval(sourcesId); clearInterval(usbId); };
  }, [loadSources, loadUsb, loadSmbCard, loadPlaylistdir]);

  // Every edit applies itself now (sources_server.py pushes the change into
  // Lyrion's live mediadirs and rescans) — there is no Apply button to press,
  // so a successful edit just refreshes what's on screen.
  const changed = () => { loadSources(); loadSmbCard(); };

  const addLocal = async (path, samba) => {
    if (!path) return;
    setBusy(true);
    try {
      const r = await post('/api/sources/local', { path, samba });
      setMsg(r.success ? t('sources.added') : (r.message || t('common.error')));
      if (r.success) { changed(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const retryUsb = async (device) => {
    setBusy(true);
    setMsg(t('sources.internal.adopting'));
    try {
      const r = await post('/api/usb/adopt', { device });
      setMsg(r.success ? t('sources.internal.adopted') : (r.message || t('common.error')));
      if (r.success) { loadUsb(); changed(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const addSmb = async () => {
    if (!smb.server.trim() || !smb.share.trim()) return;
    setBusy(true);
    setMsg(t('sources.mounting'));
    try {
      const r = await post('/api/sources/smb', smb);
      setMsg(r.success ? t('sources.mounted') : (r.message || t('common.error')));
      if (r.success) { setSmb({ server: '', share: '', username: '', password: '', rw: false }); changed(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const removeSource = async (id) => {
    try { await j('/api/sources/' + id, { method: 'DELETE' }); changed(); } catch (_) {}
  };

  const setSmbRw = async (id, rw) => {
    setBusy(true);
    try {
      const r = await post(`/api/sources/${id}/rw`, { rw });
      setMsg(r.success ? (r.message || t('sources.mounted')) : (r.message || t('common.error')));
      if (r.success) loadSources();
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const savePlaylistdir = async (path) => {
    if (!path) return;
    setBusy(true);
    try {
      const r = await post('/api/playlistdir', { path });
      setMsg(r.success ? (r.message || t('sources.playlistdir.saved')) : (r.message || t('common.error')));
      if (r.success) { setPldOpen(false); loadPlaylistdir(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  // ── Subfolder picker (smb/internal/usb only) ──────────────────────────
  // Narrows a source to a subfolder of its mount from here, instead of
  // needing Lyrion's own setup wizard for that — mirrors the admin-webui's
  // SourcesPanel.vue against the same sources_server.py endpoints.
  const [browsingId, setBrowsingId] = useState(null);
  const [browsePath, setBrowsePath] = useState('');
  const [browseDirs, setBrowseDirs] = useState([]);
  const [browseParent, setBrowseParent] = useState(null);
  const [browseBusy, setBrowseBusy] = useState(false);

  const loadBrowse = async (id, path) => {
    setBrowseBusy(true);
    try {
      const d = await j(`/api/sources/${id}/browse?path=${encodeURIComponent(path)}`);
      if (d.success === false) {
        setMsg(d.message || t('common.error'));
        setBrowsingId(null);
      } else {
        setBrowseDirs(d.dirs || []);
        setBrowseParent(d.parent);
      }
    } catch (_) { setMsg(t('common.error')); setBrowsingId(null); }
    finally { setBrowseBusy(false); }
  };
  const openBrowse = (s) => {
    setBrowsingId(s.id);
    setBrowsePath(s.subpath || '');
    loadBrowse(s.id, s.subpath || '');
  };
  const closeBrowse = () => setBrowsingId(null);
  const browseInto = (name) => {
    const next = browsePath ? `${browsePath}/${name}` : name;
    setBrowsePath(next);
    loadBrowse(browsingId, next);
  };
  const browseUp = () => {
    if (browseParent === null || browseParent === undefined) return;
    setBrowsePath(browseParent);
    loadBrowse(browsingId, browseParent);
  };
  const useBrowsePath = async (path) => {
    setBusy(true);
    try {
      const r = await post(`/api/sources/${browsingId}/subpath`, { subpath: path });
      setMsg(r.success ? (r.message || t('sources.subpathSaved')) : (r.message || t('common.error')));
      if (r.success) { setBrowsingId(null); loadSources(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const toggle = (key) => setOpenSection((cur) => (cur === key ? null : key));
  const shares = (smbCard && smbCard.shares) || [];

  return (
    <div className="space-y-4">
      <p className="text-sm text-hifi-silver">{t('settings.sources.help')}</p>
      <p className="text-xs text-hifi-silver/60">{t('sources.autoApplyHint')}</p>

      {/* ── Active sources ───────────────────────────────────────────── */}
      <Section
        icon={Library}
        title={t('sources.active')}
        summary={sources.length ? t('sources.countSummary', { count: sources.length }) : t('sources.none')}
        open={openSection === 'active'}
        onToggle={() => toggle('active')}
      >
        <div className="space-y-2">
          {sources.length === 0 && <p className="text-sm text-hifi-silver/70">{t('sources.none')}</p>}
          {sources.map((s) => {
            const smbType = s.type === 'smb';
            const mountBased = smbType || s.type === 'internal' || s.type === 'usb';
            const sub = smbType
              ? `//${s.server}/${s.share} → ${s.mountpoint}${s.subpath ? '/' + s.subpath : ''}`
              : mountBased ? s.mountpoint + (s.subpath ? '/' + s.subpath : '') : s.path;
            const ok = mountBased ? s.mounted : s.exists;
            const tag = smbType ? (s.rw ? 'SMB · RW' : 'SMB')
              : s.type === 'internal' ? t('sources.internal.tag')
                : s.type === 'usb' ? 'USB' : t('sources.local');
            return (
              <React.Fragment key={s.id}>
                <div className="flex items-center justify-between bg-hifi-dark rounded-lg p-3">
                  <div className="min-w-0">
                    <div className="text-white text-sm truncate">
                      {s.name}
                      <span className="ml-2 text-[10px] uppercase tracking-wide text-hifi-gold/80">{tag}</span>
                    </div>
                    <div className={`text-xs truncate ${ok ? 'text-hifi-silver/70' : 'text-red-400'}`}>{sub}</div>
                    {s.usage && (
                      <div className="text-xs text-hifi-silver/50">
                        {t('sources.freeOf', { free: fmtBytes(s.usage.free), total: fmtBytes(s.usage.total) })}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 ml-3 shrink-0">
                    {smbType && (
                      <button
                        onClick={() => setSmbRw(s.id, !s.rw)}
                        disabled={busy}
                        className={`text-xs py-1.5 px-3 rounded-md ${s.rw ? 'bg-hifi-gold/20 hover:bg-hifi-gold/30 text-hifi-gold' : 'bg-hifi-accent hover:bg-hifi-light text-white'}`}
                      >
                        {s.rw ? t('sources.smbMakeRo') : t('sources.smbMakeRw')}
                      </button>
                    )}
                    {mountBased && (
                      <button
                        onClick={() => (browsingId === s.id ? closeBrowse() : openBrowse(s))}
                        disabled={busy || !s.mounted}
                        className={smallBtn}
                      >
                        {t('sources.subpathPick')}
                      </button>
                    )}
                    <button onClick={() => removeSource(s.id)} className="p-2 rounded-lg bg-red-900/30 hover:bg-red-900/60 text-red-300">
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
                {browsingId === s.id && (
                  <div className="bg-hifi-dark/60 border border-hifi-accent rounded-lg p-3 -mt-1">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-xs text-hifi-silver truncate">/{browsePath || ''}</span>
                      <button onClick={closeBrowse} className="text-xs text-hifi-silver hover:text-white shrink-0">{t('common.back')}</button>
                    </div>
                    {browseBusy ? (
                      <p className="text-xs text-hifi-silver/70">{t('common.loading')}</p>
                    ) : (
                      <>
                        <div className="flex gap-2 mb-2">
                          <button onClick={browseUp} disabled={browseParent === null || browseParent === undefined} className={smallBtn}>
                            {t('sources.subpathUp')}
                          </button>
                          <button onClick={() => useBrowsePath(browsePath)} disabled={busy} className="text-xs py-1.5 px-3 rounded-md bg-hifi-gold/20 hover:bg-hifi-gold/30 text-hifi-gold">
                            {t('sources.subpathUseHere')}
                          </button>
                          <button onClick={() => useBrowsePath('')} disabled={busy || !browsePath} className={smallBtn}>
                            {t('sources.subpathUseRoot')}
                          </button>
                        </div>
                        {browseDirs.length === 0 ? (
                          <p className="text-xs text-hifi-silver/70">{t('sources.subpathNoSubfolders')}</p>
                        ) : (
                          <div className="space-y-1 max-h-48 overflow-y-auto">
                            {browseDirs.map((name) => (
                              <button
                                key={name}
                                onClick={() => browseInto(name)}
                                className="w-full text-left text-sm text-white bg-hifi-accent/40 hover:bg-hifi-accent rounded-md px-3 py-1.5 truncate"
                              >
                                {name}
                              </button>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>

        {/* USB devices needing attention (no filesystem, or auto-mount failed) —
            healthy drives are adopted automatically and show up above instead. */}
        {usb.length > 0 && (
          <div className="pt-2 border-t border-hifi-accent/40">
            <h3 className="text-white font-semibold mb-3 flex items-center space-x-2">
              <AlertTriangle size={18} className="text-hifi-gold" /><span>{t('sources.usbAttention')}</span>
            </h3>
            <div className="space-y-2">
              {usb.map((dk) => (
                <div key={dk.path} className="bg-hifi-dark rounded-lg p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-white text-sm truncate">
                        {dk.label || 'USB'}
                        <span className="ml-2 text-[10px] uppercase tracking-wide text-hifi-gold/80">USB{dk.fstype ? ` ${dk.fstype}` : ''}{dk.size ? ` · ${dk.size}` : ''}</span>
                      </div>
                      <div className="text-xs text-red-400 truncate">
                        {dk.needs_format ? t('sources.usbNeedsFormat') : `${t('sources.usbMountError')}: ${dk.error || ''}`}
                      </div>
                    </div>
                    {!dk.needs_format && (
                      <button onClick={() => retryUsb(dk.path)} disabled={busy || !dk.path} className="shrink-0 text-xs bg-hifi-gold/20 hover:bg-hifi-gold/30 text-hifi-gold py-1.5 px-3 rounded-md">
                        {t('sources.usbRetry')}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* ── Add source ───────────────────────────────────────────────── */}
      <Section
        icon={Plus}
        title={t('sources.addSource')}
        summary={t('sources.addSourceHint')}
        open={openSection === 'add'}
        onToggle={() => toggle('add')}
      >
        <Section
          nested
          icon={Network}
          title={t('sources.addSmb')}
          open={openAdd === 'smb'}
          onToggle={() => setOpenAdd((c) => (c === 'smb' ? null : 'smb'))}
        >
          <div className="grid grid-cols-2 gap-3">
            <input ref={serverRef} type="text" value={smb.server} onChange={setSmbField('server')} className={input} placeholder={t('sources.server')} />
            <input ref={shareRef} type="text" value={smb.share} onChange={setSmbField('share')} className={input} placeholder={t('sources.share')} />
            <input ref={userRef} type="text" value={smb.username} onChange={setSmbField('username')} className={input} placeholder={t('sources.user')} />
            <input ref={passRef} type="password" value={smb.password} onChange={setSmbField('password')} className={input} placeholder={t('sources.pass')} />
          </div>
          <label className="flex items-center gap-2 text-sm text-hifi-silver">
            <input type="checkbox" checked={smb.rw} onChange={(e) => setSmb((s) => ({ ...s, rw: e.target.checked }))} className="accent-hifi-gold" />
            <span>{t('sources.smbRw')}</span>
          </label>
          <button onClick={addSmb} disabled={busy} className={`${ghostBtn} w-full`}>
            {busy ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
            <span>{t('sources.mountAndAdd')}</span>
          </button>
        </Section>

        <Section
          nested
          icon={HardDrive}
          title={t('sources.internal.title')}
          open={openAdd === 'internal'}
          onToggle={() => setOpenAdd((c) => (c === 'internal' ? null : 'internal'))}
        >
          {/* Adopted disks are already listed under "Active sources", so this
              only offers the ones not in use yet. */}
          <InternalDisks onSourcesChanged={changed} showShares={false} adoptedReadOnly />
        </Section>

        <Section
          nested
          icon={FolderPlus}
          title={t('sources.addLocal')}
          open={openAdd === 'local'}
          onToggle={() => setOpenAdd((c) => (c === 'local' ? null : 'local'))}
        >
          <FolderPicker
            t={t}
            busy={busy}
            onError={setMsg}
            pickLabel={t('sources.useThisFolder')}
            onPick={(p) => addLocal(p, false)}
          />
        </Section>
      </Section>

      {/* ── Playlist folder ──────────────────────────────────────────── */}
      <Section
        icon={ListMusic}
        title={t('sources.playlistdir.title')}
        summary={playlistdir || t('sources.playlistdir.unset')}
        open={openSection === 'playlist'}
        onToggle={() => toggle('playlist')}
      >
        <p className="text-sm text-hifi-silver">{t('sources.playlistdir.hint')}</p>
        <div className="flex items-center justify-between gap-3 bg-hifi-dark rounded-lg p-3">
          <div className="text-xs text-hifi-silver/80 break-all min-w-0">
            {playlistdir || t('sources.playlistdir.unset')}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={() => setPldOpen((v) => !v)} className={smallBtn}>
              {pldOpen ? t('common.close') : t('sources.playlistdir.pick')}
            </button>
            <button
              onClick={() => savePlaylistdir(playlistdirDefault)}
              disabled={busy || !playlistdirDefault || playlistdir === playlistdirDefault}
              className={smallBtn}
            >
              {t('sources.playlistdir.default')}
            </button>
          </div>
        </div>
        {pldOpen && (
          // Start from the folder in use, so a sibling folder is one tap away
          // rather than a walk down from /.
          <FolderPicker
            t={t}
            busy={busy}
            onError={setMsg}
            startAt={playlistdir || ''}
            pickLabel={t('sources.playlistdir.use')}
            onPick={savePlaylistdir}
          />
        )}
      </Section>

      {/* ── Shared folders (what this appliance publishes on the network) ─ */}
      <Section
        icon={Share2}
        title={t('sources.shareTitle')}
        summary={shares.length ? t('sources.shareCount', { count: shares.length }) : t('sources.shareNone')}
        open={openSection === 'share'}
        onToggle={() => toggle('share')}
      >
        <p className="text-sm text-hifi-silver">{t('sources.shareHint')}</p>
        {smbCard && shares.length > 0 && <SmbCard smb={smbCard} t={t} onRegenerated={loadSmbCard} />}
        {shares.length === 0 && <p className="text-sm text-hifi-silver/70">{t('sources.shareNone')}</p>}

        <Section
          nested
          icon={FolderPlus}
          title={t('sources.shareLocal')}
          open={openShare === 'local'}
          onToggle={() => setOpenShare((c) => (c === 'local' ? null : 'local'))}
        >
          <p className="text-sm text-hifi-silver">{t('sources.localSambaHint')}</p>
          <FolderPicker
            t={t}
            busy={busy}
            onError={setMsg}
            pickLabel={t('sources.shareThisFolder')}
            onPick={(p) => addLocal(p, true)}
          />
        </Section>
      </Section>

      {msg && (
        <div className={`rounded-lg p-3 text-center text-sm ${isErr(msg) ? 'bg-red-900/20 text-red-300 border border-red-500/30' : 'bg-hifi-dark text-hifi-silver'}`}>{msg}</div>
      )}
    </div>
  );
}
