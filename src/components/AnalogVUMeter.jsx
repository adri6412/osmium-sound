import React, { useState, useRef, useEffect } from 'react';
import useWebSocket, { ReadyState } from 'react-use-websocket';
import { motion, useSpring, useTransform, useMotionValue } from 'framer-motion';
import vuMeterBackground from '../assets/vu-meter-background.png';
import vuMeterForeground from '../assets/vu-meter-foreground.png';

// The needle pivots from the wavy notch at the bottom of the foreground
// bezel's viewing window (where a real VU meter's pivot pin sits) — measured
// from the artwork itself (971x960 canvas). Anchored at the notch's actual
// low point (~[468, 638]) rather than partway up it: the shallower spot used
// previously left the pivot cap floating above the cutout instead of sitting
// in it, which also reads as slightly less parallel to the tick marks'
// own incline than pinning it at the notch's lowest dip does. Verified by
// overlaying the rotated needle on the source artwork at both sweep extremes
// (see PR discussion) — the tips still land on the "20" and "0"/red-zone
// ticks with the length bumped accordingly below.
const PIVOT_X_PCT = 48.2;
const PIVOT_Y_PCT = 66.5;
// Needle sweep measured off the artwork's own tick marks: "20" (silence, full
// left) to "+"/overload (full right), via a circle fit through the scale's
// tick tips.
const ANGLE_MIN = -58;
const ANGLE_MAX = 60;
// Needle length as % of the meter's own height, reaching just past the tick
// tips. Longer than the pivot-at-the-notch-shoulder version (was 34) to
// still clear the same tips now that the pivot sits lower.
const NEEDLE_LENGTH_PCT = 37.5;
// Minimum peak change (0-100 scale) before we redirect the needle spring at
// all. Below this, level-message noise (quiet passages, sustained tones)
// would otherwise keep re-targeting the spring 20x/sec forever, which is
// exactly the kind of unbounded continuous transform animation that pins
// the i915/iris Render engine busy at low clock on Gemini Lake (see
// freedesktop.org drm/i915 work item 16771) — letting truly-stable levels
// fall below this threshold lets the spring actually settle and go idle.
const LEVEL_DELTA_THRESHOLD = 2;

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
// `visible` defaults true so any other caller keeps today's always-on
// behavior; LyrionServer's expanded-player usage is the one that now keeps
// this component permanently mounted (instead of destroying/recreating its
// dial images and composited needle layer on every open/close) and passes
// visible={false} while it's off-screen or the lyrics view is showing —
// this is what actually avoids the ongoing cost of staying mounted: no
// websocket data in, no spring re-targeting, nothing for the compositor to
// keep redrawing.
const AnalogVUMeter = ({ visible = true, className = "" }) => {
  // Needle positions are MotionValues, not React state: updating them moves the
  // needles on the compositor without re-rendering this component. At ~30-60
  // level messages/sec from the daemon, this turns dozens of React re-renders
  // per second into zero.
  const leftValue = useMotionValue(0);
  const rightValue = useMotionValue(0);
  const lastUpdateRef = useRef(0);
  const lastLeftCommittedRef = useRef(0);
  const lastRightCommittedRef = useRef(0);
  const [socketUrl, setSocketUrl] = useState(`ws://${window.location.hostname}:9001`);

  // Passing `null` to react-use-websocket skips connecting entirely (its
  // documented way to pause) -- so the socket only exists while a viewer
  // could actually see the needles move, not for the component's whole
  // (now much longer) mounted lifetime.
  const { lastMessage, readyState } = useWebSocket(visible ? socketUrl : null, {
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
      if (Array.isArray(data.levels_l) && Array.isArray(data.levels_r)) {
        const getPeak = (arr) => (arr.length ? Math.max(...arr) : 0);
        const peakL = getPeak(data.levels_l);
        const peakR = getPeak(data.levels_r);
        // Only redirect the spring when the level actually moved by more
        // than noise-floor jitter — see LEVEL_DELTA_THRESHOLD above.
        if (Math.abs(peakL - lastLeftCommittedRef.current) >= LEVEL_DELTA_THRESHOLD) {
          leftValue.set(peakL);
          lastLeftCommittedRef.current = peakL;
        }
        if (Math.abs(peakR - lastRightCommittedRef.current) >= LEVEL_DELTA_THRESHOLD) {
          rightValue.set(peakR);
          lastRightCommittedRef.current = peakR;
        }
      }
    } catch (error) {
      console.error("Error parsing VU meter websocket data:", error);
    }
  }, [lastMessage, leftValue, rightValue]);

  // No real level data available (hidden, or WS disconnected): rest at zero
  // rather than faking movement. A VU meter is a measuring instrument, not
  // decoration — showing random motion when there's no signal to back it up
  // would be actively misleading, on top of being another unbounded
  // continuous-transform loop for the iris driver to chew on for no reason.
  useEffect(() => {
    if (!visible || readyState !== ReadyState.OPEN) {
      leftValue.set(0);
      rightValue.set(0);
      lastLeftCommittedRef.current = 0;
      lastRightCommittedRef.current = 0;
    }
  }, [visible, readyState, leftValue, rightValue]);

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
// its own websocket-driven MotionValues handle needle motion independently.
export default React.memo(AnalogVUMeter);