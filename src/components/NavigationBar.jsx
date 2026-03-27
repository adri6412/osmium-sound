import React, { useState } from 'react';
import { Home, Settings as SettingsIcon, Keyboard, X } from 'lucide-react';
import { motion } from 'framer-motion';

/**
 * Navigation bar component
 * Provides quick access to Home and Settings
 */
const NavigationBar = ({ onNavigate, currentPage }) => {
  const [isGlobalKeyboardVisible, setIsGlobalKeyboardVisible] = useState(false);
  
  const navItems = [
    { key: 'home', icon: Home, label: 'Home' },
    { key: 'settings', icon: SettingsIcon, label: 'Settings' },
  ];

  const handleGlobalKeyboardToggle = async () => {
    try {
      if (isGlobalKeyboardVisible) {
        console.log('Nascondendo tastiera virtuale di sistema...');
        if (window.electronAPI && window.electronAPI.hideGlobalKeyboard) {
          const result = await window.electronAPI.hideGlobalKeyboard();
          if (result.success) {
            setIsGlobalKeyboardVisible(false);
          } else {
            console.error('Errore:', result.message);
            // Fallback: toggle state anyway in case it was hidden externally
            setIsGlobalKeyboardVisible(false);
          }
        } else {
          setIsGlobalKeyboardVisible(false);
        }
      } else {
        console.log('Aprendo tastiera virtuale di sistema...');
        if (window.electronAPI && window.electronAPI.showGlobalKeyboard) {
          const result = await window.electronAPI.showGlobalKeyboard();
          if (result.success) {
            setIsGlobalKeyboardVisible(true);
          } else {
            console.error('Errore:', result.message);
            // Alert user that no system keyboard was found
            alert("Nessuna tastiera virtuale di sistema trovata. Assicurati di aver installato 'onboard' o 'florence'.");
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
    <nav className="bg-gradient-to-b from-hifi-gray to-hifi-dark border-b border-hifi-accent px-6 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <div className="w-3 h-3 rounded-full bg-hifi-gold shadow-lg shadow-hifi-gold/50"></div>
          <h1 className="text-xl font-bold text-hifi-gold tracking-wide">HiFi Player</h1>
        </div>
        
        <div className="flex space-x-2">
          {/* Global Keyboard Toggle */}
          <motion.button
            onClick={handleGlobalKeyboardToggle}
            className={`
              relative p-3 rounded-lg transition-all duration-200
              ${isGlobalKeyboardVisible 
                ? 'bg-green-600 text-white shadow-lg shadow-green-600/30' 
                : 'bg-hifi-light text-hifi-silver hover:bg-hifi-accent'
              }
            `}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            title={isGlobalKeyboardVisible ? 'Nascondi Tastiera Globale' : 'Mostra Tastiera Globale'}
          >
            {isGlobalKeyboardVisible ? <X size={24} /> : <Keyboard size={24} />}
          </motion.button>

          {/* Navigation Items */}
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentPage === item.key;
            
            return (
              <motion.button
                key={item.key}
                onClick={() => onNavigate(item.key)}
                className={`
                  relative p-3 rounded-lg transition-all duration-200
                  ${isActive 
                    ? 'bg-hifi-gold text-black shadow-lg shadow-hifi-gold/30' 
                    : 'bg-hifi-light text-hifi-silver hover:bg-hifi-accent'
                  }
                `}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                <Icon size={24} />
                {isActive && (
                  <motion.div
                    layoutId="activeTab"
                    className="absolute inset-0 bg-hifi-gold rounded-lg -z-10"
                    transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  />
                )}
              </motion.button>
            );
          })}
        </div>
      </div>
    </nav>
  );
};

export default NavigationBar;