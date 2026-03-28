import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';
import { useKeyboard } from '../contexts/KeyboardContext';
import SimpleKeyboard from 'simple-keyboard';
import 'simple-keyboard/build/css/index.css';

const VirtualKeyboard = () => {
  const { isKeyboardVisible, inputValue, updateInputValue, hideKeyboard, confirmInput, activeInput } = useKeyboard();
  const keyboardRef = useRef(null);
  const containerRef = useRef(null);
  const simpleKeyboardRef = useRef(null);

  // Scroll active input into view when keyboard becomes visible
  useEffect(() => {
    if (isKeyboardVisible && activeInput && activeInput.current) {
      // Small delay to allow keyboard animation to start/complete so layout is updated
      setTimeout(() => {
        activeInput.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 150);
    }
  }, [isKeyboardVisible, activeInput]);

  // Initialize SimpleKeyboard when component mounts and keyboard is visible
  useEffect(() => {
    console.log('🎹 VirtualKeyboard useEffect triggered!', { 
      isKeyboardVisible, 
      keyboardRef: keyboardRef.current, 
      simpleKeyboardRef: simpleKeyboardRef.current 
    });
    
    if (isKeyboardVisible && keyboardRef.current && !simpleKeyboardRef.current) {
      console.log('🎹 Creating SimpleKeyboard instance...');
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
          '{space}': 'SPACE',
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

      console.log('🎹 SimpleKeyboard created successfully!');
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

      if (containerRef.current && !isInside) {
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
  }, [isKeyboardVisible, hideKeyboard]);

  console.log('🎹 VirtualKeyboard render:', { isKeyboardVisible, inputValue });
  
  return (
    <AnimatePresence>
      {isKeyboardVisible && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 flex items-end justify-center z-50 pointer-events-none"
          style={{ 
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 9999,
            // Keep background transparent so you can still see the page but we can't click things behind easily without dismissing.
            // But we actually DO want to close on outside click. We will let the handleClickOutside handle document clicks.
            backgroundColor: 'transparent'
          }}
        >
          <motion.div
            ref={containerRef}
            initial={{ y: 100, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: 100, opacity: 0 }}
            transition={{ type: "spring", damping: 20, stiffness: 300 }}
            className="bg-hifi-dark border-t border-hifi-accent rounded-t-xl p-3 w-full max-w-3xl pointer-events-auto shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-lg font-semibold text-white">Tastiera Virtuale</h3>
              <div className="flex items-center space-x-2">
                <motion.button
                  onClick={hideKeyboard}
                  className="p-1.5 rounded-lg bg-hifi-light hover:bg-hifi-accent text-white transition-colors"
                  whileTap={{ scale: 0.95 }}
                >
                  <X size={18} />
                </motion.button>
              </div>
            </div>

            {/* Keyboard */}
            <div className="simple-keyboard-container-compact">
              <div ref={keyboardRef} className="simple-keyboard"></div>
            </div>

            {/* Action buttons */}
            <div className="flex gap-2 mt-3">
              <motion.button
                onClick={() => updateInputValue('')}
                className="flex-1 bg-red-600 hover:bg-red-700 text-white py-2 rounded-lg font-semibold text-sm transition-colors"
                whileTap={{ scale: 0.95 }}
              >
                Cancella Tutto
              </motion.button>
              <motion.button
                onClick={confirmInput}
                className="flex-1 bg-hifi-gold hover:bg-yellow-600 text-black py-2 rounded-lg font-semibold text-sm transition-colors"
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