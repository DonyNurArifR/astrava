import React from 'react';

interface LogoProps {
  className?: string;
  size?: number;
  showText?: boolean;
}

export const Logo: React.FC<LogoProps> = ({ className = '', size = 32, showText = true }) => {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="shrink-0 transition-transform hover:scale-105 duration-200"
      >
        <defs>
          <linearGradient id="astravaGrad" x1="10" y1="90" x2="90" y2="10" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#1E3A8A" />
            <stop offset="50%" stopColor="#2563EB" />
            <stop offset="100%" stopColor="#38BDF8" />
          </linearGradient>
          <linearGradient id="beamGrad" x1="30" y1="65" x2="70" y2="65" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#38BDF8" />
            <stop offset="100%" stopColor="#60A5FA" />
          </linearGradient>
        </defs>
        {/* Left ascending architectural strut */}
        <polygon points="50,12 36,12 12,88 28,88 44,38" fill="url(#astravaGrad)" />
        {/* Right descending structural strut */}
        <polygon points="50,12 64,12 88,88 72,88 56,38" fill="url(#astravaGrad)" fillOpacity="0.9" />
        {/* Geometric crossbeam symbolizing orchestration & bridge */}
        <polygon points="30,60 70,60 66,70 34,70" fill="url(#beamGrad)" />
        {/* Central intelligence apex prism */}
        <polygon points="50,22 43,40 57,40" fill="#FFFFFF" fillOpacity="0.95" />
      </svg>
      {showText && (
        <div className="flex flex-col">
          <span className="font-extrabold tracking-wider text-lg leading-tight text-slate-900 dark:text-white font-sans">
            ASTRAVA
          </span>
          <span className="text-[10px] tracking-widest uppercase font-medium text-blue-600 dark:text-blue-400">
            Enterprise Orchestrator
          </span>
        </div>
      )}
    </div>
  );
};
