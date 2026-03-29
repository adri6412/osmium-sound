import React, { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';

/**
 * Visual VU Meter component that simulates audio activity based on playback state
 */
const VUMeter = ({ isPlaying, bars = 16, className = "" }) => {
  const [levels, setLevels] = useState(Array(bars).fill(0));
  const animationRef = useRef(null);

  useEffect(() => {
    let timeoutId;
    let isActive = true;

    if (!isPlaying) {
      // Smoothly drop to zero when paused
      let currentLevels = [...levels];
      const dropDown = () => {
        if (!isActive) return;
        let changed = false;
        currentLevels = currentLevels.map(level => {
          const newLevel = Math.max(0, level - 5);
          if (newLevel !== level) changed = true;
          return newLevel;
        });
        setLevels([...currentLevels]);
        if (changed) {
          animationRef.current = requestAnimationFrame(dropDown);
        }
      };
      animationRef.current = requestAnimationFrame(dropDown);
      return () => {
        isActive = false;
        cancelAnimationFrame(animationRef.current);
      };
    }

    // Simulate audio reactivity
    const animate = () => {
      if (!isActive) return;

      setLevels(prev => prev.map(() => {
        // Random value between 10 and 100, biased towards lower numbers for realistic look
        const base = Math.random() * 100;
        return base > 80 ? base : Math.random() * 60 + 10;
      }));
      // Slower update rate for retro feel
      timeoutId = setTimeout(() => {
        if (isActive) {
          animationRef.current = requestAnimationFrame(animate);
        }
      }, 100);
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      isActive = false;
      clearTimeout(timeoutId);
      cancelAnimationFrame(animationRef.current);
    };
  }, [isPlaying, bars]);

  return (
    <div className={`flex items-end justify-between h-16 w-full gap-1 ${className}`}>
      {levels.map((level, i) => {
        // Create a gradient effect for the bars based on height (green -> yellow -> red)
        let bgClass = "bg-hifi-gold";
        if (level > 85) bgClass = "bg-red-500";
        else if (level > 60) bgClass = "bg-yellow-500";

        return (
          <div
            key={i}
            className="flex-1 bg-white/10 rounded-t-sm relative overflow-hidden h-full flex items-end"
          >
            <motion.div
              className={`w-full ${bgClass} rounded-t-sm shadow-[0_0_10px_currentColor]`}
              animate={{ height: `${level}%` }}
              transition={{ type: "tween", duration: 0.1, ease: "linear" }}
            />
          </div>
        );
      })}
    </div>
  );
};

export default VUMeter;