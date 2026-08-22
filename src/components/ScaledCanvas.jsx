// ScaledCanvas — scales the app's fixed 1024x600 design canvas up (or down) to
// fit whatever real window size Electron gives us (7" touchscreen, 1080p/4K TV
// over HDMI, etc). "Contain" (Math.min): the UI scales as large as possible
// while staying fully visible, with letterbox bars (matching the app's
// near-black background) rather than cropping any content.
//
// Uses CSS `zoom`, not `transform: scale()`. transform only affects
// compositing/paint — Chromium still rasterizes the layer's content at (near)
// its "ideal" scale on every repaint, so anything continuously animating
// inside it (VU meters, EQ bars, ...) gets re-rasterized at the *scaled*
// resolution every frame. On weak kiosk-class iGPUs (e.g. Intel Gemini Lake)
// that pegs the Render/3D engine at 100% during normal playback. `zoom`
// instead re-flows layout at the target size up front, so painting costs the
// same as if the page had simply been designed at that size — no
// scale-and-recomposite tax.
import React from 'react';

const DESIGN_WIDTH = 1024;
const DESIGN_HEIGHT = 600;

// Portal target id: several fullscreen overlays (LyrionServer's expanded
// player/queue/modals, RoomCorrectionWizard, CdRip, Settings dialogs, the
// virtual keyboard, ...) use createPortal/position:absolute to escape
// ancestor overflow:hidden/stacking contexts while staying pinned to the
// 1024x600 canvas. Unlike `transform`, `zoom` does NOT establish a containing
// block for `position:fixed` descendants, so those overlays are written as
// `position:absolute` and portaled to be direct children of this div (which
// is itself `position:relative`) rather than relying on a fixed/viewport
// trick.
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
          zoom: scale, flexShrink: 0, overflow: 'hidden'
        }}
      >
        {children}
      </div>
    </div>
  );
}
