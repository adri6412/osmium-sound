// Whether a physical keyboard is connected RIGHT NOW — plugging one in
// suppresses the on-screen keyboard, unplugging it brings the on-screen one
// back, live, with no restart needed. Nothing here is remembered across app
// restarts on purpose: this always reflects current hardware state.
//
// Source of truth is the main process (main/main.js polls udev's
// `*-event-kbd` symlinks under /dev/input every 2s and pushes changes here
// — Chromium/Electron has no renderer-side HID enumeration API). Outside
// Electron (e.g. a plain browser dev preview, no window.electronAPI) there's
// no such signal at all, so this falls back to a same-session "have we seen
// a real keydown" heuristic: a real key press dispatches a native `keydown`;
// VirtualKeyboard.jsx never does (it pushes typed text straight into the
// field via a native value setter + an `input` event — see setNativeValue in
// KeyboardContext.jsx) — so any `keydown` observed here is real. That
// fallback can only ever turn on, never off (no way to detect an unplug
// without the IPC signal), which is why it's dev-preview-only.
let detected = false;

if (typeof window !== 'undefined' && window.electronAPI?.getPhysicalKeyboard) {
  window.electronAPI.getPhysicalKeyboard().then((v) => { detected = !!v; }).catch(() => {});
  window.electronAPI.onPhysicalKeyboardChanged?.((_event, v) => { detected = !!v; });
} else if (typeof document !== 'undefined') {
  const IGNORED_KEYS = new Set(['Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'AltGraph', 'Unidentified']);
  document.addEventListener('keydown', (e) => {
    if (!IGNORED_KEYS.has(e.key)) detected = true;
  }, true);
}

export const hasPhysicalKeyboard = () => detected;
