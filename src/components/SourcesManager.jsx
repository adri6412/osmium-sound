import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Usb, FolderPlus, Network, Trash2, Loader2, Plus, FolderOpen } from 'lucide-react';
import { useI18n } from '../i18n';
import { useKeyboardInput } from '../hooks/useKeyboardInput';

// The on-device sources manager (mount/list SMB + USB + local folders) runs as a
// small HTTP service on the appliance itself. Talk to it natively so the UI
// matches the rest of Settings (no embedded web page).
const SRC = 'http://localhost:8080';

const isErr = (m) => /error|errore|fallit|fail|non valido|invalid/i.test(m || '');

export default function SourcesManager() {
  const { t } = useI18n();

  const [sources, setSources] = useState([]);
  const [usb, setUsb] = useState([]);
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [applying, setApplying] = useState(false);

  const [localPath, setLocalPath] = useState('');
  const localRef = useKeyboardInput(localPath, setLocalPath);

  const [smb, setSmb] = useState({ server: '', share: '', username: '', password: '' });
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

  useEffect(() => {
    loadSources();
    loadUsb();
    const id = setInterval(loadUsb, 4000); // pick up freshly-inserted drives
    return () => clearInterval(id);
  }, [loadSources, loadUsb]);

  const addLocal = async () => {
    const path = localPath.trim();
    if (!path) return;
    setBusy(true);
    try {
      const r = await post('/api/sources/local', { path });
      setMsg(r.success ? t('sources.added') : (r.message || t('common.error')));
      if (r.success) { setLocalPath(''); loadSources(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const addUsbPath = async (path) => {
    setBusy(true);
    try {
      const r = await post('/api/sources/local', { path });
      setMsg(r.success ? t('sources.added') : (r.message || t('common.error')));
      if (r.success) loadSources();
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const addSmb = async () => {
    if (!smb.server.trim() || !smb.share.trim()) return;
    setBusy(true);
    setMsg(t('sources.mounting'));
    try {
      const r = await post('/api/sources/smb', smb);
      setMsg(r.success ? t('sources.mounted') : (r.message || t('common.error')));
      if (r.success) { setSmb({ server: '', share: '', username: '', password: '' }); loadSources(); }
    } catch (_) { setMsg(t('common.error')); } finally { setBusy(false); }
  };

  const removeSource = async (id) => {
    try { await j('/api/sources/' + id, { method: 'DELETE' }); loadSources(); } catch (_) {}
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
      <p className="text-sm text-hifi-silver">{t('settings.sources.help')}</p>

      {/* Active sources */}
      <div>
        <h3 className="text-white font-semibold mb-3">{t('sources.active')}</h3>
        <div className="space-y-2">
          {sources.length === 0 && (
            <p className="text-sm text-hifi-silver/70">{t('sources.none')}</p>
          )}
          {sources.map((s) => {
            const smbType = s.type === 'smb';
            const sub = smbType ? `//${s.server}/${s.share} → ${s.mountpoint}` : s.path;
            const ok = smbType ? s.mounted : s.exists;
            return (
              <div key={s.id} className="flex items-center justify-between bg-hifi-dark rounded-lg p-3">
                <div className="min-w-0">
                  <div className="text-white text-sm truncate">
                    {s.name}
                    <span className="ml-2 text-[10px] uppercase tracking-wide text-hifi-gold/80">{smbType ? 'SMB' : t('sources.local')}</span>
                  </div>
                  <div className={`text-xs truncate ${ok ? 'text-hifi-silver/70' : 'text-red-400'}`}>{sub}</div>
                </div>
                <button onClick={() => removeSource(s.id)} className="ml-3 shrink-0 p-2 rounded-lg bg-red-900/30 hover:bg-red-900/60 text-red-300">
                  <Trash2 size={16} />
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* USB disks */}
      <div>
        <h3 className="text-white font-semibold mb-3 flex items-center space-x-2"><Usb size={18} className="text-hifi-gold" /><span>{t('sources.usbTitle')}</span></h3>
        <div className="space-y-3">
          {usb.length === 0 && (
            <p className="text-sm text-hifi-silver/70">{t('sources.usbNone')}</p>
          )}
          {usb.map((dk) => (
            <div key={dk.mountpoint} className="bg-hifi-dark rounded-lg p-3">
              <div className="flex items-center justify-between">
                <div className="text-white text-sm">
                  {dk.label || 'USB'}
                  <span className="ml-2 text-[10px] uppercase tracking-wide text-hifi-gold/80">USB{dk.fstype ? ` ${dk.fstype}` : ''}{dk.size ? ` · ${dk.size}` : ''}</span>
                </div>
                <button onClick={() => addUsbPath(dk.mountpoint)} disabled={busy} className="text-xs bg-hifi-accent hover:bg-hifi-light text-white py-1.5 px-3 rounded-md">
                  {t('sources.addWhole')}
                </button>
              </div>
              {(dk.folders || []).length > 0 && (
                <div className="mt-2 space-y-1">
                  {dk.folders.map((f) => (
                    <div key={f.path} className="flex items-center justify-between pl-2">
                      <div className="flex items-center space-x-2 min-w-0 text-hifi-silver text-sm">
                        <FolderOpen size={14} className="shrink-0 text-hifi-gold/70" />
                        <span className="truncate">{f.name}</span>
                      </div>
                      <button onClick={() => addUsbPath(f.path)} disabled={busy} className="ml-3 shrink-0 text-xs bg-hifi-gold/20 hover:bg-hifi-gold/30 text-hifi-gold py-1 px-3 rounded-md">
                        {t('sources.add')}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Add local folder */}
      <div>
        <h3 className="text-white font-semibold mb-3 flex items-center space-x-2"><FolderPlus size={18} className="text-hifi-gold" /><span>{t('sources.addLocal')}</span></h3>
        <input ref={localRef} type="text" value={localPath} onChange={(e) => setLocalPath(e.target.value)} className={input} placeholder="/media/musica" />
        <button onClick={addLocal} disabled={busy} className={`${ghostBtn} w-full mt-3`}><Plus size={18} /><span>{t('sources.addLocal')}</span></button>
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
        <button onClick={addSmb} disabled={busy} className={`${ghostBtn} w-full mt-3`}><Plus size={18} /><span>{t('sources.mountAndAdd')}</span></button>
      </div>

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
