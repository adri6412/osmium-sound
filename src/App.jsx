import React, { useState } from 'react';
import { AnimatePresence } from 'framer-motion';

// Import pages
import Home from './pages/Home';
import Settings from './pages/Settings';
import YouTube from './pages/YouTube';
import Spotify from './pages/Spotify';
import LyrionServer from './pages/LyrionServer';

// Import components
import NavigationBar from './components/NavigationBar';
import VirtualKeyboard from './components/VirtualKeyboard';

// Import contexts
import { KeyboardProvider, useKeyboard } from './contexts/KeyboardContext';

// Main app component with simple state-based navigation
const AppContent = () => {
  const [currentPage, setCurrentPage] = useState('home');
  const { showKeyboard } = useKeyboard();

  React.useEffect(() => {
    const handleFocus = (e) => {
      const target = e.target;
      if (
        (target.tagName === 'INPUT' && (target.type === 'text' || target.type === 'password' || target.type === 'email' || target.type === 'number' || target.type === 'search' || target.type === 'tel' || target.type === 'url')) ||
        target.tagName === 'TEXTAREA'
      ) {
        // Store original state before making it readonly
        if (!target.hasAttribute('data-original-readonly')) {
          target.setAttribute('data-original-readonly', target.readOnly ? 'true' : 'false');
        }

        // Prevent default mobile keyboard
        if (!target.readOnly) {
          target.readOnly = true;
        }

        const inputRef = { current: target };
        showKeyboard(inputRef, target.value || '');
      }
    };

    const handleClick = (e) => {
      const target = e.target;
      if (
        (target.tagName === 'INPUT' && (target.type === 'text' || target.type === 'password' || target.type === 'email' || target.type === 'number' || target.type === 'search' || target.type === 'tel' || target.type === 'url')) ||
        target.tagName === 'TEXTAREA'
      ) {
        const inputRef = { current: target };
        showKeyboard(inputRef, target.value || '');
      }
    };

    const handleFocusOut = (e) => {
      const target = e.target;
      if (
        (target.tagName === 'INPUT' && (target.type === 'text' || target.type === 'password' || target.type === 'email' || target.type === 'number' || target.type === 'search' || target.type === 'tel' || target.type === 'url')) ||
        target.tagName === 'TEXTAREA'
      ) {
        // Restore original readonly state
        if (target.hasAttribute('data-original-readonly')) {
          const original = target.getAttribute('data-original-readonly') === 'true';
          target.readOnly = original;
          target.removeAttribute('data-original-readonly');
        }
      }
    };

    // Use capturing phase to ensure we catch events before they are stopped
    document.addEventListener('focusin', handleFocus, true);
    document.addEventListener('focusout', handleFocusOut, true);
    document.addEventListener('click', handleClick, true);

    return () => {
      document.removeEventListener('focusin', handleFocus, true);
      document.removeEventListener('focusout', handleFocusOut, true);
      document.removeEventListener('click', handleClick, true);
    };
  }, [showKeyboard]);

  const renderPage = () => {
    switch (currentPage) {
      case 'home':
        return <Home onNavigate={setCurrentPage} />;
      case 'settings':
        return <Settings />;
      case 'youtube':
        return <YouTube />;
      case 'spotify':
        return <Spotify />;
      case 'lyrion':
        return <LyrionServer />;
      default:
        return <Home onNavigate={setCurrentPage} />;
    }
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-hifi-dark overflow-hidden">
      <NavigationBar onNavigate={setCurrentPage} currentPage={currentPage} />
      
      <main className="flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {renderPage()}
        </AnimatePresence>
      </main>

    </div>
  );
};

function App() {
  return (
    <KeyboardProvider>
      <AppContent />
      <VirtualKeyboard />
    </KeyboardProvider>
  );
}

export default App;

