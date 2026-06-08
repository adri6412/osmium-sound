import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Delete } from 'lucide-react';
import { useKeyboard } from '../contexts/KeyboardContext';
import SimpleKeyboard from 'simple-keyboard';
import 'simple-keyboard/build/css/index.css';

const VirtualKeyboard = () => {
  const { isKeyboardVisible, inputValue, updateInputValue, hideKeyboard, confirmInput, activeInput } = useKeyboard();
  const keyboardRef = useRef(null);
  const containerRef = useRef(null);
  const simpleKeyboardRef = useRef(null);

  // Label shown above the preview (placeholder of the field being edited)
  const activeLabel =
    activeInput?.current?.getAttribute?.('aria-label') ||
    activeInput?.current?.placeholder ||
    'Inserisci testo';

  // Keep the active input visible above the keyboard. The keyboard occupies the
  // bottom half of the screen, so we add temporary bottom padding to the page and
  // scroll the field towards the top so it never ends up hidden behind the keys.
  useEffect(() => {
    if (!isKeyboardVisible) return;
    const el = activeInput?.current;
    document.body.style.paddingBottom = '55vh';
    if (el && el.scrollIntoView) {
      const t = setTimeout(() => {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 180);
      return () => clearTimeout(t);
    }
  }, [isKeyboardVisible, activeInput]);

  // Reset the page padding when the keyboard closes
  useEffect(() => {
    if (!isKeyboardVisible) {
      document.body.style.paddingBottom = '';
    }
    return () => {
      document.body.style.paddingBottom = '';
    };
  }, [isKeyboardVisible]);

  // Initialize SimpleKeyboard when component mounts and keyboard is visible
  useEffect(() => {
    if (isKeyboardVisible && keyboardRef.current && !simpleKeyboardRef.current) {
      simpleKeyboardRef.current = new SimpleKeyboard(keyboardRef.current, {
        layout: {
          default: [
            '1 2 3 4 5 6 7 8 9 0',
            'q w e r t y u i o p',
            'a s d f g h j k l',
            'z x c v b n m . -',
            '{space} {bksp}'
          ]
        },
        display: {
          '{space}': 'SPAZIO',
          '{bksp}': '⌫'
        },
        theme: 'hg-theme-default',
        physicalKeyboardHighlight: false,
        syncInstanceInputs: true,
        mergeDisplay: true,
        debug: false,
        buttonTheme: [
          {
            class: "hg-button-custom",
            buttons: "1 2 3 4 5 6 7 8 9 0 q w e r t y u i o p a s d f g h j k l z x c v b n m . - {space} {bksp}"
          }
        ],
        onChange: (input) => {
          updateInputValue(input);
        }
      });
    }

    // Cleanup when keyboard is hidden
    if (!isKeyboardVisible && simpleKeyboardRef.current) {
      simpleKeyboardRef.current.destroy();
      simpleKeyboardRef.current = null;
    }

    return () => {
      if (simpleKeyboardRef.current) {
        simpleKeyboardRef.current.destroy();
        simpleKeyboardRef.current = null;
      }
    };
  }, [isKeyboardVisible, inputValue, updateInputValue]);

  // Update keyboard input when inputValue changes
  useEffect(() => {
    if (simpleKeyboardRef.current) {
      simpleKeyboardRef.current.setInput(inputValue);
    }
  }, [inputValue]);

  // Close keyboard when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      // Use composedPath to handle elements that might be removed from the DOM
      // (like simple-keyboard buttons during re-renders)
      const path = event.composedPath();
      const isInside = path.some(el => el === containerRef.current);
      // Don't dismiss when the click originated from the field we're editing
      const isActiveField = activeInput?.current && path.includes(activeInput.current);

      if (containerRef.current && !isInside && !isActiveField) {
        hideKeyboard();
      }
    };

    if (isKeyboardVisible) {
      // Use capture phase to ensure we get the event before elements are removed
      document.addEventListener('mousedown', handleClickOutside, true);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside, true);
    };
  }, [isKeyboardVisible, hideKeyboard, activeInput]);

  return (
    <AnimatePresence>
      {isKeyboardVisible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 flex items-end justify-center pointer-events-none"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 9999,
            backgroundColor: 'transparent'
          }}
        >
          <motion.div
            ref={containerRef}
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: "spring", damping: 24, stiffness: 320 }}
            className="bg-hifi-dark border-t border-hifi-accent rounded-t-2xl p-4 w-full max-w-3xl pointer-events-auto shadow-2xl"
          >
            {/* Header with live preview of what is being typed */}
            <div className="flex items-end justify-between mb-3 gap-3">
              <div className="flex-1 min-w-0">
                <div className="text-xs text-hifi-silver mb-1 truncate">{activeLabel}</div>
                <div className="bg-black/40 border border-hifi-accent rounded-lg px-3 py-2 min-h-[2.75rem] flex items-center">
                  <span className="text-white font-mono text-lg break-all">
                    {inputValue || <span className="text-hifi-silver/40">…</span>}
                  </span>
                  <span className="kb-caret ml-0.5 text-hifi-gold font-mono text-lg">|</span>
                </div>
              </div>
              <motion.button
                onClick={hideKeyboard}
                className="p-2 rounded-lg bg-hifi-light hover:bg-hifi-accent text-white transition-colors shrink-0"
                whileTap={{ scale: 0.95 }}
                aria-label="Chiudi tastiera"
              >
                <X size={20} />
              </motion.button>
            </div>

            {/* Keyboard */}
            <div className="simple-keyboard-container-compact">
              <div ref={keyboardRef} className="simple-keyboard"></div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 mt-3">
              <motion.button
                onClick={() => updateInputValue('')}
                className="flex items-center justify-center gap-2 bg-hifi-light hover:bg-hifi-accent text-white px-4 py-2.5 rounded-lg font-semibold text-sm transition-colors"
                whileTap={{ scale: 0.95 }}
              >
                <Delete size={16} />
                Cancella
              </motion.button>
              <motion.button
                onClick={confirmInput}
                className="flex-1 bg-hifi-gold hover:bg-yellow-600 text-black py-2.5 rounded-lg font-semibold text-sm transition-colors"
                whileTap={{ scale: 0.95 }}
              >
                Conferma
              </motion.button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default VirtualKeyboard;
