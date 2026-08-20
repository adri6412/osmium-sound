import React, { useState, useRef, useEffect } from 'react';
import useWebSocket, { ReadyState } from 'react-use-websocket';
import { motion, useSpring, useTransform, useMotionValue } from 'framer-motion';
import vuMeterDials from '../assets/vu-meter-dials.png';
import vuMeterBezel from '../assets/vu-meter-bezel.png';

// The artwork is a single 1280x675 stereo panel: both dial faces live in
// `vu-meter-dials.png` and the black bezel that frames them (LEFT/RIGHT
// engraving included) lives in `vu-meter-bezel.png`, whose two dial windows
// are cut out. So the whole meter is one composited unit — the needles are
// positioned in percentages of that shared 1280x675 box, not per-dial.
const PANEL_W = 1280;
const PANEL_H = 675;

// Each needle pivots from the apex of the wavy notch at the bottom of its
// bezel window (where a real VU meter's pivot pin sits), measured off the
// bezel artwork's own alpha channel: the notch tops out at y=385 for the left
// window and y=387 for the right, centred on x=336 / x=945.
const PIVOTS = [
  { x: 336, y: 385 },
  { x: 945, y: 387 },
];

// Needle sweep measured off the dial artwork's own tick marks, by polar-
// binning the black/red ink around the pivot: the long "20" tick that opens
// the scale sits at -47.5 deg and the last tick of the red overload arc ("3")
// at +48 deg, both reaching out to r=236.
const ANGLE_MIN = -47.5;
const ANGLE_MAX = 48;
// Needle length in artwork pixels, reaching just past those tick tips.
const NEEDLE_LENGTH = 245;
// Minimum peak change (0-100 scale) before we redirect the needle spring at
// all. Below this, level-message noise (quiet passages, sustained tones)
// would otherwise keep re-targeting the spring 20x/sec forever, which is
// exactly the kind of unbounded continuous transform animation that pins
// the i915/iris Render engine busy at low clock on Gemini Lake (see
// freedesktop.org drm/i915 work item 16771) — letting truly-stable levels
// fall below this threshold lets the spring actually settle and go idle.
const LEVEL_DELTA_THRESHOLD = 2;

const pct = (v, total) => `${(v / total) * 100}%`;

// `value` is a framer-motion MotionValue (0-100). Driving the needle straight
// from a MotionValue means level updates never trigger a React re-render — the
// needle moves purely on the compositor.
const VUNeedle = ({ value, pivot }) => {
  // Create a spring for smooth needle movement
  const springValue = useSpring(value, {
    stiffness: 150,
    damping: 15,
    mass: 0.5,
  });

  const rotate = useTransform(springValue, [0, 100], [ANGLE_MIN, ANGLE_MAX]);

  return (
    <>
      {/* The needle — anchored at the pivot, rotating about its own base */}
      <motion.div
        className="absolute bg-[#111] shadow-[1px_0_3px_rgba(0,0,0,0.6)] z-10"
        style={{
          left: pct(pivot.x, PANEL_W),
          top: pct(pivot.y, PANEL_H),
          width: '0.3%',
          minWidth: '2px',
          height: pct(NEEDLE_LENGTH, PANEL_H),
          x: '-50%',
          y: '-100%',
          rotate,
          transformOrigin: 'bottom center',
        }}
      />
      {/* Needle pivot cap — sits in the notch, half-hidden by the bezel */}
      <div
        className="absolute bg-[#111] rounded-full z-20 shadow-md"
        style={{
          left: pct(pivot.x, PANEL_W),
          top: pct(pivot.y, PANEL_H),
          width: '1.4%',
          aspectRatio: '1',
          transform: 'translate(-50%, -50%)',
        }}
      />
    </>
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
    <div className={`flex items-center justify-center w-full h-full [container-type:size] ${className}`}>
      {/* The panel letterboxes itself inside whatever box the caller gives us,
          but it has to do so by *sizing this div*, not by object-fit on the
          images: the needles are positioned in percentages of this div, so an
          object-contain letterbox inside a differently-shaped box would leave
          them pointing off the dials. Hence container-query units — the width
          is whichever of the container's own width or its height-times-aspect
          is smaller, and aspect-ratio derives the height from it. */}
      <div
        className="relative"
        style={{
          width: `min(100cqw, 100cqh * ${PANEL_W} / ${PANEL_H})`,
          aspectRatio: `${PANEL_W} / ${PANEL_H}`,
        }}
      >
        <img src={vuMeterDials} alt="" draggable={false}
             className="block w-full h-full pointer-events-none select-none" />

        <VUNeedle value={leftValue} pivot={PIVOTS[0]} />
        <VUNeedle value={rightValue} pivot={PIVOTS[1]} />

        {/* Bezel frame + glass — masks everything above to the dial windows */}
        <img src={vuMeterBezel} alt="" draggable={false}
             className="absolute inset-0 w-full h-full pointer-events-none select-none z-30" />
      </div>
    </div>
  );
};

// Memoized so LyrionServer's 1 Hz status poll doesn't re-render the meter;
// its own websocket-driven MotionValues handle needle motion independently.
export default React.memo(AnalogVUMeter);
