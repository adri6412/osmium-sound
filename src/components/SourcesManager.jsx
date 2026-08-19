import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { FolderPlus, Network, Trash2, Loader2, Plus, AlertTriangle } from 'lucide-react';
import { useI18n } from '../i18n';
import { useKeyboardInput } from '../hooks/useKeyboardInput';
import InternalDisks from './InternalDisks';

// The on-device sources manager (mount/list SMB + USB + local folders) runs as a
// small HTTP service on the appliance itself. Talk to it natively so the UI
// matches the rest of Settings (no embedded web page).
const SRC = 'http://localhost:8080';

const isErr = (m) => /error|errore|fallit|fail|non valido|invalid/i.test(m || '');

export default function SourcesManager() {
  const { t } = useI18n();

  // "Semplice" (default) shows only what the average user needs: active
  // sources + USB devices needing attention (rare) + Apply. "Avanzate" adds
  // internal-disk adoption/formatting and manual local/SMB folder entry —
  // same pill-toggle pattern as the DSP EQ graphic/advanced view in
  // Settings.jsx.
  const [view, setView] = useState('simple');

  const [sources, setSources] = useState([]);
  const [usb, setUsb] = useState([]); // USB devices needing attention only — see api_usb()
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);

  // Add local folder — file-browser picker (mirrors Lyrion's own folder
  // picker) instead of a free-text path box.
  const [addLocalOpen, setAddLocalOpen] = useState(false); // collapsed by default; expand on demand
  const [addLocalPath, setAddLocalPath] = useState('');   // '' = top-level roots list
  const [addLocalParent, setAddLocalParent] = useState(null);
  const [addLocalDirs, setAddLocalDirs] = useState([]);
  const [addLocalBusy, setAddLocalBusy] = useState(false);
  const [addLocalSamba, setAddLocalSamba] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const newFolderRef = useKeyboardInput(newFolderName, setNewFolderName);

  const [smb, setSmb] = useState({ server: '', share: '', username: '', password: '', rw: false });
  const setSmbField = (k) => (e) => setSmb((s) => ({ ...s, [k]: e.target.value }));
  const serverRef = useKeyboardInput(smb.server, () => {});
  const shareRef = useKeyboardInput(smb.share, () => {});
  const userRef = useKeyboardInput(smb.username, () => {});
  const passRef = useKeyboardInput(smb.password, () => {});

  const j = async (url, opts) => {
    const r = await fetch(SRC + url, opts);
    return r.json();
  };
  const post = (url, body) =>
    j(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  const loadSources = useCallback(async () => {
    try { const d = await j('/api/sources'); setSources(d.sources || []); } catch (_) {}
  }, []);
  const loadUsb = useCallback(async () => {
    try { const d = await j('/api/usb'); setUsb(d.disks || []); } catch (_) {}
  }, []);

  const loadAddLocalBrowse = useCallback(async (path = addLocalPath) => {
    setAddLocalBusy(true);
    try {
      const d = await j('/api/local/browse?path=' + encodeURIComponent(path));
      if (d.success === false) {
        setMsg(d.message || t('common.error'));
      } else {
        setAddLocalDirs(d.dirs || []);
        setAddLocalParent(d.parent);
        setAddLocalPath(d.path || '');
      }
    } catch (_) { setMsg(t('common.error')); }
    finally { setAddLocalBusy(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadSources();
    loadUsb();
    // sources_server.py auto-adopts every healthy USB drive on its own
    // (read-write + Samba share, no tap needed) — poll both lists so a
    // freshly-inserted drive shows up here live, without navigating away
    // and back.
    const sourcesId = setInterval(loadSources, 4000);
    const usbId = setInterval(loadUsb, 4000);
    return () => { clearInterval(sourcesId); clearInterval(usbId); };
  }, [loadSources, loadUsb]);

  const toggleAddLocal = () => {
    setAddLocalOpen((open) => {
      const next = !open;
      if (next && addLocalDirs.length === 0) loadAddLocalBrowse('');
      return next;
    });
  };
  const addLocalUp = () => {
    if (addLocalParent === null || addLocalParent === undefined) return;
    loadAddLocalBrowse(addLocalParent);
  };
  const createFolderHere = async () => {
    const name = newFolderName.trim();
    if (!name || !addLocalPath) return;
    setAddLocalBusy(true);
    try {
      const r = await post('/api/local/mkdir', { path: addLocalPath, name });
      if (r.success) { setNewFolderName(''); await loadAddLocalBrowse(r.path); }
      else setMsg(r.message || t('common.error'));
    } catch (_) { setMsg(t('common.error')); }
    finally { setAddLocalBusy(false); }
  };
  const addLocal = async () => {
    if (!addLocalPath) return;
    setBusy(true);
    try {
      const r = await post('/api/sources/local', { path: addLocalPath, samba: addLocalSamba });
      setMsg(r.success ? t('sources.added') : (r.message || t('common.error')));
      if (r.success) { setAddLocalSamba(false); loadAddLocalBrowse(addLocalPath); loadSources(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const retryUsb = async (device) => {
    setBusy(true);
    setMsg(t('sources.internal.adopting'));
    try {
      const r = await post('/api/usb/adopt', { device });
      setMsg(r.success ? t('sources.internal.adopted') : (r.message || t('common.error')));
      if (r.success) { loadUsb(); loadSources(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const addSmb = async () => {
    if (!smb.server.trim() || !smb.share.trim()) return;
    setBusy(true);
    setMsg(t('sources.mounting'));
    try {
      const r = await post('/api/sources/smb', smb);
      setMsg(r.success ? t('sources.mounted') : (r.message || t('common.error')));
      if (r.success) { setSmb({ server: '', share: '', username: '', password: '', rw: false }); loadSources(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const removeSource = async (id) => {
    try { await j('/api/sources/' + id, { method: 'DELETE' }); loadSources(); } catch (_) {}
  };

  const setSmbRw = async (id, rw) => {
    setBusy(true);
    try {
      const r = await post(`/api/sources/${id}/rw`, { rw });
      setMsg(r.success ? (r.message || t('sources.mounted')) : (r.message || t('common.error')));
      if (r.success) loadSources();
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

  const apply = async () => {
    setApplying(true);
    setMsg(t('sources.applying'));
    try {
      const r = await post('/api/apply', {});
      setMsg(r.message || (r.success ? t('sources.applied') : t('common.error')));
    } catch (_) { setMsg(t('common.error')); } finally { setApplying(false); }
  };

  const input = 'w-full bg-hifi-dark border border-hifi-accent rounded-lg px-4 py-3 text-white focus:outline-none focus:border-hifi-gold';
  const ghostBtn = 'bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white py-3 px-4 rounded-lg font-medium flex items-center justify-center space-x-2 transition-colors';

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm text-hifi-silver">{t('settings.sources.help')}</p>
        <div className="flex bg-hifi-dark rounded-full p-0.5 shrink-0">
          {['simple', 'advanced'].map((v) => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`text-xs px-3 py-1 rounded-full transition-colors ${
                view === v ? 'bg-hifi-gold text-black' : 'text-hifi-silver hover:text-white'
              }`}
            >
              {t(v === 'simple' ? 'sources.viewSimple' : 'sources.viewAdvanced')}
            </button>
          ))}
        </div>
      </div>

      {/* Active sources */}
      <div>
        <h3 className="text-white font-semibold mb-3">{t('sources.active')}</h3>
        <div className="space-y-2">
          {sources.length === 0 && (
            <p className="text-sm text-hifi-silver/70">{t('sources.none')}</p>
          )}
          {sources.map((s) => {
            const smbType = s.type === 'smb';
            const internalType = s.type === 'internal';
            const usbType = s.type === 'usb';
            const mountBased = smbType || internalType || usbType;
            const sub = smbType ? `//${s.server}/${s.share} → ${s.mountpoint}${s.subpath ? '/' + s.subpath : ''}` : mountBased ? s.mountpoint + (s.subpath ? '/' + s.subpath : '') : s.path;
            const ok = mountBased ? s.mounted : s.exists;
            const tag = smbType ? (s.rw ? 'SMB · RW' : 'SMB') : internalType ? t('sources.internal.tag') : usbType ? 'USB' : t('sources.local');
            return (
              <React.Fragment key={s.id}>
              <div className="flex items-center justify-between bg-hifi-dark rounded-lg p-3">
                <div className="min-w-0">
                  <div className="text-white text-sm truncate">
                    {s.name}
                    <span className="ml-2 text-[10px] uppercase tracking-wide text-hifi-gold/80">{tag}</span>
                  </div>
                  <div className={`text-xs truncate ${ok ? 'text-hifi-silver/70' : 'text-red-400'}`}>{sub}</div>
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
                      className="text-xs py-1.5 px-3 rounded-md bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white"
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
                        <button onClick={browseUp} disabled={browseParent === null || browseParent === undefined} className="text-xs py-1.5 px-3 rounded-md bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white">
                          {t('sources.subpathUp')}
                        </button>
                        <button onClick={() => useBrowsePath(browsePath)} disabled={busy} className="text-xs py-1.5 px-3 rounded-md bg-hifi-gold/20 hover:bg-hifi-gold/30 text-hifi-gold">
                          {t('sources.subpathUseHere')}
                        </button>
                        <button onClick={() => useBrowsePath('')} disabled={busy || !browsePath} className="text-xs py-1.5 px-3 rounded-md bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white">
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
      </div>

      {/* USB devices needing attention (no filesystem, or auto-mount failed) —
          healthy drives are adopted automatically and show up above instead. */}
      {usb.length > 0 && (
        <div>
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

      {view === 'advanced' && (
        <>
          {/* Internal disks (adopt existing / format) */}
          <InternalDisks onSourcesChanged={loadSources} />

          {/* Add local folder — file-browser picker (mirrors Lyrion's own
              folder picker) instead of a free-text path box. */}
          <div>
            <h3 className="text-white font-semibold mb-3 flex items-center space-x-2"><FolderPlus size={18} className="text-hifi-gold" /><span>{t('sources.addLocal')}</span></h3>
            <button onClick={toggleAddLocal} className={`${ghostBtn} w-full`}>
              <span>{addLocalOpen ? t('common.close') : t('sources.addLocal')}</span>
            </button>
            {addLocalOpen && (
            <div className="bg-hifi-dark rounded-lg p-3 mt-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-hifi-silver truncate">{addLocalPath || '/'}</span>
                <button
                  onClick={addLocalUp}
                  disabled={addLocalParent === null || addLocalParent === undefined}
                  className="shrink-0 text-xs py-1.5 px-3 rounded-md bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white"
                >
                  {t('sources.subpathUp')}
                </button>
              </div>
              {addLocalBusy ? (
                <p className="text-xs text-hifi-silver/70 mt-2">{t('common.loading')}</p>
              ) : addLocalDirs.length === 0 ? (
                <p className="text-xs text-hifi-silver/70 mt-2">{t('sources.subpathNoSubfolders')}</p>
              ) : (
                <div className="space-y-1 mt-2 max-h-40 overflow-y-auto">
                  {addLocalDirs.map((dir) => (
                    <button
                      key={dir}
                      onClick={() => loadAddLocalBrowse(dir)}
                      className="w-full text-left text-sm text-white bg-hifi-accent/40 hover:bg-hifi-accent rounded-md px-3 py-1.5 truncate"
                    >
                      {dir}
                    </button>
                  ))}
                </div>
              )}
              <div className="flex gap-2 mt-3">
                <input ref={newFolderRef} type="text" value={newFolderName} onChange={(e) => setNewFolderName(e.target.value)} className={input} placeholder={t('sources.newFolderPlaceholder')} />
                <button onClick={createFolderHere} disabled={addLocalBusy || !newFolderName.trim() || !addLocalPath} className="shrink-0 text-xs py-1.5 px-3 rounded-md bg-hifi-accent hover:bg-hifi-light disabled:opacity-50 text-white">
                  {t('sources.newFolderCreate')}
                </button>
              </div>
              <label className="flex items-center gap-2 mt-3 text-sm text-hifi-silver">
                <input type="checkbox" checked={addLocalSamba} onChange={(e) => setAddLocalSamba(e.target.checked)} className="accent-hifi-gold" />
                <span>{t('sources.localSambaHint')}</span>
              </label>
              <button onClick={addLocal} disabled={busy || !addLocalPath} className={`${ghostBtn} w-full mt-3`}><Plus size={18} /><span>{t('sources.useThisFolder')}</span></button>
            </div>
            )}
          </div>

          {/* Add network folder (SMB) */}
          <div>
            <h3 className="text-white font-semibold mb-3 flex items-center space-x-2"><Network size={18} className="text-hifi-gold" /><span>{t('sources.addSmb')}</span></h3>
            <div className="grid grid-cols-2 gap-3">
              <input ref={serverRef} type="text" value={smb.server} onChange={setSmbField('server')} className={input} placeholder={t('sources.server')} />
              <input ref={shareRef} type="text" value={smb.share} onChange={setSmbField('share')} className={input} placeholder={t('sources.share')} />
              <input ref={userRef} type="text" value={smb.username} onChange={setSmbField('username')} className={input} placeholder={t('sources.user')} />
              <input ref={passRef} type="password" value={smb.password} onChange={setSmbField('password')} className={input} placeholder={t('sources.pass')} />
            </div>
            <label className="flex items-center gap-2 mt-3 text-sm text-hifi-silver">
              <input type="checkbox" checked={smb.rw} onChange={(e) => setSmb((s) => ({ ...s, rw: e.target.checked }))} className="accent-hifi-gold" />
              <span>{t('sources.smbRw')}</span>
            </label>
            <button onClick={addSmb} disabled={busy} className={`${ghostBtn} w-full mt-3`}><Plus size={18} /><span>{t('sources.mountAndAdd')}</span></button>
          </div>
        </>
      )}

      {msg && (
        <div className={`rounded-lg p-3 text-center text-sm ${isErr(msg) ? 'bg-red-900/20 text-red-300 border border-red-500/30' : 'bg-hifi-dark text-hifi-silver'}`}>{msg}</div>
      )}

      {/* Apply + rescan */}
      <motion.button onClick={apply} disabled={applying} className="w-full bg-hifi-gold hover:bg-yellow-600 disabled:bg-hifi-accent text-black py-4 rounded-lg font-semibold flex items-center justify-center space-x-2" whileTap={{ scale: applying ? 1 : 0.97 }}>
        {applying ? <Loader2 size={18} className="animate-spin" /> : null}
        <span>{t('sources.apply')}</span>
      </motion.button>
    </div>
  );
}
