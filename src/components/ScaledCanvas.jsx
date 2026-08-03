// ScaledCanvas — scales the app's fixed 1024x600 design canvas up (or down) to
// fit whatever real window size Electron gives us (7" touchscreen, 1080p/4K TV
// over HDMI, etc). Uses the same ResizeObserver + transform:scale technique as
// BootIntro.jsx's Stage, but "contain" (Math.min) instead of "cover": the UI
// scales as large as possible while staying fully visible, with letterbox bars
// (matching the app's near-black background) rather than cropping any content.
import React from 'react';

const DESIGN_WIDTH = 1024;
const DESIGN_HEIGHT = 600;

// Portal target id: several fullscreen overlays (LyrionServer's expanded
// player/queue/modals, RoomCorrectionWizard, CdRip) use createPortal to
// escape ancestor overflow:hidden/stacking contexts. If they portal to
// document.body they land OUTSIDE this transformed canvas — body isn't a
// descendant of it — so they render at native physical size instead of
// scaling with everything else. Portaling into this div instead keeps them
// inside the transform's containing block, so `position:fixed` in those
// overlays still resolves against the 1024x600 canvas, not the real screen.
export const SCALED_CANVAS_ID = 'hifi-scaled-canvas';

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
        id={SCALED_CANVAS_ID}
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
