import React, { useState, useRef, useEffect } from 'react';
import useWebSocket, { ReadyState } from 'react-use-websocket';
import { motion, useSpring, useTransform, useMotionValue } from 'framer-motion';
import vuMeterBackground from '../assets/vu-meter-background.png';
import vuMeterForeground from '../assets/vu-meter-foreground.png';

// The needle pivots from the wavy notch at the bottom of the foreground
// bezel's viewing window (where a real VU meter's pivot pin sits) — measured
// from the artwork itself (971x960 canvas, notch apex at ~[468, 580]) rather
// than guessed, so it lines up with the printed scale regardless of how this
// component gets resized.
const PIVOT_X_PCT = 48.2;
const PIVOT_Y_PCT = 60.4;
// Needle sweep measured off the artwork's own tick marks: "20" (silence, full
// left) to "+"/overload (full right), via a circle fit through the scale's
// tick tips.
const ANGLE_MIN = -58;
const ANGLE_MAX = 60;
// Needle length as % of the meter's own height, reaching just past the tick
// tips (radius ~27.5% of width in the source art) for a visible overshoot.
const NEEDLE_LENGTH_PCT = 34;

// `value` is a framer-motion MotionValue (0-100). Driving the needle straight
// from a MotionValue means level updates never trigger a React re-render — the
// needle moves purely on the compositor.
const SingleVUMeter = ({ value, label }) => {
  // Create a spring for smooth needle movement
  const springValue = useSpring(value, {
    stiffness: 150,
    damping: 15,
    mass: 0.5,
  });

  const rotate = useTransform(springValue, [0, 100], [ANGLE_MIN, ANGLE_MAX]);

  return (
    <div className="relative w-full min-w-[150px] max-w-[450px] h-full aspect-square overflow-hidden">
      {/* Dial face */}
      <img src={vuMeterBackground} alt="" draggable={false}
           className="absolute inset-0 w-full h-full object-contain pointer-events-none select-none" />

      {/* The Needle — anchored at the pivot, rotating about its own base */}
      <motion.div
        className="absolute bg-[#111] shadow-[1px_0_3px_rgba(0,0,0,0.6)] z-10"
        style={{
          left: `${PIVOT_X_PCT}%`,
          top: `${PIVOT_Y_PCT}%`,
          width: '2px',
          height: `${NEEDLE_LENGTH_PCT}%`,
          x: '-50%',
          y: '-100%',
          rotate,
          transformOrigin: 'bottom center',
        }}
      />
      {/* Needle Pivot Cap */}
      <div className="absolute w-3 h-3 bg-[#111] rounded-full z-20 shadow-md"
           style={{ left: `${PIVOT_X_PCT}%`, top: `${PIVOT_Y_PCT}%`, transform: 'translate(-50%, -50%)' }} />

      {/* Bezel frame + glass — masks everything above to the viewing window */}
      <img src={vuMeterForeground} alt="" draggable={false}
           className="absolute inset-0 w-full h-full object-contain pointer-events-none select-none z-30" />
    </div>
  );
};

/**
 * Dual Analog VU Meter component replacing the digital bars
 */
