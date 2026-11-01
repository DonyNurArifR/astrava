import React, { useEffect, useState } from 'react';
import {
  FolderKanban,
  PlayCircle,
  FileText,
  ShieldAlert,
  ArrowRight,
  TrendingUp,
  Terminal,
  Clock,
} from 'lucide-react';
import { api } from '../api/client';
import type { Approval, Execution, Project, ProjectStats, UsageSummary } from '../types/api';

interface OverviewPageProps {
  onNavigate: (tab: any) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({ onNavigate }) => {
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [recentProjects, setRecentProjects] = useState<Project[]>([]);
  const [recentExecutions, setRecentExecutions] = useState<Execution[]>([]);
  const [pendingApprovals, setPendingApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getProjectStats().catch(() => null),
      api.getUsageSummary().catch(() => null),
      api.getProjects().catch(() => []),
      api.getExecutions().catch(() => []),
      api.getApprovals(true).catch(() => []),
    ]).then(([statsRes, usageRes, projectsRes, execsRes, apprRes]) => {
      setStats(statsRes);
      setUsage(usageRes);
      setRecentProjects(projectsRes.slice(0, 5));
      setRecentExecutions(execsRes.slice(0, 5));
      setPendingApprovals(apprRes);
      setLoading(false);
    });
  }, []);

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3 text-slate-400">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
          <p className="text-sm">Loading ASTRAVA platform intelligence...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Hero Banner */}
      <div className="bg-gradient-to-r from-slate-900 via-slate-800 to-blue-950 rounded-2xl p-6 text-white border border-slate-800 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
        <div>
          <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-500/20 text-blue-300 border border-blue-500/30">
            ASTRAVA Enterprise
          </span>
          <h2 className="text-2xl font-bold mt-2 tracking-tight">From vision to execution.</h2>
          <p className="text-sm text-slate-300 mt-1 max-w-xl">
            Autonomous creation and orchestration engine. Direct objectives to functioning SaaS
            products and high-impact media assets with continuous verification.
          </p>
        </div>
        <button
          onClick={() => onNavigate('command-center')}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm shrink-0"
        >
          <Terminal size={16} />
          <span>Launch Command Center</span>
          <ArrowRight size={14} />
        </button>
      </div>

      {/* Pending Approvals Banner if any */}
      {pendingApprovals.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldAlert className="text-amber-500 shrink-0" size={20} />
            <div>
              <p className="text-sm font-semibold text-amber-800 dark:text-amber-200">
                {pendingApprovals.length} Action{pendingApprovals.length > 1 ? 's' : ''} Awaiting Human Approval
              </p>
              <p className="text-xs text-amber-700/80 dark:text-amber-300/80">
                Orchestration pipeline paused at a high-risk operational boundary.
              </p>
            </div>
          </div>
          <button
            onClick={() => onNavigate('approvals')}
            className="px-3.5 py-1.5 bg-amber-500 text-slate-950 rounded-lg text-xs font-bold hover:bg-amber-400 transition-colors"
          >
            Review Requests
          </button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Active Projects</span>
            <FolderKanban size={18} className="text-blue-500" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {stats?.active_projects ?? 0}
            </span>
            <span className="text-xs text-slate-400">/ {stats?.total_projects ?? 0} total</span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Executions Run</span>
            <PlayCircle size={18} className="text-indigo-500" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {stats?.total_executions ?? 0}
            </span>
            <span className="text-xs text-emerald-500 font-semibold flex items-center gap-0.5">
              <TrendingUp size={12} /> {usage?.successful_executions ?? 0} ok
            </span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Generated Artifacts</span>
            <FileText size={18} className="text-emerald-500" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {stats?.total_artifacts ?? 0}
            </span>
            <span className="text-xs text-slate-400">registered files</span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Model Usage Cost</span>
            <span className="text-xs font-mono font-bold text-blue-500">Haiku 5.5</span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              ${usage ? usage.total_cost_usd.toFixed(4) : '0.0000'}
            </span>
            <span className="text-xs text-slate-400 font-mono">
              {(usage?.total_tokens ?? 0).toLocaleString()} tok
            </span>
          </div>
        </div>
      </div>

      {/* Two Column Layout: Recent Projects & Recent Executions */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Projects */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-900 dark:text-white text-base">Production Projects</h3>
            <button
              onClick={() => onNavigate('projects')}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline font-semibold flex items-center gap-1"
            >
              <span>View all</span>
              <ArrowRight size={12} />
            </button>
          </div>

          {recentProjects.length === 0 ? (
            <div className="p-8 text-center text-slate-400 text-sm">
              No projects created yet. Launch the Command Center to start your first production project.
            </div>
          ) : (
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {recentProjects.map(p => (
                <div key={p.id} className="py-3.5 flex items-center justify-between">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm text-slate-900 dark:text-white">
                        {p.name}
                      </span>
                      <span className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded ${
                        p.studio_type === 'saas'
                          ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
                          : 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300'
                      }`}>
                        {p.studio_type}
                      </span>
                    </div>
                    {p.description && (
                      <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-1">
                        {p.description}
                      </p>
                    )}
                  </div>
                  <span className="text-xs font-medium text-emerald-600 dark:text-emerald-400 capitalize">
                    {p.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Executions */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-slate-900 dark:text-white text-base">Pipeline Executions</h3>
            <button
              onClick={() => onNavigate('executions')}
              className="text-xs text-blue-600 dark:text-blue-400 hover:underline font-semibold flex items-center gap-1"
            >
              <span>View all</span>
              <ArrowRight size={12} />
            </button>
          </div>

          {recentExecutions.length === 0 ? (
            <div className="p-8 text-center text-slate-400 text-sm">
              No executions logged yet. Run a workflow from the Command Center.
            </div>
          ) : (
            <div className="divide-y divide-slate-100 dark:divide-slate-800">
              {recentExecutions.map(e => (
                <div key={e.id} className="py-3 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs text-slate-700 dark:text-slate-300">
                        {e.id.slice(0, 8)}
                      </span>
                      <span className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded ${
                        e.status === 'completed'
                          ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                          : e.status === 'waiting_approval'
                          ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300'
                          : 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                      }`}>
                        {e.status}
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 flex items-center gap-1">
                      <Clock size={11} /> {new Date(e.created_at).toLocaleTimeString()}
                    </span>
                  </div>
                  <span className="text-xs text-slate-500 font-mono">
                    {e.events ? `${e.events.length} events` : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
