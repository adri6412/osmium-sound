import React from 'react';
import ledBarLeftCap from '../assets/ledbar/led-bar-left-cap.png';
import ledBarFill from '../assets/ledbar/led-bar-fill.png';
import ledBarBase from '../assets/ledbar/led-bar-base.png';
import ledBarBitperfect from '../assets/ledbar/led-bar-bitperfect.png';
import ledBarReplaygain from '../assets/ledbar/led-bar-replaygain.png';

// Native proportions (px, at the source artwork's own 175px height): the
// rounded end cap, a fixed-width Format/bitrate segment, then the baked
// BitPerfect/ReplayGain segments. Fixed widths (not content-driven) so the
// whole bar always renders at exactly this aspect ratio regardless of how
// long the format text is — long labels truncate instead of stretching the
// bar past the album artwork's own width, which is what `className="w-full"`
// callers rely on to line the two up exactly.
const CAP_W = 52;
const FORMAT_W = 340;
const BODY_W = 480;
const TOTAL_W = CAP_W + FORMAT_W + BODY_W;
const NATIVE_H = 175;
const pct = (w) => `${(w / TOTAL_W) * 100}%`;

// Three-segment hardware-style status bar: Format/bitrate | BitPerfect |
// ReplayGain. The BitPerfect/ReplayGain segments are baked art (from the
// source PSD, DSP segment removed — DSP is an unreleased paid feature, kept
// out of this bar). `mode` between them is mutually exclusive by design —
// LMS applies ReplayGain via software gain, so a track is never bit-perfect
// while it's active — matching the artwork, which only ever lit one LED.
//
// The Format segment can't be baked art: its text is arbitrary track
// metadata ("FLAC · 24bit · 96kHz"), not a fixed label. It's built from two
// real pixel slices lifted from that same artwork instead — the rounded end
// cap and an 8px column of the flat panel interior (its gradient only
// varies vertically, so tiling it horizontally is seamless) — so the seam
// against the baked segments is invisible.
//
// Wrapped in its own rounded-2xl + overflow-hidden shell — same corner
// radius as the album artwork card next to it — instead of trusting the
// baked cap art's own curvature to read as "rounded" at every render size;
// this guarantees clean corners on both ends regardless.
const LedBar = ({ mode, formatLabel, className = '' }) => (
  <div className={`flex items-stretch select-none rounded-2xl overflow-hidden ${className}`}
    style={{ aspectRatio: `${TOTAL_W} / ${NATIVE_H}` }}>
    <div className="shrink-0 h-full" style={{ width: pct(CAP_W), backgroundImage: `url(${ledBarLeftCap})`, backgroundSize: '100% 100%' }} />
    <div className="flex items-center shrink-0 h-full px-2 overflow-hidden"
      style={{
        width: pct(FORMAT_W),
        backgroundImage: `url(${ledBarFill})`, backgroundRepeat: 'repeat-x', backgroundSize: 'auto 100%',
        borderRight: '1px solid rgba(180,200,220,0.08)',
      }}>
      {formatLabel && (
        <span className="text-[10px] text-hifi-silver/60 tracking-wide truncate">{formatLabel}</span>
      )}
    </div>
    <div className="relative shrink-0 h-full" style={{ width: pct(BODY_W) }}>
      <img src={ledBarBase} alt="" draggable={false}
        className="block w-full h-full pointer-events-none" />
      <img src={ledBarBitperfect} alt="BitPerfect" draggable={false}
        className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200"
        style={{ opacity: mode === 'bitperfect' ? 1 : 0 }} />
      <img src={ledBarReplaygain} alt="ReplayGain" draggable={false}
        className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200"
        style={{ opacity: mode === 'replaygain' ? 1 : 0 }} />
    </div>
  </div>
);

export default React.memo(LedBar);
