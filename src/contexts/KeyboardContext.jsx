import React, { createContext, useContext, useState, useEffect, useRef, useMemo, useCallback } from 'react';

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

  const showKeyboard = useCallback((inputRef, currentValue = '') => {
    setActiveInput(inputRef);
    setInputValue(currentValue);
    setIsKeyboardVisible(true);
  }, []);

  const hideKeyboard = useCallback(() => {
    setIsKeyboardVisible(false);
    setActiveInput(null);
    setInputValue('');
  }, []);

  const updateInputValue = useCallback((value) => {
    setInputValue(value);
    const el = activeInputRef.current?.current;
    if (el) setNativeValue(el, value);
  }, []);

  const confirmInput = useCallback(() => {
    const el = activeInputRef.current?.current;
    if (el) setNativeValue(el, inputValueRef.current);
    hideKeyboard();
  }, [hideKeyboard]);

  const toggleKeyboard = useCallback(() => {
    if (isVisibleRef.current) hideKeyboard();
    else showKeyboard(null, '');
  }, [hideKeyboard, showKeyboard]);

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