const AnalogVUMeter = ({ isPlaying, className = "" }) => {
  // Needle positions are MotionValues, not React state: updating them moves the
  // needles on the compositor without re-rendering this component. At ~30-60
  // level messages/sec from the daemon, this turns dozens of React re-renders
  // per second into zero.
  const leftValue = useMotionValue(0);
  const rightValue = useMotionValue(0);
  const lastUpdateRef = useRef(0);
  const [socketUrl, setSocketUrl] = useState(`ws://${window.location.hostname}:9001`);

  const { lastMessage, readyState } = useWebSocket(socketUrl, {
    shouldReconnect: () => true,
    reconnectInterval: 3000,
  });

  useEffect(() => {
    const savedApiHost = localStorage.getItem('apiHost');
    if (savedApiHost) {
        try {
            const url = new URL(savedApiHost);
            setSocketUrl(`ws://${url.hostname}:9001`);
        } catch(e) {}
    } else if (window.location.hostname && window.location.hostname !== 'localhost') {
        setSocketUrl(`ws://${window.location.hostname}:9001`);
    } else {
        setSocketUrl('ws://localhost:9001');
    }
  }, []);

  useEffect(() => {
    if (lastMessage === null) return;
    // Throttle target updates to 20 Hz (was ~33 Hz). This does NOT make the
    // needle motion choppy: useSpring below keeps interpolating every
    // compositor frame regardless of how often we redirect it, exactly like
    // a real VU meter's mechanical inertia smooths over individual samples —
    // only the *reaction time* to brand-new peaks is very slightly longer,
    // not the smoothness of the sweep itself. What it does cut is how often
    // the spring gets re-targeted while mid-flight during continuous
    // playback (see main.js's did-finish-load comment — Electron's
    // setFrameRate() doesn't actually cap this window's frame rate, so nothing
    // else limits how often that redirection happens), which is the one
    // animation running non-stop for the entire duration of playback, unlike
    // the app's other, transient page-transition/loading animations.
    const now = performance.now();
    if (now - lastUpdateRef.current < 50) return;
    lastUpdateRef.current = now;
    try {
      const data = JSON.parse(lastMessage.data);
      if (data.levels && Array.isArray(data.levels)) {
        const mid = Math.floor(data.levels.length / 2);
        const leftBars = data.levels.slice(0, mid);
        const rightBars = data.levels.slice(mid);
        const getPeak = (arr) => (arr.length ? Math.max(...arr) : 0);
        leftValue.set(getPeak(leftBars));
        rightValue.set(getPeak(rightBars));
      }
    } catch (error) {
      console.error("Error parsing VU meter websocket data:", error);
    }
  }, [lastMessage, leftValue, rightValue]);

  // Fallback animation if WS is disconnected but audio is playing
  useEffect(() => {
    let timeoutId;
    let animationFrameId;
    let isActive = true;

    if (readyState !== ReadyState.OPEN) {
        if (!isPlaying) {
          // Drop to 0. We let framer-motion's useSpring handle the smooth drop,
          // so we only need to set the value to 0 once here.
          leftValue.set(0);
          rightValue.set(0);
          return;
        }

        // Simulate audio
        const animateFallback = () => {
          if (!isActive) return;

          const sim = () => {
            const base = Math.random() * 100;
            return base > 80 ? base : Math.random() * 50 + 5;
          };
          leftValue.set(sim());
          rightValue.set(sim());

          timeoutId = setTimeout(() => {
            if (isActive) animationFrameId = requestAnimationFrame(animateFallback);
          }, 80);
        };

        animationFrameId = requestAnimationFrame(animateFallback);

        return () => {
          isActive = false;
          if (timeoutId) clearTimeout(timeoutId);
          if (animationFrameId) cancelAnimationFrame(animationFrameId);
        };
    }
  }, [isPlaying, readyState, leftValue, rightValue]);

  return (
    <div className={`flex items-center justify-center bg-[#111] p-2 md:p-3 rounded-lg shadow-[inset_0_0_10px_rgba(0,0,0,1)] border-2 md:border-4 border-[#1a1a1a] w-full max-w-full ${className}`}>
      <div className="flex w-full h-full justify-center gap-1 md:gap-2">
        <SingleVUMeter value={leftValue} label="L" />
        <div className="w-1 md:w-2 rounded bg-gradient-to-b from-[#222] to-[#111] shadow-inner" /> {/* Separator */}
        <SingleVUMeter value={rightValue} label="R" />
      </div>
    </div>
  );
};

// Memoized so LyrionServer's 1 Hz status poll doesn't re-render the meter;
// only `isPlaying` changes matter here.
export default React.memo(AnalogVUMeter);