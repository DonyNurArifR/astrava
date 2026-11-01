import React, { useEffect, useState } from 'react';
import { CheckCircle2, AlertTriangle, User, RefreshCw } from 'lucide-react';
import { api } from '../api/client';

interface HeaderProps {
  title: string;
  subtitle?: string;
  onRefresh?: () => void;
  isRefreshing?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  title,
  subtitle,
  onRefresh,
  isRefreshing = false,
}) => {
  const [healthStatus, setHealthStatus] = useState<'healthy' | 'degraded' | 'checking'>('checking');

  useEffect(() => {
    api
      .getHealth()
      .then(res => {
        if (res.status === 'healthy') {
          setHealthStatus('healthy');
        } else {
          setHealthStatus('degraded');
        }
      })
      .catch(() => setHealthStatus('degraded'));
  }, []);

  return (
    <header className="h-16 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-6 flex items-center justify-between transition-colors">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-white leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            {subtitle}
          </p>
        )}
      </div>

      <div className="flex items-center gap-4">
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            className="p-2 text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title="Refresh data"
          >
            <RefreshCw size={16} className={isRefreshing ? 'animate-spin text-blue-500' : ''} />
          </button>
        )}

        {/* System Health Indicator */}
        <div className="flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
          {healthStatus === 'healthy' ? (
            <>
              <CheckCircle2 size={13} className="text-emerald-500" />
              <span className="text-emerald-700 dark:text-emerald-400">System Online</span>
            </>
          ) : healthStatus === 'checking' ? (
            <span className="text-slate-500">Checking...</span>
          ) : (
            <>
              <AlertTriangle size={13} className="text-amber-500" />
              <span className="text-amber-600 dark:text-amber-400">Degraded</span>
            </>
          )}
        </div>

        {/* Operator User */}
        <div className="flex items-center gap-2.5 pl-3 border-l border-slate-200 dark:border-slate-800">
          <div className="w-8 h-8 rounded-full bg-blue-600/10 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex items-center justify-center font-bold text-sm">
            <User size={16} />
          </div>
          <div className="flex flex-col text-left">
            <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">
              Abstract
            </span>
            <span className="text-[10px] text-slate-400 font-mono">DonyNurArifR</span>
          </div>
        </div>
      </div>
    </header>
  );
};
