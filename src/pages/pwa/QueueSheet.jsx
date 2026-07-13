import React, { useState } from 'react';
import { Trash2, Save } from 'lucide-react';
import { useI18n } from '../../i18n';
import BottomSheet from './BottomSheet';

const QueueSheet = ({ player, open, onClose }) => {
  const { t } = useI18n();
  const { queue, queueIndex, queueJump, queueRemove, queueClear, saveQueue } = player;
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [msg, setMsg] = useState('');

  const handleSave = async () => {
    const result = await saveQueue(name);
    if (!result.success) { setMsg(result.error || ''); return; }
    setSaving(false);
    setName('');
    onClose();
  };

  return (
    <BottomSheet open={open} onClose={onClose} title={`${t('player.queue')} (${queue.length})`}>
      {queue.length === 0 ? (
        <p className="text-sm text-hifi-silver/50 text-center py-8">{t('player.queueEmpty')}</p>
      ) : (
        <ul>
          {queue.map((item, idx) => (
            <li key={`${item.id || item.url || idx}-${idx}`}
              className={`pwa-row pwa-divider ${idx === queueIndex ? 'bg-hifi-gold/10' : ''}`}>
              <button onClick={() => queueJump(idx)} className="flex-1 min-w-0 text-left">
                <p className={`text-[14px] truncate ${idx === queueIndex ? 'text-hifi-gold' : 'text-white'}`}>{item.title || item.track || '—'}</p>
                <p className="text-[12px] text-hifi-silver/50 truncate">{item.artist || t('player.unknownArtist')}</p>
              </button>
              <button onClick={() => queueRemove(idx)} className="p-2 text-hifi-silver/50 shrink-0"><Trash2 size={15} /></button>
            </li>
          ))}
        </ul>
      )}

      <div className="p-4 space-y-2">
        {!saving ? (
          <div className="flex gap-2">
            <button onClick={() => setSaving(true)} disabled={queue.length === 0}
              className="pwa-btn-outlined flex items-center justify-center gap-2 flex-1">
              <Save size={15} /> {t('player.saveAsPlaylist')}
            </button>
            <button onClick={queueClear} disabled={queue.length === 0}
              className="w-auto px-4 py-3 rounded-flat border border-red-500/40 text-red-400 text-sm flex items-center gap-2">
              <Trash2 size={15} />
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <input value={name} onChange={(e) => { setName(e.target.value); setMsg(''); }}
              placeholder={t('player.playlistNamePlaceholder')} className="pwa-input" autoFocus />
            {msg && <p className="text-xs text-red-400">{msg}</p>}
            <div className="flex gap-2">
              <button onClick={() => setSaving(false)} className="pwa-btn-outlined flex-1">{t('common.cancel')}</button>
              <button onClick={handleSave} disabled={!name.trim()} className="pwa-btn-filled flex-1">{t('common.confirm')}</button>
            </div>
          </div>
        )}
      </div>
    </BottomSheet>
  );
};

export default QueueSheet;
