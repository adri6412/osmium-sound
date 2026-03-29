import React, { useState, useEffect } from 'react';
import useWebSocket, { ReadyState } from 'react-use-websocket';
import { motion, useSpring, useTransform, useMotionValue } from 'framer-motion';

const SingleVUMeter = ({ value, label }) => {
  // value is between 0 and 100
  // we want to map this to an angle. Let's say -45 deg to +45 deg

  const motionVal = useMotionValue(value);

  // Create a spring for smooth needle movement
  const springValue = useSpring(motionVal, {
    stiffness: 150,
    damping: 15,
    mass: 0.5,
  });

  useEffect(() => {
    motionVal.set(value);
  }, [value, motionVal]);

  const rotate = useTransform(springValue, [0, 100], [-45, 45]);

  return (
    <div className="relative w-full min-w-[150px] max-w-[450px] h-full aspect-[4/3] bg-[#d9c79e] rounded-sm shadow-inner overflow-hidden flex flex-col items-center justify-end pb-4 border-[6px] border-[#2a2a2a] box-border relative"
         style={{
           backgroundImage: 'radial-gradient(circle at 50% 120%, #fcf5d4 0%, #c2ac74 80%, #a68f56 100%)'
         }}>

      {/* Background shadow/lighting effects to simulate the vintage bulb look */}
      <div className="absolute inset-0 shadow-[inset_0_0_20px_rgba(0,0,0,0.6)] pointer-events-none" />
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[120%] h-[80%] bg-[#fffae6] blur-3xl opacity-40 pointer-events-none" />

      {/* Top Right "Bulb" screw/dot */}
      <div className="absolute top-3 right-3 w-3 h-3 bg-[#111] rounded-full shadow-[inset_-1px_-1px_2px_rgba(255,255,255,0.3),_1px_1px_2px_rgba(0,0,0,0.8)] border border-black/50" />

      {/* VU Text */}
      <div className="absolute top-4 left-5 text-xl font-bold text-[#222] tracking-wider" style={{ fontFamily: 'sans-serif' }}>
        VU
      </div>

      {/* Scale Arc and Ticks */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-[20%] w-[85%] aspect-[2/1] pointer-events-none">
        {/* SVG Arc for the scale */}
        <svg viewBox="0 0 200 100" className="w-full h-full overflow-visible">
          {/* Main Arc Line */}
          <path d="M 10 90 A 100 100 0 0 1 190 90" fill="none" stroke="#222" strokeWidth="1.5" />

          {/* Red portion of the arc (overload) */}
          <path d="M 140 37 A 100 100 0 0 1 190 90" fill="none" stroke="#c0392b" strokeWidth="4" />

          {/* Ticks (Simulated positions) */}
          {/* Black Ticks */}
          {[
            { angle: -45, label: "20" },
            { angle: -30, label: "10" },
            { angle: -15, label: "7" },
            { angle: 0, label: "5" },
            { angle: 10, label: "3" },
            { angle: 20, label: "2" },
            { angle: 30, label: "1" },
            { angle: 40, label: "0" },
          ].map((tick, i) => {
             // Center of rotation is around 100, 150
             const cx = 100;
             const cy = 150;
             const radius = 95;
             const rad = (tick.angle - 90) * (Math.PI / 180);
             const x1 = cx + radius * Math.cos(rad);
             const y1 = cy + radius * Math.sin(rad);
             const x2 = cx + (radius - 8) * Math.cos(rad);
             const y2 = cy + (radius - 8) * Math.sin(rad);
             const tx = cx + (radius - 20) * Math.cos(rad);
             const ty = cy + (radius - 20) * Math.sin(rad);

             return (
               <g key={i}>
                 <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#222" strokeWidth="1.5" />
                 <text x={tx} y={ty} fontSize="10" fill="#222" textAnchor="middle" dominantBaseline="middle" fontWeight="bold" transform={`rotate(${tick.angle}, ${tx}, ${ty})`}>
                    {tick.label}
                 </text>
               </g>
             );
          })}

          {/* Red Ticks */}
           {[
            { angle: 50, label: "1" },
            { angle: 60, label: "2" },
            { angle: 70, label: "3" },
            { angle: 80, label: "+" },
          ].map((tick, i) => {
             const cx = 100;
             const cy = 150;
             const radius = 95;
             const rad = (tick.angle - 90) * (Math.PI / 180);
             const x1 = cx + radius * Math.cos(rad);
             const y1 = cy + radius * Math.sin(rad);
             const x2 = cx + (radius - 8) * Math.cos(rad);
             const y2 = cy + (radius - 8) * Math.sin(rad);
             const tx = cx + (radius - 20) * Math.cos(rad);
             const ty = cy + (radius - 20) * Math.sin(rad);

             return (
               <g key={`red-${i}`}>
                 <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#c0392b" strokeWidth="1.5" />
                 <text x={tx} y={ty} fontSize="10" fill="#c0392b" textAnchor="middle" dominantBaseline="middle" fontWeight="bold" transform={`rotate(${tick.angle}, ${tx}, ${ty})`}>
                    {tick.label}
                 </text>
               </g>
             );
          })}

          {/* Secondary scale line below main arc */}
          <path d="M 18 100 A 90 90 0 0 1 182 100" fill="none" stroke="#222" strokeWidth="0.5" strokeDasharray="3 3" />
          {/* Some small numbers for secondary scale */}
          <text x="50" y="110" fontSize="5" fill="#444">20</text>
          <text x="80" y="105" fontSize="5" fill="#444">40</text>
          <text x="110" y="105" fontSize="5" fill="#444">60</text>
          <text x="140" y="110" fontSize="5" fill="#444">80</text>
          <text x="170" y="120" fontSize="5" fill="#444">100</text>
        </svg>
      </div>

      {/* Logo & Label */}
      <div className="absolute bottom-4 flex flex-col items-center z-10 pointer-events-none">
        <div className="flex space-x-[2px] mb-1">
           {/* Simulate "WAVES" like logo */}
           <div className="w-[3px] h-3 bg-[#222]" style={{ transform: 'skewX(20deg)' }} />
           <div className="w-[3px] h-4 bg-[#222] translate-y-[-2px]" />
           <div className="w-[3px] h-3 bg-[#222]" style={{ transform: 'skewX(-20deg)' }} />
        </div>
        <span className="text-[9px] font-bold text-[#222] tracking-[0.2em] mt-1">WAVES</span>
      </div>

      {/* The Needle */}
      <motion.div
        className="absolute bottom-[-20%] left-1/2 w-[2px] h-[95%] bg-[#111] shadow-[2px_0_5px_rgba(0,0,0,0.5)] z-20"
        style={{
          rotate,
          x: "-50%",
          transformOrigin: "bottom center"
        }}
      />
      {/* Needle Pivot Cap */}
      <div className="absolute bottom-[-20%] left-1/2 w-4 h-4 bg-[#111] rounded-full -translate-x-1/2 translate-y-1/2 z-30 shadow-md" />
    </div>
  );
};

/**
 * Dual Analog VU Meter component replacing the digital bars
 */
const AnalogVUMeter = ({ isPlaying, className = "" }) => {
  const [leftValue, setLeftValue] = useState(0);
  const [rightValue, setRightValue] = useState(0);
  const [socketUrl, setSocketUrl] = useState(`ws://${window.location.hostname}:9001`);

  const { lastMessage, readyState } = useWebSocket(socketUrl, {
    shouldReconnect: () => true,
    reconnectInterval: 3000,
  });

  useEffect(() => {
    const savedApiHost = localStorage.getItem('apiHost');
    if (savedApiHost) {
        try {
            const url = new URL(savedApiHost);
            setSocketUrl(`ws://${url.hostname}:9001`);
        } catch(e) {}
    } else if (window.location.hostname && window.location.hostname !== 'localhost') {
        setSocketUrl(`ws://${window.location.hostname}:9001`);
    } else {
        setSocketUrl('ws://localhost:9001');
    }
  }, []);

  useEffect(() => {
    if (lastMessage !== null) {
      try {
        const data = JSON.parse(lastMessage.data);
        if (data.levels && Array.isArray(data.levels)) {
            // We have an array of 32 bars from the python daemon.
            // Split into left and right channel approx
            const mid = Math.floor(data.levels.length / 2);
            const leftBars = data.levels.slice(0, mid);
            const rightBars = data.levels.slice(mid);

            // Get max or average to drive the needle
            const getPeak = (arr) => {
              if (!arr.length) return 0;
              // Reduce the sensitivity by multiplying by 0.75 so the needle isn't stuck at 100
              const maxVal = Math.max(...arr);
              return maxVal * 0.75;
            };

            setLeftValue(getPeak(leftBars));
            setRightValue(getPeak(rightBars));
        }
      } catch (error) {
        console.error("Error parsing VU meter websocket data:", error);
      }
    }
  }, [lastMessage]);

  // Fallback animation if WS is disconnected but audio is playing
  useEffect(() => {
    let timeoutId;
    let animationFrameId;
    let isActive = true;

    if (readyState !== ReadyState.OPEN) {
        if (!isPlaying) {
          // Drop to 0. We let framer-motion's useSpring handle the smooth drop,
          // so we only need to set the value to 0 once here.
          setLeftValue(0);
          setRightValue(0);
          return;
        }

        // Simulate audio
        const animateFallback = () => {
          if (!isActive) return;

          setLeftValue(() => {
            const base = Math.random() * 100 * 0.75;
            return base > 60 ? base : Math.random() * 40 + 5;
          });
          setRightValue(() => {
            const base = Math.random() * 100 * 0.75;
            return base > 60 ? base : Math.random() * 40 + 5;
          });

          timeoutId = setTimeout(() => {
            if (isActive) animationFrameId = requestAnimationFrame(animateFallback);
          }, 80);
        };

        animationFrameId = requestAnimationFrame(animateFallback);

        return () => {
          isActive = false;
          if (timeoutId) clearTimeout(timeoutId);
          if (animationFrameId) cancelAnimationFrame(animationFrameId);
        };
    }
  }, [isPlaying, readyState]);

  return (
    <div className={`flex items-center justify-center bg-[#111] p-2 md:p-3 rounded-lg shadow-[inset_0_0_10px_rgba(0,0,0,1)] border-2 md:border-4 border-[#1a1a1a] w-full max-w-full ${className}`}>
      <div className="flex w-full h-full justify-center gap-1 md:gap-2">
        <SingleVUMeter value={leftValue} label="L" />
        <div className="w-1 md:w-2 rounded bg-gradient-to-b from-[#222] to-[#111] shadow-inner" /> {/* Separator */}
        <SingleVUMeter value={rightValue} label="R" />
      </div>
    </div>
  );
};

export default AnalogVUMeter;