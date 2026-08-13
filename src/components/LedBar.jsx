import React from 'react';
import ledBarBase from '../assets/ledbar/led-bar-base.png';
import ledBarBitperfect from '../assets/ledbar/led-bar-bitperfect.png';
import ledBarReplaygain from '../assets/ledbar/led-bar-replaygain.png';

// Two-segment hardware-style status bar (BitPerfect / ReplayGain). `mode` is
// mutually exclusive by design — LMS applies ReplayGain via software gain,
// so a track can never be bit-perfect while ReplayGain is active — matching
// the source artwork, which only ever lights one LED at a time.
// (No DSP segment: DSP is an unreleased paid feature, kept out of this bar.)
const LedBar = ({ mode, className = '' }) => (
  <div className={`relative inline-block ${className}`} style={{ aspectRatio: '532 / 175' }}>
    <img src={ledBarBase} alt="" draggable={false}
      className="block w-full h-full select-none pointer-events-none" />
    <img src={ledBarBitperfect} alt="BitPerfect" draggable={false}
      className="absolute inset-0 w-full h-full select-none pointer-events-none transition-opacity duration-200"
      style={{ opacity: mode === 'bitperfect' ? 1 : 0 }} />
    <img src={ledBarReplaygain} alt="ReplayGain" draggable={false}
      className="absolute inset-0 w-full h-full select-none pointer-events-none transition-opacity duration-200"
      style={{ opacity: mode === 'replaygain' ? 1 : 0 }} />
  </div>
);

export default React.memo(LedBar);
