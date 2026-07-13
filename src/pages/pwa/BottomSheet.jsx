import React from 'react';
import { createPortal } from 'react-dom';

// Modal bottom sheet — the one place Android's flat design uses rounded
// corners (8dp top corners on bottom sheets, see the "Riferimento visivo
// Android" section of the plan / SqueezerWidget.LargeComponent shape).
// Shared by QueueSheet and the sleep-timer picker in NowPlayingScreen.
const BottomSheet = ({ open, onClose, title, children }) => {
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-[80] flex flex-col justify-end">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative bg-hifi-gray rounded-t-sheet max-h-[75vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between h-11 px-4 shrink-0 pwa-divider">
          <span className="text-sm font-semibold text-white">{title}</span>
          <button onClick={onClose} className="text-hifi-silver/60 text-xs">✕</button>
        </div>
        <div className="overflow-y-auto">{children}</div>
      </div>
    </div>,
    document.body
  );
};

export default BottomSheet;
