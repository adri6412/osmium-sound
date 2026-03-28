import React, { useState } from 'react';
import { Settings as SettingsIcon, Keyboard, X, Menu, Server, Youtube, Disc3 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

/**
 * Sidebar component
 * Replaces NavigationBar and Home grid for a more integrated experience.
 */
const Sidebar = ({ onNavigate, currentPage, isOpen, setIsOpen }) => {
  const [isGlobalKeyboardVisible, setIsGlobalKeyboardVisible] = useState(false);

  const navItems = [
    { key: 'lyrion', icon: Server, label: 'Libreria Locale' },
    { key: 'spotify', icon: Disc3, label: 'Spotify' },
    { key: 'youtube', icon: Youtube, label: 'YouTube' },
    { key: 'settings', icon: SettingsIcon, label: 'Impostazioni' },
  ];

  const handleGlobalKeyboardToggle = async () => {
    try {
      if (isGlobalKeyboardVisible) {
        if (window.electronAPI && window.electronAPI.hideGlobalKeyboard) {
          const result = await window.electronAPI.hideGlobalKeyboard();
          if (result.success) {
            setIsGlobalKeyboardVisible(false);
          }
        } else {
          setIsGlobalKeyboardVisible(false);
        }
      } else {
        if (window.electronAPI && window.electronAPI.showGlobalKeyboard) {
          const result = await window.electronAPI.showGlobalKeyboard();
          if (result.success) {
            setIsGlobalKeyboardVisible(true);
          }
        } else {
          setIsGlobalKeyboardVisible(true);
        }
      }
    } catch (error) {
      console.error('Errore nel controllo della tastiera globale:', error);
    }
  };

  return (
    <>
      {/* Backdrop */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsOpen(false)}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
          />
        )}
      </AnimatePresence>

      {/* Sidebar Drawer */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed top-0 left-0 bottom-0 w-80 bg-hifi-dark border-r border-hifi-accent shadow-2xl z-50 flex flex-col"
          >
            {/* Header */}
            <div className="p-6 border-b border-white/10 flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="w-4 h-4 rounded-full bg-hifi-gold shadow-lg shadow-hifi-gold/50"></div>
                <h1 className="text-2xl font-bold text-hifi-gold tracking-wide">HiFi Player</h1>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="p-2 text-hifi-silver hover:text-white rounded-lg hover:bg-white/10 transition-colors"
              >
                <X size={24} />
              </button>
            </div>

            {/* Nav Links */}
            <div className="flex-1 overflow-y-auto py-6 px-4 space-y-2">
              {navItems.map((item) => {
                const Icon = item.icon;
                const isActive = currentPage === item.key;

                return (
                  <button
                    key={item.key}
                    onClick={() => {
                      onNavigate(item.key);
                      setIsOpen(false);
                    }}
                    className={`
                      w-full flex items-center space-x-4 px-4 py-4 rounded-xl transition-all duration-200
                      ${isActive
                        ? 'bg-hifi-gold text-black font-semibold shadow-lg shadow-hifi-gold/20'
                        : 'text-hifi-silver hover:bg-hifi-light hover:text-white'
                      }
                    `}
                  >
                    <Icon size={24} />
                    <span className="text-lg">{item.label}</span>
                  </button>
                );
              })}
            </div>

            {/* Footer / Utilities */}
            <div className="p-6 border-t border-white/10">
               <button
                  onClick={handleGlobalKeyboardToggle}
                  className={`
                    w-full flex items-center justify-center space-x-3 px-4 py-3 rounded-xl transition-all duration-200
                    ${isGlobalKeyboardVisible
                      ? 'bg-green-600/20 text-green-500 border border-green-500/50'
                      : 'bg-white/5 text-hifi-silver hover:bg-white/10 hover:text-white'
                    }
                  `}
                >
                  {isGlobalKeyboardVisible ? <X size={20} /> : <Keyboard size={20} />}
                  <span>{isGlobalKeyboardVisible ? 'Nascondi Tastiera' : 'Tastiera di Sistema'}</span>
                </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Global Hamburger Button (when sidebar is closed) */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className="fixed top-4 left-4 z-30 p-3 bg-hifi-dark/80 backdrop-blur-md border border-white/10 rounded-full text-white shadow-lg hover:bg-hifi-light transition-colors"
        >
          <Menu size={24} />
        </button>
      )}
    </>
  );
};

export default Sidebar;