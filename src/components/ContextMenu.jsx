import React, { useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

// Small anchored action menu for long-press gestures (see useLongPress).
// `anchor` is a viewport point (clientX/clientY of the triggering pointer
// event) — it gets converted to canvas-local coordinates and clamped so the
// panel never renders outside the fixed 1024x600 design canvas, however it's
// currently scaled (ScaledCanvas uses CSS `zoom`, which keeps this subtree's
// px == real viewport px, so a plain rect-relative subtraction is enough).
export default function ContextMenu({ open, anchor, items, onClose }) {
  const panelRef = useRef(null);
  const [pos, setPos] = useState(null);

  useLayoutEffect(() => {
    if (!open || !anchor) { setPos(null); return; }
    const canvas = document.getElementById(SCALED_CANVAS_ID);
    const panel = panelRef.current;
    if (!canvas || !panel) return;
    const canvasRect = canvas.getBoundingClientRect();
    const pw = panel.offsetWidth;
    const ph = panel.offsetHeight;
    const margin = 8;
    let x = anchor.x - canvasRect.left - pw / 2;
    let y = anchor.y - canvasRect.top - ph - 12; // open above the touch point
    if (y < margin) y = anchor.y - canvasRect.top + 12; // not enough room above → open below
    x = Math.min(Math.max(x, margin), canvasRect.width - pw - margin);
    y = Math.min(Math.max(y, margin), canvasRect.height - ph - margin);
    setPos({ x, y });
    // Re-measure once the panel has its real size (first render is 0x0).
  }, [open, anchor]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div className="absolute inset-0 z-[80]"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <div className="absolute inset-0" onClick={onClose} />
          <motion.div
            ref={panelRef}
            initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.92, opacity: 0 }}
            className="absolute min-w-[180px] bg-hifi-panel border border-hifi-border rounded-2xl py-1.5 shadow-2xl overflow-hidden"
            style={{ left: pos?.x ?? -9999, top: pos?.y ?? -9999, visibility: pos ? 'visible' : 'hidden' }}>
            {items.map(({ key, label, Icon, onSelect, danger }) => (
              <button key={key}
                onClick={() => { onSelect(); onClose(); }}
                className={`w-full flex items-center gap-3 px-4 py-3 text-sm text-left transition-colors ${
                  danger ? 'text-red-300 active:bg-red-500/10' : 'text-white active:bg-hifi-light'}`}>
                <Icon size={16} className={danger ? 'text-red-300' : 'text-hifi-gold'} />
                {label}
              </button>
            ))}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.getElementById(SCALED_CANVAS_ID) || document.body
  );
}
