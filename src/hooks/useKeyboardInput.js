import { useRef, useEffect } from 'react';
import { useKeyboard } from '../contexts/KeyboardContext';

export const useKeyboardInput = (value, onChange) => {
  const inputRef = useRef(null);
  const { showKeyboard } = useKeyboard();

  useEffect(() => {
    const input = inputRef.current;
    if (!input) {
      console.log('⚠️ useKeyboardInput: input ref is null');
      return;
    }

    // Handled by global hook in App.jsx now.
    // We keep this hook around to not break existing components (e.g., Settings.jsx)
    // and let the global hook handle showing the keyboard.

    // Make input look clickable but still allow focus
    input.style.cursor = 'pointer';
    input.readOnly = true; // Prevent physical keyboard input

    return () => {
      if (input) {
        input.style.cursor = 'text';
        input.readOnly = false;
      }
    };
  }, []);

  return inputRef;
};