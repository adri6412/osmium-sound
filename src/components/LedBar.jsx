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
const NATIVE_W = 897;
const NATIVE_H = 175;

// The album cover next to this bar is a square using Tailwind's rounded-2xl
// (16px) — at its ~320px size, a 5%-of-edge corner. Reusing that same 16px
// flat on the bar looked wrong even once the two matched exactly in overall
// width: the bar's own rendered height is only ~width * (NATIVE_H/NATIVE_W),
// so a 16px radius there eats a much bigger share of that edge — the corners
// visually dominate and the bar reads as shorter/more pill-shaped than the
// cover despite the identical bounding-box width. Scaling the radius down by
// that same NATIVE_H/NATIVE_W factor keeps both corners at the same
// 5%-of-height proportion, so they actually match instead of just sharing a
// number.
const COVER_RADIUS_PX = 16;
const BAR_RADIUS_PX = COVER_RADIUS_PX * (NATIVE_H / NATIVE_W);

// Hardware-style status plate: Hi-Res/PCM/DSD format-quality LEDs on the left,
// BitPerfect/ReplayGain further right. `quality` lights the format LEDs per
// the source file's own rate/depth (PCM alone at 44.1/16, PCM+Hi-Res above
// that, DSD+Hi-Res for DSD) — independent of playback state. `mode` is
// mutually exclusive by design — LMS applies ReplayGain via software gain, so
// a track is never bit-perfect while it's active — matching the artwork,
// which only ever lit one of the two.
const LedBar = ({ mode, quality, className = '', style }) => (
  <div className={`relative select-none overflow-hidden ${className}`}
    style={{ aspectRatio: `${NATIVE_W} / ${NATIVE_H}`, borderRadius: `${BAR_RADIUS_PX}px`, ...style }}>
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
  </div>
);

export default React.memo(LedBar);
