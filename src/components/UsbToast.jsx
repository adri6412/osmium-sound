import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Usb } from 'lucide-react';
import { useI18n } from '../i18n';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

const AUTO_DISMISS_MS = 4500;

// Small, non-blocking "USB drive mounted" notice — fired from App.jsx's
// usb-watcher effect when a new `usb`-type source appears (sources_server.py
// auto-adopts every USB drive read-write + Samba-shared the moment it's
// plugged in, see usb_sync(); nothing left to confirm). Purely informational
// and auto-dismissing, unlike the old UsbDetectedModal it replaces, which
// blocked the screen asking whether to mount.
export default function UsbToast({ disk, onDismiss }) {
  const { t } = useI18n();

  useEffect(() => {
    if (!disk) return undefined;
    const id = setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => clearTimeout(id);
  }, [disk, onDismiss]);

  return createPortal(
    <AnimatePresence>
      {disk && (
        <motion.div
          className="absolute bottom-6 right-6 z-[10050] max-w-xs cursor-pointer"
          initial={{ opacity: 0, y: 12, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.95 }}
          onClick={onDismiss}
        >
          <div className="flex items-center gap-3 bg-hifi-light border border-hifi-accent rounded-xl px-4 py-3 shadow-2xl">
            <Usb size={18} className="text-hifi-gold shrink-0" />
            <p className="text-white text-sm">{t('usbToast.mounted', { label: disk.label || 'USB' })}</p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.getElementById(SCALED_CANVAS_ID) || document.body
  );
}
