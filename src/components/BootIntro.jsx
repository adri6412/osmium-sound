// BootIntro.jsx — fullscreen 5s "Osmium Sound" logo animation shown once at
// startup, before the main UI. Ported from the exported OsmiumIntro.jsx but
// stripped of the preview chrome: there is NO playback bar / controls, it does
// not loop, and it calls `onDone` when the 5s timeline finishes so the app can
// reveal the UI underneath.
import React from 'react';
import introLogo from '../assets/intro-logo.png';

// ── easing + interpolation ──────────────────────────────────────────────────
const Easing = {
  linear: (t) => t,
  easeOutQuad: (t) => t * (2 - t),
  easeInOutQuad: (t) => (t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t),
  easeOutCubic: (t) => (--t) * t * t + 1,
  easeOutExpo: (t) => (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)),
};
const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
const lerp = (a, b, t) => a + (b - a) * t;
function interpolate(input, output, ease = Easing.linear) {
  return (t) => {
    if (t <= input[0]) return output[0];
    if (t >= input[input.length - 1]) return output[output.length - 1];
    for (let i = 0; i < input.length - 1; i++) {
      if (t >= input[i] && t <= input[i + 1]) {
        const span = input[i + 1] - input[i];
        const local = span === 0 ? 0 : (t - input[i]) / span;
        return output[i] + (output[i + 1] - output[i]) * ease(local);
      }
    }
    return output[output.length - 1];
  };
}

// ── timeline context ──────────────────────────────────────────────────────────
const TimelineContext = React.createContext({ time: 0, duration: 5 });
const useTime = () => React.useContext(TimelineContext).time;

