import { useRef, useCallback } from 'react';

// Press-and-hold gesture: fires `onLongPress(x, y)` after `threshold` ms of
// holding still. Cancels itself if the finger moves past `moveTolerance`
// before the timer fires — the same behavior a native scroll gesture would
// give, so a long-press attempt that turns into a scroll doesn't also open a
// menu. `onPointerMove` is deliberately NOT captured (no setPointerCapture,
// no touchAction:'none') so normal scrolling/tapping on the element keeps
// working; only the timer reacts to movement.
export function useLongPress(onLongPress, { threshold = 500, moveTolerance = 10 } = {}) {
  const timerRef = useRef(null);
  const startRef = useRef({ x: 0, y: 0 });
  const firedRef = useRef(false);

  const clear = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
  }, []);

  const onPointerDown = useCallback((e) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    startRef.current = { x: e.clientX, y: e.clientY };
    firedRef.current = false;
    clear();
    timerRef.current = setTimeout(() => {
      firedRef.current = true;
      onLongPress(e.clientX, e.clientY);
    }, threshold);
  }, [clear, onLongPress, threshold]);

  const onPointerMove = useCallback((e) => {
    if (!timerRef.current) return;
    const dx = e.clientX - startRef.current.x;
    const dy = e.clientY - startRef.current.y;
    if (Math.hypot(dx, dy) > moveTolerance) clear();
  }, [clear, moveTolerance]);

  // A tap/click firing right after a successful long-press would double-act
  // on the same gesture (e.g. play the track AND open its menu) — callers
  // check this ref in their onClick and skip it when true.
  const didLongPress = useCallback(() => firedRef.current, []);

  return {
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: clear,
      onPointerCancel: clear,
      onPointerLeave: clear,
    },
    didLongPress,
  };
}
