import React, { useState, useEffect } from 'react';
import useWebSocket, { ReadyState } from 'react-use-websocket';
import { motion } from 'framer-motion';

/**
 * Visual VU Meter component that connects to the local Python WebSocket daemon
 * to display real-time PCM audio levels from Squeezelite.
 */
const VUMeter = ({ isPlaying, bars = 32, className = "" }) => {
  const [levels, setLevels] = useState(Array(bars).fill(0));
  const [socketUrl, setSocketUrl] = useState(`ws://${window.location.hostname}:9001`);

  const { lastMessage, readyState } = useWebSocket(socketUrl, {
    shouldReconnect: (closeEvent) => true,
    reconnectInterval: 3000,
  });

  useEffect(() => {
    // Determine the IP address of the local API server if we are not running on localhost
    // In production (Electron), window.location.hostname is often empty or "localhost"
    // so we might need to parse an API URL from local storage if available.
    const savedApiHost = localStorage.getItem('apiHost');
    if (savedApiHost) {
        try {
            const url = new URL(savedApiHost);
            setSocketUrl(`ws://${url.hostname}:9001`);
        } catch(e) {}
    } else if (window.location.hostname && window.location.hostname !== 'localhost') {
        setSocketUrl(`ws://${window.location.hostname}:9001`);
    } else {
        setSocketUrl('ws://localhost:9001'); // Default fallback for dev
    }
  }, []);

  useEffect(() => {
    if (lastMessage !== null) {
      try {
        const data = JSON.parse(lastMessage.data);
        if (data.levels && Array.isArray(data.levels)) {
            // Resize array if necessary
            let newLevels = data.levels;
            if (newLevels.length > bars) {
                newLevels = newLevels.slice(0, bars);
            } else if (newLevels.length < bars) {
                newLevels = [...newLevels, ...Array(bars - newLevels.length).fill(0)];
            }
            setLevels(newLevels);
        }
      } catch (error) {
        console.error("Error parsing VU meter websocket data:", error);
      }
    }
  }, [lastMessage, bars]);

  // Fallback animation logic if WebSocket is disconnected but track is playing
  // (e.g. playing Spotify or YouTube instead of local Lyrion/Squeezelite)
  useEffect(() => {
    let timeoutId;
    let animationFrameId;
    let isActive = true;

    if (readyState !== ReadyState.OPEN) {
        if (!isPlaying) {
          // Smoothly drop to zero when paused (fallback)
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
              animationFrameId = requestAnimationFrame(dropDown);
            }
          };
          animationFrameId = requestAnimationFrame(dropDown);
          return () => {
            isActive = false;
            cancelAnimationFrame(animationFrameId);
          };
        }

        // Simulate audio reactivity (fallback)
        const animateFallback = () => {
          if (!isActive) return;

          setLevels(prev => prev.map(() => {
            const base = Math.random() * 100;
            return base > 80 ? base : Math.random() * 60 + 10;
          }));

          timeoutId = setTimeout(() => {
            if (isActive) {
              animationFrameId = requestAnimationFrame(animateFallback);
            }
          }, 100);
        };

        animationFrameId = requestAnimationFrame(animateFallback);

        return () => {
          isActive = false;
          clearTimeout(timeoutId);
          cancelAnimationFrame(animationFrameId);
        };
    }
  }, [isPlaying, readyState, levels, bars]);

  return (
    <div className={`flex items-end justify-between h-16 w-full gap-[2px] ${className}`}>
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
              transition={{ type: "tween", duration: 0.05, ease: "linear" }}
            />
          </div>
        );
      })}
    </div>
  );
};

export default VUMeter;