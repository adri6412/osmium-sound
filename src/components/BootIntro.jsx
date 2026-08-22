// BootIntro.jsx — fullscreen boot animation shown once at startup, before the
// main UI. The animation is a pre-rendered clip (assets/intro.mp4, 7.5s of
// 1080p H.264) rather than the hand-written JSX timeline it replaced: a single
// video layer costs the weak Intel iGPU far less than compositing a dozen
// animated DOM layers every frame, and re-exporting the artwork no longer
// means porting a new timeline into this file.
//
// The clip opens and closes on black, so App.jsx's 600 ms overlay fade lands on
// a black frame and the UI simply comes up out of it.
import React from 'react';
import introVideo from '../assets/intro.mp4';

/**
 * Fullscreen boot intro. Plays the clip once, then calls `onDone`.
 * `maxDuration` (seconds) is a watchdog, not the choreography: this kiosk has
 * no keyboard and no window manager, so if the video never reports `ended`
 * (missing codec, truncated file, wedged decoder) the intro must hand over
 * anyway instead of leaving a black overlay on screen forever.
 */
export default function BootIntro({ onDone, maxDuration = 15 }) {
  const videoRef = React.useRef(null);
  const doneRef = React.useRef(false);
  const onDoneRef = React.useRef(onDone);
  React.useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  const finish = React.useCallback(() => {
    if (doneRef.current) return;
    doneRef.current = true;
    onDoneRef.current && onDoneRef.current();
  }, []);

  React.useEffect(() => {
    const t = setTimeout(finish, maxDuration * 1000);
    return () => clearTimeout(t);
  }, [finish, maxDuration]);

  // Muted autoplay is allowed, but play() can still reject (autoplay policy in
  // a dev browser, decoder error). Treat that like a finished intro rather than
  // sitting on a frozen first frame.
  React.useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const p = v.play();
    if (p && p.catch) p.catch(finish);
  }, [finish]);

  return (
    <div style={{ position: 'absolute', inset: 0, background: '#000', overflow: 'hidden' }}>
      <video
        ref={videoRef}
        src={introVideo}
        autoPlay
        muted
        playsInline
        preload="auto"
        onEnded={finish}
        onError={finish}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
      />
    </div>
  );
}