// ── Stage: fullscreen cover-scaled canvas, plays once, then onDone ───────────
function Stage({ width, height, duration = 5, background = '#080b10', onDone, children }) {
  const [time, setTime] = React.useState(0);
  const [scale, setScale] = React.useState(1);
  const [ready, setReady] = React.useState(false);
  const stageRef = React.useRef(null);
  const rafRef = React.useRef(null);
  const startRef = React.useRef(null);
  const doneRef = React.useRef(false);
  const onDoneRef = React.useRef(onDone);
  React.useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  // Decode the logo up-front so its first paint (when it fades in at ~1.1s)
  // doesn't hitch the animation mid-flight. The timeline only starts once the
  // image is ready (black screen until then), so playback runs smoothly.
  React.useEffect(() => {
    let cancelled = false;
    const done = () => { if (!cancelled) setReady(true); };
    const img = new Image();
    img.src = introLogo;
    if (img.decode) img.decode().then(done).catch(done);
    else { img.onload = done; img.onerror = done; }
    // Safety: never block the intro for more than 1.2s on a slow decode.
    const t = setTimeout(done, 1200);
    return () => { cancelled = true; clearTimeout(t); };
  }, []);

  // Cover-scale the 1920×1080 scene to fill the screen (crop, no letterbox).
  React.useEffect(() => {
    if (!stageRef.current) return;
    const el = stageRef.current;
    const measure = () => {
      const s = Math.max(el.clientWidth / width, el.clientHeight / height);
      setScale(Math.max(0.05, s));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener('resize', measure);
    return () => { ro.disconnect(); window.removeEventListener('resize', measure); };
  }, [width, height]);

  // Monotonic 0 → duration playback, once. Waits for the logo to be decoded.
  React.useEffect(() => {
    if (!ready) return;
    const step = (ts) => {
      if (startRef.current == null) startRef.current = ts;
      const elapsed = (ts - startRef.current) / 1000;
      setTime(Math.min(elapsed, duration));
      if (elapsed >= duration) {
        if (!doneRef.current) { doneRef.current = true; onDoneRef.current && onDoneRef.current(); }
        return;
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [duration, ready]);

  const ctxValue = React.useMemo(() => ({ time, duration }), [time, duration]);

  return (
    <div ref={stageRef} style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', background: '#000' }}>
      <div style={{ width, height, background, position: 'relative', transform: `scale(${scale})`, transformOrigin: 'center', flexShrink: 0, overflow: 'hidden' }}>
        <TimelineContext.Provider value={ctxValue}>{children}</TimelineContext.Provider>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
//  INTRO SCENE (unchanged from the export)
// ─────────────────────────────────────────────────────────────────────────────
const GOLD = '#d6a94c';
const GOLD_LT = '#f3d488';
const SILVER = '#c9cdd6';
const CX = 960;        // logo mark horizontal center on a 1920 canvas
const CY = 470;        // logo mark vertical center (cover-cropped)

const PARTICLES = Array.from({ length: 22 }, (_, i) => {
  const r = (n) => { const x = Math.sin((i + 1) * 12.9898 + n * 78.233) * 43758.5453; return x - Math.floor(x); };
  return { x: 120 + r(1) * 1680, y: 120 + r(2) * 840, s: 1.5 + r(3) * 3.5, sp: 0.6 + r(4) * 1.8, ph: r(5) * 6.28, drift: 20 + r(6) * 40, gold: r(7) > 0.55 };
});

function Backdrop() {
  return <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(125% 120% at 50% 40%, #1c2433 0%, #11161f 46%, #080b10 100%)' }} />;
}

function EQBars() {
  const t = useTime();
  const ramp = clamp(interpolate([0, 1.05], [0, 1], Easing.easeOutQuad)(t), 0, 1);
  const out = clamp(interpolate([1.15, 1.55], [0, 1])(t), 0, 1);
  const amp = ramp * (1 - out);
  if (amp <= 0.002) return null;
  const N = 25, bw = 9, gap = 11, total = N * bw + (N - 1) * gap, x0 = CX - total / 2, cy = 560;
  const bars = [];
  for (let i = 0; i < N; i++) {
    const phase = i * 0.55;
    const dist = Math.abs(i - (N - 1) / 2) / ((N - 1) / 2);
    const env = 0.35 + 0.65 * (1 - dist);
    const h = (16 + (Math.abs(Math.sin(t * 6.0 + phase)) * 0.72 + 0.28) * 150 * env) * amp;
    const gold = i % 3 === 1;
    bars.push(<div key={i} style={{ position: 'absolute', left: x0 + i * (bw + gap), top: cy - h / 2, width: bw, height: h, borderRadius: bw / 2, background: gold ? `linear-gradient(${GOLD_LT},${GOLD})` : `linear-gradient(#eef1f6,${SILVER})`, opacity: 0.6 * amp, boxShadow: gold ? `0 0 14px ${GOLD}66` : '0 0 11px rgba(201,205,214,0.4)' }} />);
  }
  return <div style={{ position: 'absolute', inset: 0 }}>{bars}</div>;
}

function Particles() {
  const t = useTime();
  const fade = clamp(interpolate([0, 0.45], [0, 1])(t), 0, 1) * (1 - clamp(interpolate([1.2, 1.7], [0, 1])(t), 0, 1));
  if (fade <= 0.002) return null;
  return (
    <div style={{ position: 'absolute', inset: 0 }}>
      {PARTICLES.map((p, i) => {
        const tw = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * p.sp * 2.5 + p.ph));
        const y = p.y - (t * p.drift);
        return <div key={i} style={{ position: 'absolute', left: p.x, top: y, width: p.s, height: p.s, borderRadius: '50%', background: p.gold ? GOLD_LT : '#eaeef5', opacity: tw * fade * 0.8, boxShadow: `0 0 ${p.s * 3}px ${p.gold ? GOLD : '#cfd6e2'}` }} />;
      })}
    </div>
  );
}

function GlowBurst() {
  const t = useTime();
  if (t < 1.05 || t > 2.15) return null;
  const p = clamp((t - 1.12) / 0.85, 0, 1);
  const sc = lerp(0.32, 1.75, Easing.easeOutCubic(p));
  const op = (1 - p) * 0.9;
  const size = 1000;
  return <div style={{ position: 'absolute', left: CX - size / 2, top: CY - size / 2, width: size, height: size, borderRadius: '50%', background: `radial-gradient(circle, ${GOLD_LT}dd 0%, ${GOLD}55 32%, transparent 66%)`, opacity: op, transform: `scale(${sc})`, filter: 'blur(8px)', willChange: 'transform, opacity' }} />;
}

function LogoLayer() {
  const t = useTime();
  const inP = clamp((t - 1.12) / 0.95, 0, 1);
  const e = Easing.easeOutExpo(inP);
  const opacity = clamp((t - 1.12) / 0.5, 0, 1);
  const scaleIn = lerp(1.16, 1.0, e);
  const breathe = t > 2.1 ? 0.011 * Math.sin((t - 2.1) * 1.5) : 0;
  const scale = scaleIn * (1 + breathe);
  // Only transform + opacity here (both GPU-composited). The original animated
  // `filter: blur()/brightness()` re-rasterized the whole 1.3 MP logo every
  // frame — far too heavy on Pi-class hardware and the main source of stutter.
  return (
    <div style={{ position: 'absolute', inset: 0, opacity, transform: `scale(${scale})`, transformOrigin: '50% 43%', willChange: 'transform, opacity' }}>
      <img src={introLogo} alt="Osmium Sound" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
    </div>
  );
}

function Sheen() {
  const t = useTime();
  if (t < 2.35 || t > 3.45) return null;
  const p = clamp((t - 2.4) / 0.95, 0, 1);
  const x = lerp(-45, 150, Easing.easeInOutQuad(p));
  const op = Math.sin(p * Math.PI) * 0.55;
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
      <div style={{ position: 'absolute', top: '-20%', left: `${x}%`, width: '26%', height: '140%', transform: 'skewX(-16deg)', background: `linear-gradient(90deg, transparent, ${GOLD_LT}99, #ffffffcc, ${GOLD_LT}99, transparent)`, opacity: op, filter: 'blur(9px)', mixBlendMode: 'screen' }} />
    </div>
  );
}

function Flash() {
  const t = useTime();
  if (t < 1.08 || t > 1.65) return null;
  const p = clamp((t - 1.12) / 0.42, 0, 1);
  const op = (1 - p) * 0.55;
  return <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(circle at 50% 43%, ${GOLD_LT}, transparent 58%)`, opacity: op, mixBlendMode: 'screen', pointerEvents: 'none' }} />;
}

function Ring({ start, t }) {
  const age = t - start;
  if (age < 0 || age > 1.7) return null;
  const p = age / 1.7;
  const size = lerp(300, 1550, Easing.easeOutCubic(p));
  const op = (1 - p) * 0.16;
  return <div style={{ position: 'absolute', left: CX, top: CY, width: size, height: size, marginLeft: -size / 2, marginTop: -size / 2, borderRadius: '50%', border: `2px solid ${GOLD_LT}`, opacity: op }} />;
}
function PulseRings() {
  const t = useTime();
  return (
    <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', mixBlendMode: 'screen' }}>
      <Ring start={2.5} t={t} />
      <Ring start={3.4} t={t} />
      <Ring start={4.3} t={t} />
    </div>
  );
}

function Vignette() {
  return <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none', background: 'radial-gradient(115% 110% at 50% 44%, transparent 55%, rgba(4,6,9,0.55) 100%)' }} />;
}

function Scene() {
  return (
    <React.Fragment>
      <Backdrop />
      <GlowBurst />
      <EQBars />
      <Particles />
      <LogoLayer />
      <Sheen />
      <PulseRings />
      <Flash />
      <Vignette />
    </React.Fragment>
  );
}

/**
 * Fullscreen boot intro. Plays the 5s animation once, then calls `onDone`.
 * `duration` lets the caller shorten/extend it (the choreography targets 5s).
 */
export default function BootIntro({ onDone, duration = 5 }) {
  return (
    <Stage width={1920} height={1080} duration={duration} background="#080b10" onDone={onDone}>
      <Scene />
    </Stage>
  );
}
