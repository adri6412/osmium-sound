// ScaledCanvas — scales the app's fixed 1024x600 design canvas up (or down) to
// fit whatever real window size Electron gives us (7" touchscreen, 1080p/4K TV
// over HDMI, etc). Uses the same ResizeObserver + transform:scale technique as
// BootIntro.jsx's Stage, but "contain" (Math.min) instead of "cover": the UI
// scales as large as possible while staying fully visible, with letterbox bars
// (matching the app's near-black background) rather than cropping any content.
import React from 'react';

const DESIGN_WIDTH = 1024;
const DESIGN_HEIGHT = 600;

export default function ScaledCanvas({ children }) {
  const outerRef = React.useRef(null);
  const [scale, setScale] = React.useState(1);

  React.useEffect(() => {
    if (!outerRef.current) return;
    const el = outerRef.current;
    const measure = () => {
      const s = Math.min(el.clientWidth / DESIGN_WIDTH, el.clientHeight / DESIGN_HEIGHT);
      setScale(Math.max(0.05, s));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener('resize', measure);
    return () => { ro.disconnect(); window.removeEventListener('resize', measure); };
  }, []);

  return (
    <div
      ref={outerRef}
      style={{
        position: 'fixed', inset: 0, display: 'flex', alignItems: 'center',
        justifyContent: 'center', overflow: 'hidden', background: '#0a0a0a'
      }}
    >
      <div
        style={{
          width: DESIGN_WIDTH, height: DESIGN_HEIGHT, position: 'relative',
          transform: `scale(${scale})`, transformOrigin: 'center', flexShrink: 0,
          overflow: 'hidden'
        }}
      >
        {children}
      </div>
    </div>
  );
}
