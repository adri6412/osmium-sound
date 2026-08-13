import React from 'react';
import ledBarLeftCap from '../assets/ledbar/led-bar-left-cap.png';
import ledBarFill from '../assets/ledbar/led-bar-fill.png';
import ledBarBase from '../assets/ledbar/led-bar-base.png';
import ledBarBitperfect from '../assets/ledbar/led-bar-bitperfect.png';
import ledBarReplaygain from '../assets/ledbar/led-bar-replaygain.png';

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
// against the baked segments is invisible despite the segment stretching to
// fit whatever text is passed in.
const LedBar = ({ mode, formatLabel, className = '' }) => (
  <div className={`inline-flex items-stretch select-none ${className}`}>
    <div className="shrink-0 h-full" style={{ aspectRatio: '52 / 175', backgroundImage: `url(${ledBarLeftCap})`, backgroundSize: '100% 100%' }} />
    <div className="flex items-center shrink-0 h-full px-2"
      style={{
        backgroundImage: `url(${ledBarFill})`, backgroundRepeat: 'repeat-x', backgroundSize: 'auto 100%',
        borderRight: '1px solid rgba(180,200,220,0.15)', boxShadow: 'inset -2px 0 4px rgba(0,0,0,0.35)',
      }}>
      {formatLabel && (
        <span className="text-[10px] text-hifi-silver/60 tracking-wide whitespace-nowrap">{formatLabel}</span>
      )}
    </div>
    <div className="relative shrink-0 h-full" style={{ aspectRatio: '480 / 175' }}>
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
