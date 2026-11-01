import React from 'react';
import {
  LayoutDashboard,
  Terminal,
  FolderKanban,
  PlayCircle,
  FileText,
  ShieldCheck,
  Cpu,
  Settings as SettingsIcon,
  Moon,
  Sun,
  Sparkles,
} from 'lucide-react';
import { Logo } from './Logo';
import { useTheme } from '../context/ThemeContext';

export type NavItemKey =
  | 'overview'
  | 'command-center'
  | 'projects'
  | 'executions'
  | 'artifacts'
  | 'approvals'
  | 'intelligence'
  | 'settings';

interface SidebarProps {
  activeTab: NavItemKey;
  onSelectTab: (tab: NavItemKey) => void;
  pendingApprovalsCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onSelectTab,
  pendingApprovalsCount = 0,
}) => {
  const { theme, toggleTheme } = useTheme();

  const navItems = [
    { key: 'overview', label: 'Overview', icon: LayoutDashboard },
    { key: 'command-center', label: 'Command Center', icon: Terminal, badge: 'Live' },
    { key: 'projects', label: 'Projects', icon: FolderKanban },
    { key: 'executions', label: 'Executions', icon: PlayCircle },
    { key: 'artifacts', label: 'Artifacts', icon: FileText },
    {
      key: 'approvals',
      label: 'Approvals',
      icon: ShieldCheck,
      count: pendingApprovalsCount,
    },
    { key: 'intelligence', label: 'Intelligence', icon: Cpu },
    { key: 'settings', label: 'Settings', icon: SettingsIcon },
  ];

  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-800 text-slate-300 flex flex-col justify-between select-none">
      <div>
        <div className="p-5 border-b border-slate-800">
          <Logo size={36} />
        </div>

        <nav className="p-3 space-y-1">
          {navItems.map(item => {
            const Icon = item.icon;
            const isActive = activeTab === item.key;
            return (
              <button
                key={item.key}
                onClick={() => onSelectTab(item.key as NavItemKey)}
                className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon size={18} className={isActive ? 'text-white' : 'text-slate-400'} />
                  <span>{item.label}</span>
                </div>
                {item.count !== undefined && item.count > 0 && (
                  <span className="px-2 py-0.5 text-xs font-bold rounded-full bg-amber-500 text-slate-950">
                    {item.count}
                  </span>
                )}
                {item.badge && (
                  <span className="px-1.5 py-0.5 text-[10px] uppercase font-bold rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      <div className="p-4 border-t border-slate-800 space-y-3">
        <div className="bg-slate-800/60 rounded-lg p-3 text-xs border border-slate-700/50">
          <div className="flex items-center gap-2 text-slate-200 font-semibold mb-1">
            <Sparkles size={14} className="text-blue-400" />
            <span>Active Executor</span>
          </div>
          <div className="text-slate-400">Claude Haiku 5.5</div>
          <div className="text-[11px] text-emerald-400 font-mono mt-1 flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block animate-pulse"></span>
            CLI Subscription Ready
          </div>
        </div>

        <div className="flex items-center justify-between pt-2">
          <button
            onClick={toggleTheme}
            className="flex items-center gap-2 text-xs text-slate-400 hover:text-white px-2 py-1.5 rounded hover:bg-slate-800 transition-colors"
          >
            {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
            <span>{theme === 'dark' ? 'Light Theme' : 'Dark Theme'}</span>
          </button>
          <span className="text-[11px] font-mono text-slate-500">v1.0.0</span>
        </div>
      </div>
    </aside>
  );
};
