import React from 'react';
import ledBarBase from '../assets/ledbar/led-bar-base.png';
import ledBarHires from '../assets/ledbar/led-bar-hires.png';
import ledBarPcm from '../assets/ledbar/led-bar-pcm.png';
import ledBarDsd from '../assets/ledbar/led-bar-dsd.png';
import ledBarBitperfect from '../assets/ledbar/led-bar-bitperfect.png';
import ledBarReplaygain from '../assets/ledbar/led-bar-replaygain.png';

// Native proportions (px) of the baked artwork. A single flat plate now (no
// more cap+tiled-fill+body split for an arbitrary-width format string — that
// text moved back above the transport controls) with fixed glow overlays
// stacked on top and toggled by opacity.
//
// The artwork itself is the flat ("biscotto flat") redesign: matte plate, no
// gloss, and the LED domes only exist in the lit overlays — an unlit segment
// is simply empty above its label, so the base plate carries no dark dome.
const NATIVE_W = 897;
const NATIVE_H = 175;

// No CSS corner rounding here any more: the old plate bled to the edge of its
// own bounding box, so the bar needed a border-radius to match the album
// cover's rounded-2xl. The flat plate draws its own corners inset inside a
// transparent margin, so any radius applied here would only clip empty pixels.
//
// The source PSD draws a DSP label, icon and lit dome in the third segment;
// all three are cut from the exported artwork, since DSP isn't part of this
// build. The segment's own separator line is kept, so what's left is the same
// free slot the previous plate had — and the brand mark goes back into it, at
// the label row's own vertical centre rather than the old plate's.
const BRAND_BOX = { left: '81%', top: '49%', width: '12.82%', height: '28.57%' };

// Hardware-style status plate: Hi-Res/PCM/DSD format-quality LEDs on the left,
// BitPerfect/ReplayGain further right. `quality` lights the format LEDs per
// the source file's own rate/depth (PCM alone at 44.1/16, PCM+Hi-Res above
// that, DSD+Hi-Res for DSD) — independent of playback state. `mode` is
// mutually exclusive by design — LMS applies ReplayGain via software gain, so
// a track is never bit-perfect while it's active — matching the artwork,
// which only ever lit one of the two.
const LedBar = ({ mode, quality, className = '', style }) => (
  <div className={`relative select-none ${className}`}
    style={{ aspectRatio: `${NATIVE_W} / ${NATIVE_H}`, containerType: 'inline-size', ...style }}>
    <img src={ledBarBase} alt="" draggable={false} className="block w-full h-full pointer-events-none" />
    <img src={ledBarHires} alt="Hi-Res" draggable={false}
      className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200"
      style={{ opacity: quality?.hires ? 1 : 0 }} />
    <img src={ledBarPcm} alt="PCM" draggable={false}
      className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200"
      style={{ opacity: quality?.pcm ? 1 : 0 }} />
    <img src={ledBarDsd} alt="DSD" draggable={false}
      className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200"
      style={{ opacity: quality?.dsd ? 1 : 0 }} />
    <img src={ledBarBitperfect} alt="BitPerfect" draggable={false}
      className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200"
      style={{ opacity: mode === 'bitperfect' ? 1 : 0 }} />
    <img src={ledBarReplaygain} alt="ReplayGain" draggable={false}
      className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200"
      style={{ opacity: mode === 'replaygain' ? 1 : 0 }} />
    <div className="absolute flex flex-col items-center justify-center leading-[1.05] pointer-events-none" style={BRAND_BOX}>
      {/* cqw, not a fixed px size: this is the one label that isn't baked
          into the raster art, so it needs to scale with the bar itself
          (container-type: inline-size set above) instead of staying a fixed
          size while everything around it grows/shrinks. */}
      <span className="font-bold tracking-[0.1em] text-white/90" style={{ fontSize: '2.1cqw' }}>OSMIUM</span>
      <span className="font-bold tracking-[0.1em] text-hifi-gold" style={{ fontSize: '2.1cqw' }}>SOUND</span>
    </div>
  </div>
);

export default React.memo(LedBar);
