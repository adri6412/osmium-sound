import React, { createContext, useContext, useState, useEffect } from 'react';

const KeyboardContext = createContext();

export const useKeyboard = () => {
  const context = useContext(KeyboardContext);
  if (!context) {
    throw new Error('useKeyboard must be used within a KeyboardProvider');
  }
  return context;
};

export const KeyboardProvider = ({ children }) => {
  const [isKeyboardVisible, setIsKeyboardVisible] = useState(false);
  const [activeInput, setActiveInput] = useState(null);
  const [inputValue, setInputValue] = useState('');

  const showKeyboard = (inputRef, currentValue = '') => {
    setActiveInput(inputRef);
    setInputValue(currentValue);
    setIsKeyboardVisible(true);
  };

  const hideKeyboard = () => {
    setIsKeyboardVisible(false);
    setActiveInput(null);
    setInputValue('');
  };

  const updateInputValue = (value) => {
    setInputValue(value);
    if (activeInput && activeInput.current) {
      // Use native setters to correctly trigger React's synthetic events
      if (activeInput.current.tagName === 'INPUT') {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeInputValueSetter.call(activeInput.current, value);
      } else if (activeInput.current.tagName === 'TEXTAREA') {
        const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
        nativeTextAreaValueSetter.call(activeInput.current, value);
      } else {
        activeInput.current.value = value;
      }

      // Trigger change event
      const event = new Event('input', { bubbles: true });
      activeInput.current.dispatchEvent(event);
    }
  };

  const confirmInput = () => {
    if (activeInput && activeInput.current) {
      if (activeInput.current.tagName === 'INPUT') {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeInputValueSetter.call(activeInput.current, inputValue);
      } else if (activeInput.current.tagName === 'TEXTAREA') {
        const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
        nativeTextAreaValueSetter.call(activeInput.current, inputValue);
      } else {
        activeInput.current.value = inputValue;
      }

      // Trigger change event
      const event = new Event('input', { bubbles: true });
      activeInput.current.dispatchEvent(event);
    }
    hideKeyboard();
  };

  const toggleKeyboard = () => {
    if (isKeyboardVisible) {
      hideKeyboard();
    } else {
      showKeyboard(null, '');
    }
  };

  // Listen for global shortcut toggle
  useEffect(() => {
    const handleGlobalToggle = () => {
      toggleKeyboard();
    };

    // Listen for the global shortcut event from main process
    if (window.electronAPI) {
      window.electronAPI.onToggleSimpleKeyboard?.(handleGlobalToggle);
    }

    return () => {
      if (window.electronAPI?.removeToggleSimpleKeyboard) {
        window.electronAPI.removeToggleSimpleKeyboard(handleGlobalToggle);
      }
    };
  }, [isKeyboardVisible]);

  const value = {
    isKeyboardVisible,
    activeInput,
    inputValue,
    showKeyboard,
    hideKeyboard,
    updateInputValue,
    confirmInput,
    toggleKeyboard
  };

  return (
    <KeyboardContext.Provider value={value}>
      {children}
    </KeyboardContext.Provider>
  );
};