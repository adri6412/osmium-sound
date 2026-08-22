import React from 'react';

// Wall clock pill shown in the fullscreen Now Playing header (tap = start the
// screensaver). Kept in its own component, with its own ticking state, so the
// update re-renders just this pill instead of the whole LyrionServer tree.
//
// The tick is a self-re-aiming timeout on the next :00 second, not a 1s
// interval: with only hours:minutes on screen that's one wake-up (and one
// repaint of a two-word element) per minute, nothing in between — the
// always-on Now Playing screen is exactly where a per-second re-render would
// otherwise keep the iGPU busy for no visible change.
const twoDigits = (n) => n.toString().padStart(2, '0');
// 24h, same as the screensaver clock this button opens — the two are seen
// back to back, so they shouldn't disagree on format.
const readClock = () => {
  const d = new Date();
  return `${twoDigits(d.getHours())}:${twoDigits(d.getMinutes())}`;
};

const NowPlayingClock = ({ active, onActivate, title }) => {
  const [text, setText] = React.useState(readClock);

  React.useEffect(() => {
    // The Now Playing layer stays mounted forever once opened (it's only
    // hidden), so without this gate the clock would keep ticking behind a
    // screen nobody is looking at.
    if (!active) return undefined;
    let id;
    const tick = () => {
      setText(readClock());
      const now = new Date();
      // Floor the delay: a timeout that fires a millisecond *early* would
      // otherwise re-aim itself at ~0ms and tick twice on the same boundary.
      id = setTimeout(tick, Math.max(500, (60 - now.getSeconds()) * 1000 - now.getMilliseconds()));
    };
    tick();
    return () => clearTimeout(id);
  }, [active]);

  return (
    <button onClick={onActivate} title={title} aria-label={title}
      className="px-4 py-1 rounded-full bg-white/10 hover:bg-white/20 active:bg-white/25 text-white text-xl font-medium tracking-wide tabular-nums transition-colors">
      {text}
    </button>
  );
};

export default NowPlayingClock;
