import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useI18n } from '../i18n';
import { SCALED_CANVAS_ID } from './ScaledCanvas';

// Anti-burn-in drift target: a handful of fixed offsets the background cycles
// through, one every DRIFT_INTERVAL_MS. Picked ahead of time (not randomized
// per-tick) so the value is stable between renders.
const DRIFT_OFFSETS = [
  { x: '0%', y: '0%' }, { x: '8%', y: '5%' }, { x: '-6%', y: '9%' },
  { x: '5%', y: '-7%' }, { x: '-8%', y: '-4%' }
];
const DRIFT_INTERVAL_MS = 45000;

// `requireTap`: this screensaver was raised on purpose (the clock button in
// the Now Playing header), not by the idle timer — a passing mouse move or a
// grazed touch must not dismiss it, only a real tap/click on the screen.
const Screensaver = ({ isActive, requireTap, onWake }) => {
  const { localeTag } = useI18n();
  const [time, setTime] = useState(new Date());
  const [driftIdx, setDriftIdx] = useState(0);

  useEffect(() => {
    if (!isActive) return;

    // Update time every second
    const interval = setInterval(() => {
      setTime(new Date());
    }, 1000);

    return () => clearInterval(interval);
  }, [isActive]);

  // Anti-burn-in background drift, driven at a low discrete frequency instead
  // of a continuous/infinite Web Animations timeline. A `repeat: Infinity`
  // transform tween keeps Chromium's compositor producing a new frame every
  // vsync for as long as the screensaver is up (measured ~23% Render/3D on
  // Gen9 iGPUs just for this) — see [[no-heavy-animations-weak-igpu]]. Moving
  // to a fixed target every 45s means the compositor is only active for the
  // brief transition below, then idles completely between moves.
  useEffect(() => {
    if (!isActive) return;
    const id = setInterval(() => {
      setDriftIdx((i) => (i + 1) % DRIFT_OFFSETS.length);
    }, DRIFT_INTERVAL_MS);
    return () => clearInterval(id);
  }, [isActive]);

  const formatTime = (date) => {
    return {
      hours: date.getHours().toString().padStart(2, '0'),
      minutes: date.getMinutes().toString().padStart(2, '0'),
      seconds: date.getSeconds().toString().padStart(2, '0'),
      dateStr: date.toLocaleDateString(localeTag(), {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      })
    };
  };

  const { hours, minutes, seconds, dateStr } = formatTime(time);

  return createPortal(
    <AnimatePresence>
      {isActive && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 1 }} // Slow fade in/out
          className="absolute inset-0 z-[100] bg-black flex flex-col items-center justify-center cursor-none"
          onClick={onWake}
        >
          {/* Subtle slow-moving gradient background for avoiding pure black static
              burn-in. Animates `transform` (GPU-composited, no repaint) instead of
              `background-position` — the previous version animated
              background-position on a box sized to its default 100%/100%
              background-size, which repainted this full-canvas layer every frame,
              forever, for zero visible pan (there was no extra gradient area to
              move across). Oversized via `inset: -50%` (200% of the container,
              centered) so the transform-driven drift has room to move.
              `animate` targets a single fixed offset (from DRIFT_OFFSETS, swapped
              every 45s in state above) instead of a `repeat: Infinity` keyframe
              array — the compositor only has to do work for the brief transition
              between offsets, then goes fully idle until the next swap. */}
          <motion.div
            className="absolute opacity-20 bg-gradient-to-br from-hifi-dark via-black to-hifi-gray"
            style={{ inset: '-50%' }}
            animate={DRIFT_OFFSETS[driftIdx]}
            transition={{ duration: 4, ease: 'easeInOut' }}
          />

          <div className="relative z-10 flex flex-col items-center select-none">
            {/* Main Clock */}
            <div className="flex items-baseline space-x-4 text-white font-light tracking-wider">
              <span className="text-[12rem] leading-none">{hours}</span>
              {/* Blinks once per second, driven by the existing `time` tick rather
                  than a continuous CSS `animate-pulse` (infinite keyframe loop —
                  compositor busy forever while the screensaver is up). */}
              <span className={`text-[10rem] leading-none mb-8 transition-opacity duration-200 ${seconds % 2 === 0 ? 'opacity-50' : 'opacity-20'}`}>:</span>
              <span className="text-[12rem] leading-none">{minutes}</span>
            </div>

            {/* Seconds & Date */}
            <div className="flex flex-col items-center mt-8">
              <span className="text-3xl text-hifi-gold font-mono tracking-[0.2em] opacity-80 mb-4">
                {seconds}
              </span>
              <span className="text-2xl text-hifi-silver/60 uppercase tracking-widest">
                {dateStr}
              </span>
            </div>

            {/* Floating Brand/Logo */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 mt-64 opacity-20 flex items-center space-x-2">
              <div className="w-2 h-2 rounded-full bg-hifi-gold"></div>
              <span className="text-sm tracking-[0.5em] uppercase text-white font-bold">HiFi Player</span>
            </div>
          </div>

          {/* Invisible overlay to catch any interaction. A tap/click always
              wakes (it bubbles to the onClick above); move/touch-start only
              count for the idle screensaver — see `requireTap`. */}
          <div className="absolute inset-0"
            onMouseMove={requireTap ? undefined : onWake}
            onTouchStart={requireTap ? undefined : onWake} />
        </motion.div>
      )}
    </AnimatePresence>,
    document.getElementById(SCALED_CANVAS_ID) || document.body
  );
};

export default Screensaver;