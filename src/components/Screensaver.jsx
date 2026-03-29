import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

const Screensaver = ({ isActive, onWake }) => {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    if (!isActive) return;

    // Update time every second
    const interval = setInterval(() => {
      setTime(new Date());
    }, 1000);

    return () => clearInterval(interval);
  }, [isActive]);

  const formatTime = (date) => {
    return {
      hours: date.getHours().toString().padStart(2, '0'),
      minutes: date.getMinutes().toString().padStart(2, '0'),
      seconds: date.getSeconds().toString().padStart(2, '0'),
      dateStr: date.toLocaleDateString('it-IT', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      })
    };
  };

  const { hours, minutes, seconds, dateStr } = formatTime(time);

  return (
    <AnimatePresence>
      {isActive && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 1 }} // Slow fade in/out
          className="fixed inset-0 z-[100] bg-black flex flex-col items-center justify-center cursor-none"
          onClick={onWake}
        >
          {/* Subtle slow-moving gradient background for avoiding pure black static burn-in */}
          <motion.div
            className="absolute inset-0 opacity-20 bg-gradient-to-br from-hifi-dark via-black to-hifi-gray"
            animate={{
              backgroundPosition: ['0% 0%', '100% 100%', '0% 0%'],
            }}
            transition={{ duration: 30, repeat: Infinity, ease: 'linear' }}
          />

          <div className="relative z-10 flex flex-col items-center select-none">
            {/* Main Clock */}
            <div className="flex items-baseline space-x-4 text-white font-light tracking-wider">
              <span className="text-[12rem] leading-none">{hours}</span>
              <span className="text-[10rem] leading-none opacity-50 mb-8 animate-pulse">:</span>
              <span className="text-[12rem] leading-none">{minutes}</span>
            </div>

            {/* Seconds & Date */}
            <div className="flex flex-col items-center mt-8">
              <span className="text-3xl text-hifi-gold font-mono tracking-[0.2em] opacity-80 mb-4">
                {seconds}
              </span>
              <span className="text-2xl text-hifi-silver/60 uppercase tracking-widest">
                {dateStr}
              </span>
            </div>

            {/* Floating Brand/Logo */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 mt-64 opacity-20 flex items-center space-x-2">
              <div className="w-2 h-2 rounded-full bg-hifi-gold"></div>
              <span className="text-sm tracking-[0.5em] uppercase text-white font-bold">HiFi Player</span>
            </div>
          </div>

          {/* Invisible overlay to catch any interaction */}
          <div className="absolute inset-0" onMouseMove={onWake} onTouchStart={onWake} />
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default Screensaver;