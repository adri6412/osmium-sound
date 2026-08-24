import React, { createContext, useContext, useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { isCharacterKey } from '../utils/physicalKeyboard';

// Split into two contexts on purpose. `showKeyboard`/`hideKeyboard`/etc. are
// stable action references that most consumers (App.jsx, Settings.jsx) only
// need to call a keyboard open — they don't care about live keystrokes.
// `isKeyboardVisible`/`inputValue` change on every keystroke while the
// keyboard is open, and are only actually needed by VirtualKeyboard's own
// preview. Bundling everything into one context value meant every keystroke
// changed the object identity and re-rendered *every* consumer, including
// App.jsx near the root of the tree — cascading into the whole app on every
// character typed on any field (search box, WiFi password, settings inputs).
// Keeping actions and live state in separate contexts means a consumer that
// only reads actions never re-renders from keystrokes at all.
const KeyboardActionsContext = createContext(null);
const KeyboardStateContext = createContext(null);

export const useKeyboardActions = () => {
  const context = useContext(KeyboardActionsContext);
  if (!context) {
    throw new Error('useKeyboardActions must be used within a KeyboardProvider');
  }
  return context;
};

const useKeyboardState = () => {
  const context = useContext(KeyboardStateContext);
  if (!context) {
    throw new Error('useKeyboardState must be used within a KeyboardProvider');
  }
  return context;
};

// Back-compat combined hook for consumers that genuinely need both (currently
// only VirtualKeyboard, which is expected to re-render on every keystroke
// since it renders the live preview/caret).
export const useKeyboard = () => {
  const actions = useKeyboardActions();
  const state = useKeyboardState();
  return { ...actions, ...state };
};

const setNativeValue = (el, value) => {
  if (el.tagName === 'INPUT') {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(el, value);
  } else if (el.tagName === 'TEXTAREA') {
    Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(el, value);
  } else {
    el.value = value;
  }
  el.dispatchEvent(new Event('input', { bubbles: true }));
};

// How long to wait, after the last keystroke, before pushing the typed value
// into the real underlying <input>/<textarea>. That real field usually lives
// in some other big screen (Settings, the WiFi setup wizard, ...) whose own
// onChange/setState re-renders that whole screen — syncing on every single
// keystroke meant every character typed anywhere re-rendered its entire host
// screen. The virtual keyboard already shows its own live preview of what's
// typed (VirtualKeyboard.jsx), so the real field doesn't need to track every
// keystroke in real time — only closely enough that it feels instant.
const DOM_SYNC_DEBOUNCE_MS = 150;

export const KeyboardProvider = ({ children }) => {
  const [isKeyboardVisible, setIsKeyboardVisible] = useState(false);
  const [activeInput, setActiveInput] = useState(null);
  const [inputValue, setInputValue] = useState('');

  // Actions read current state via refs rather than closing over the state
  // variables above, so they can stay referentially stable (empty deps)
  // instead of being recreated (and changing the actions context value)
  // every time isKeyboardVisible/activeInput/inputValue change.
  const isVisibleRef = useRef(isKeyboardVisible);
  const activeInputRef = useRef(activeInput);
  const inputValueRef = useRef(inputValue);
  isVisibleRef.current = isKeyboardVisible;
  activeInputRef.current = activeInput;
  inputValueRef.current = inputValue;

  const syncTimerRef = useRef(null);
  // Immediately pushes whatever's currently typed into the real field and
  // cancels any pending debounced sync — used whenever the keyboard is about
  // to close or switch fields, so a value never gets lost mid-debounce.
  const flushSync = useCallback(() => {
    clearTimeout(syncTimerRef.current);
    const el = activeInputRef.current?.current;
    if (el) setNativeValue(el, inputValueRef.current);
  }, []);

  const showKeyboard = useCallback((inputRef, currentValue = '') => {
    // Re-focusing the SAME field mid-debounce (e.g. tapping it again to move
    // the caret while typing) can hand us a stale `currentValue` — it's read
    // from the DOM before this call, which may not have caught up with the
    // last few keystrokes yet. In that case keep our own (fresher) in-flight
    // value instead of clobbering it; only adopt `currentValue` when this is
    // genuinely a different field.
    const sameField = inputRef?.current && inputRef.current === activeInputRef.current?.current;
    if (!sameField) {
      flushSync(); // commit whatever was pending on the previously active field
      setInputValue(currentValue);
    }
    setActiveInput(inputRef);
    setIsKeyboardVisible(true);
  }, [flushSync]);

  const hideKeyboard = useCallback(() => {
    flushSync();
    setIsKeyboardVisible(false);
    setActiveInput(null);
    setInputValue('');
  }, [flushSync]);

  const updateInputValue = useCallback((value) => {
    setInputValue(value); // drives the virtual keyboard's own live preview
    clearTimeout(syncTimerRef.current);
    syncTimerRef.current = setTimeout(flushSync, DOM_SYNC_DEBOUNCE_MS);
  }, [flushSync]);

  const confirmInput = useCallback(() => {
    hideKeyboard(); // flushes the pending value and closes
  }, [hideKeyboard]);

  const toggleKeyboard = useCallback(() => {
    if (isVisibleRef.current) hideKeyboard();
    else showKeyboard(null, '');
  }, [hideKeyboard, showKeyboard]);

  // A real character key pressed while the on-screen keyboard is open means
  // there IS a physical keyboard after all (internal laptop keyboards aren't
  // reported by the main process — see src/utils/physicalKeyboard.js). Close
  // the on-screen one *before* the character lands in the field: this runs
  // in the capture phase of keydown, hideKeyboard() flushes whatever was
  // typed on-screen into the field synchronously, and only then does the
  // browser append the physical character — nothing is lost either way.
  // Leaving it open would be worse: its own preview value, now stale, would
  // overwrite the physically typed text on its next flush.
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (isVisibleRef.current && isCharacterKey(e)) hideKeyboard();
    };
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [hideKeyboard]);

  // Listen for global shortcut toggle
  useEffect(() => {
    const handleGlobalToggle = () => toggleKeyboard();
    if (window.electronAPI) {
      window.electronAPI.onToggleSimpleKeyboard?.(handleGlobalToggle);
    }
    return () => {
      if (window.electronAPI?.removeToggleSimpleKeyboard) {
        window.electronAPI.removeToggleSimpleKeyboard(handleGlobalToggle);
      }
    };
  }, [toggleKeyboard]);

  const actionsValue = useMemo(() => ({
    showKeyboard,
    hideKeyboard,
    updateInputValue,
    confirmInput,
    toggleKeyboard
  }), [showKeyboard, hideKeyboard, updateInputValue, confirmInput, toggleKeyboard]);

  const stateValue = useMemo(() => ({
    isKeyboardVisible,
    activeInput,
    inputValue
  }), [isKeyboardVisible, activeInput, inputValue]);

  return (
    <KeyboardActionsContext.Provider value={actionsValue}>
      <KeyboardStateContext.Provider value={stateValue}>
        {children}
      </KeyboardStateContext.Provider>
    </KeyboardActionsContext.Provider>
  );
};
