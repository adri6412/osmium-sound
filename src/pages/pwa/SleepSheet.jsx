import React from 'react';
import { useI18n } from '../../i18n';
import BottomSheet from './BottomSheet';

const MINUTES = [15, 30, 45, 60, 90, 120];

const SleepSheet = ({ player, open, onClose }) => {
  const { t } = useI18n();
  const { willSleepIn, setSleepTimer } = player;

  const pick = (m) => { setSleepTimer(m); onClose(); };

  return (
    <BottomSheet open={open} onClose={onClose} title={t('player.sleep')}>
      <div className="p-4 space-y-3">
        {willSleepIn > 0 && (
          <p className="text-xs text-hifi-gold">{t('player.sleepActive', { min: Math.ceil(willSleepIn / 60) })}</p>
        )}
        <div className="grid grid-cols-3 gap-2">
          {MINUTES.map((m) => (
            <button key={m} onClick={() => pick(m)}
              className="py-2.5 rounded-flat border border-hifi-accent text-white text-sm">
              {m}m
            </button>
          ))}
        </div>
        <button onClick={() => pick(0)}
          className="w-full py-2.5 rounded-flat border border-red-500/40 text-red-400 text-sm">
          {t('player.sleepOff')}
        </button>
      </div>
    </BottomSheet>
  );
};

export default SleepSheet;
