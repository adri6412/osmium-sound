import React from 'react';
import ledBarLeftCap from '../assets/ledbar/led-bar-left-cap.png';
import ledBarFill from '../assets/ledbar/led-bar-fill.png';
import ledBarBase from '../assets/ledbar/led-bar-base.png';
import ledBarBitperfect from '../assets/ledbar/led-bar-bitperfect.png';
import ledBarReplaygain from '../assets/ledbar/led-bar-replaygain.png';
import ledQualityOff from '../assets/ledbar/led-quality-off.png';
import ledQualityGreen from '../assets/ledbar/led-quality-green.png';
import ledQualityYellow from '../assets/ledbar/led-quality-yellow.png';
import ledQualityDarkblue from '../assets/ledbar/led-quality-darkblue.png';
import ledQualityOrange from '../assets/ledbar/led-quality-orange.png';

const QUALITY_LED_SRC = { green: ledQualityGreen, yellow: ledQualityYellow, darkblue: ledQualityDarkblue, orange: ledQualityOrange };

// Four-segment hardware-style status bar: Format/bitrate (+ quality LED) |
// BitPerfect | ReplayGain. The BitPerfect/ReplayGain segments are baked art
// (from the source PSD, DSP segment removed — DSP is an unreleased paid
// feature, kept out of this bar). `mode` between them is mutually exclusive
// by design — LMS applies ReplayGain via software gain, so a track is never
// bit-perfect while it's active — matching the artwork, which only ever lit
// one LED.
//
// The Format segment can't be baked art: its text is arbitrary track
// metadata ("FLAC · 24bit · 96kHz"), not a fixed label. It's built from two
// real pixel slices lifted from that same artwork instead — the rounded end
// cap and an 8px column of the flat panel interior (its gradient only
// varies vertically, so tiling it horizontally is seamless) — so the seam
// against the baked segments is invisible despite the segment stretching to
// fit whatever text is passed in. Its own quality LED (green/yellow/
// dark-blue/orange) is the same trick one level down: the neutral "off"
// bezel is a pixel crop of the baked BitPerfect LED's own unlit state, green
// is that same LED's lit glow as-is, orange is the ReplayGain LED's lit glow
// as-is, and yellow/dark-blue are the green glow with only its hue rotated
// (its shading/highlight structure carries over untouched) — not the
// trademarked format logos, which is what these LEDs replaced.
//
// Wrapped in its own rounded-2xl + overflow-hidden shell — same corner
// radius as the album artwork card next to it — instead of trusting the
// baked cap art's own curvature to read as "rounded" at every render size;
// this guarantees clean corners on both ends regardless.
const LedBar = ({ mode, formatLabel, qualityLed, className = '' }) => (
  <div className={`inline-flex items-stretch select-none rounded-2xl overflow-hidden ${className}`}>
    <div className="shrink-0 h-full" style={{ aspectRatio: '52 / 175', backgroundImage: `url(${ledBarLeftCap})`, backgroundSize: '100% 100%' }} />
    <div className="flex items-center gap-2 shrink-0 h-full px-2"
      style={{
        backgroundImage: `url(${ledBarFill})`, backgroundRepeat: 'repeat-x', backgroundSize: 'auto 100%',
        borderRight: '1px solid rgba(180,200,220,0.08)',
      }}>
      {formatLabel && (
        <span className="text-[10px] text-hifi-silver/60 tracking-wide whitespace-nowrap">{formatLabel}</span>
      )}
      <div className="relative h-6 aspect-square shrink-0">
        <img src={ledQualityOff} alt="" draggable={false} className="absolute inset-0 w-full h-full pointer-events-none" />
        {qualityLed && (
          <img src={QUALITY_LED_SRC[qualityLed]} alt="" draggable={false}
            className="absolute inset-0 w-full h-full pointer-events-none transition-opacity duration-200" />
        )}
      </div>
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
