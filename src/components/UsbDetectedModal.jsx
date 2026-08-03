import React from 'react';
import { createPortal } from 'react-dom';
import { motion } from 'framer-motion';
import { Usb } from 'lucide-react';
import { useI18n } from '../i18n';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

// Global "a USB drive was just plugged in" prompt — fired from App.jsx
// regardless of which screen is currently showing (see the usb-watcher
// effect there). Styled to match Settings.jsx's changelog/confirm dialogs.
export default function UsbDetectedModal({ disk, onMount, onCancel }) {
  const { t } = useI18n();
  if (!disk) return null;

  return createPortal(
    <motion.div
      className="absolute inset-0 z-[10050] flex items-center justify-center bg-black/80 backdrop-blur-sm p-6"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      onClick={onCancel}
    >
      <motion.div
        className="bg-hifi-light border border-hifi-accent rounded-2xl p-6 max-w-md w-full shadow-2xl"
        initial={{ scale: 0.92, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-3 text-hifi-gold">
          <Usb size={22} />
          <h3 className="text-white text-lg font-semibold">{t('usbPrompt.title')}</h3>
        </div>
        <p className="text-hifi-silver text-sm leading-relaxed mb-6">
          {t('usbPrompt.body', { label: disk.label || 'USB' })}
        </p>
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 bg-hifi-accent hover:bg-hifi-dark text-white py-3 rounded-lg font-medium transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={onMount}
            className="flex-1 bg-hifi-gold hover:bg-yellow-600 text-black py-3 rounded-lg font-semibold transition-colors"
          >
            {t('usbPrompt.mount')}
          </button>
        </div>
      </motion.div>
    </motion.div>,
    document.getElementById(SCALED_CANVAS_ID) || document.body
  );
}
