// Whether a physical keyboard is connected RIGHT NOW — plugging one in
// suppresses the on-screen keyboard, unplugging it brings the on-screen one
// back, live, with no restart needed. Nothing here is remembered across app
// restarts on purpose: this always reflects current hardware state.
//
// Two signals, either one is enough:
//
// 1. The main process (main/inputDevices.js, polled every 2s and pushed here
//    over IPC — Chromium/Electron has no renderer-side HID enumeration API):
//    a USB or Bluetooth keyboard someone can type on is plugged in. Live in
//    both directions. It deliberately does NOT report internal laptop
//    keyboards (i8042/PS/2, I2C, SPI): they're indistinguishable from the
//    phantom "AT Translated Set 2 keyboard" most x86 boards register with
//    nothing attached, and trusting that phantom is exactly how touch-only
//    appliances ended up with no keyboard at all.
//
// 2. This session: a real letter key was pressed. A real key press
//    dispatches a native `keydown`; VirtualKeyboard.jsx never does (it pushes
//    typed text straight into the field via a native value setter + an
//    `input` event — see setNativeValue in KeyboardContext.jsx) — so any
//    letter keydown observed here comes from real hardware, and covers the
//    laptop keyboards (1) leaves out. Letters only (`code` KeyA..KeyZ): a
//    TV/IR remote's digits, arrows and Enter must not count as "someone is
//    typing on a keyboard". Cleared again when (1) reports an unplug, so
//    plug-a-keyboard-for-a-long-password-then-unplug still brings the
//    on-screen keyboard back.
//
// Outside Electron (plain browser dev preview, no window.electronAPI) only
// (2) exists.
let pluggedIn = false;
let typedThisSession = false;

/** A key press that inserts a character into the focused field (letter, digit, punctuation, space). */
export const isCharacterKey = (e) => e.key?.length === 1 && !e.ctrlKey && !e.metaKey;

/** A letter key — the strongest evidence there is that someone is typing on a real keyboard. */
export const isLetterKey = (e) => isCharacterKey(e) && /^Key[A-Z]$/.test(e.code || '');

if (typeof window !== 'undefined' && window.electronAPI?.getPhysicalKeyboard) {
  window.electronAPI.getPhysicalKeyboard().then((v) => { pluggedIn = !!v; }).catch(() => {});
  window.electronAPI.onPhysicalKeyboardChanged?.((_event, v) => {
    pluggedIn = !!v;
    if (!v) typedThisSession = false;
  });
}
if (typeof document !== 'undefined') {
  document.addEventListener('keydown', (e) => {
    if (isLetterKey(e)) typedThisSession = true;
  }, true);
}

export const hasPhysicalKeyboard = () => pluggedIn || typedThisSession;
