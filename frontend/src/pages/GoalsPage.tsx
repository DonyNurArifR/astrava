import React, { useState, useEffect, useCallback } from 'react';
import {
  Target,
  Plus,
  Play,
  CheckCircle2,
  Clock,
  PauseCircle,
  XCircle,
  FolderKanban,
  RotateCw,
  X,
  ListChecks,
} from 'lucide-react';
import { api } from '../api/client';
import type { Project, ProjectGoal, GoalStatus } from '../types/api';

export const GoalsPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [goals, setGoals] = useState<ProjectGoal[]>([]);
  const [statusFilter, setStatusFilter] = useState<GoalStatus | 'all'>('all');
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Create Goal Modal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newCriteriaText, setNewCriteriaText] = useState('');
  const [creating, setCreating] = useState(false);

  // Execution tracking
  const [executingGoalId, setExecutingGoalId] = useState<string | null>(null);
  const [executionSuccessMsg, setExecutionSuccessMsg] = useState<string | null>(null);

  // Load projects
  useEffect(() => {
    api
      .getProjects()
      .then(projs => {
        setProjects(projs);
        if (projs.length > 0 && !selectedProjectId) {
          setSelectedProjectId(projs[0].id);
        }
      })
      .catch((err: any) => setError(err.message || 'Failed to load projects'));
  }, []);

  // Load goals for selected project
  const loadGoals = useCallback(async () => {
    if (!selectedProjectId) {
      setGoals([]);
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const filter = statusFilter === 'all' ? undefined : statusFilter;
      const data = await api.getProjectGoals(selectedProjectId, filter);
      setGoals(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load project goals');
    } finally {
      setLoading(false);
    }
  }, [selectedProjectId, statusFilter]);

  useEffect(() => {
    loadGoals();
  }, [loadGoals]);

  const handleCreateGoal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProjectId || !newTitle.trim()) return;

    try {
      setCreating(true);
      const criteria = newCriteriaText
        .split('\n')
        .map(c => c.trim())
        .filter(Boolean);

      const created = await api.createProjectGoal(selectedProjectId, {
        title: newTitle.trim(),
        description: newDescription.trim(),
        target_criteria: criteria,
      });

      setGoals(prev => [created, ...prev]);
      setIsModalOpen(false);
      setNewTitle('');
      setNewDescription('');
      setNewCriteriaText('');
    } catch (err: any) {
      alert(`Failed to create goal: ${err.message}`);
    } finally {
      setCreating(false);
    }
  };

  const handleExecuteGoal = async (goal: ProjectGoal) => {
    try {
      setExecutingGoalId(goal.id);
      setExecutionSuccessMsg(null);
      const execution = await api.executeGoal(goal.project_id, goal.id);
      setExecutionSuccessMsg(`Autonomous pipeline started for goal '${goal.title}' (Execution #${execution.id.slice(0, 8)})`);
      setTimeout(() => setExecutionSuccessMsg(null), 8000);
    } catch (err: any) {
      alert(`Failed to trigger goal execution: ${err.message}`);
    } finally {
      setExecutingGoalId(null);
    }
  };

  const getStatusBadge = (status: GoalStatus) => {
    switch (status) {
      case 'achieved':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
            <CheckCircle2 size={13} /> Achieved
          </span>
        );
      case 'active':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
            <Clock size={13} /> Active
          </span>
        );
      case 'paused':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
            <PauseCircle size={13} /> Paused
          </span>
        );
      case 'cancelled':
        return (
          <span className="flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-red-50 text-red-700 dark:bg-red-950/60 dark:text-red-300 border border-red-200 dark:border-red-800">
            <XCircle size={13} /> Cancelled
          </span>
        );
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Top Header & Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400 border border-blue-100 dark:border-blue-900/40">
            <Target size={24} />
          </div>
          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">Project Goals & Outcomes</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              High-level strategic objectives dynamically decomposed into adaptive execution graphs
            </p>
          </div>
        </div>

        <button
          onClick={() => setIsModalOpen(true)}
          disabled={!selectedProjectId}
          className="flex items-center justify-center gap-2 px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-500 rounded-xl transition-colors shadow-xs disabled:opacity-50"
        >
          <Plus size={16} /> New Goal
        </button>
      </div>

      {executionSuccessMsg && (
        <div className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300 text-sm flex items-center justify-between">
          <span className="flex items-center gap-2">
            <CheckCircle2 size={16} /> {executionSuccessMsg}
          </span>
          <button onClick={() => setExecutionSuccessMsg(null)} className="text-slate-400 hover:text-slate-600">
            <X size={16} />
          </button>
        </div>
      )}

      {/* Controls Bar: Project Selector & Status Filter */}
      <div className="p-4 rounded-xl bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/70 shadow-xs flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="flex items-center gap-3 w-full sm:w-auto">
          <label className="text-xs font-medium text-slate-500 dark:text-slate-400 flex items-center gap-1.5 whitespace-nowrap">
            <FolderKanban size={14} /> Project:
          </label>
          <select
            value={selectedProjectId}
            onChange={e => setSelectedProjectId(e.target.value)}
            className="w-full sm:w-64 px-3 py-1.5 text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-blue-500"
          >
            {projects.map(p => (
              <option key={p.id} value={p.id}>
                {p.name} {p.studio_type ? `(${p.studio_type.toUpperCase()})` : ''}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-1 w-full sm:w-auto justify-end overflow-x-auto">
          {(['all', 'active', 'achieved', 'paused', 'cancelled'] as const).map(status => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`px-3 py-1 text-xs font-semibold rounded-lg capitalize transition-colors ${
                statusFilter === status
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700/60'
              }`}
            >
              {status}
            </button>
          ))}
        </div>
      </div>

      {/* Goals Content */}
      {loading ? (
        <div className="text-center py-16 text-slate-400">
          <RotateCw className="animate-spin mx-auto mb-2" size={24} />
          Loading project goals...
        </div>
      ) : error ? (
        <div className="p-4 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 text-sm">
          {error}
        </div>
      ) : goals.length === 0 ? (
        <div className="text-center py-16 text-slate-400 border border-dashed border-slate-200 dark:border-slate-700 rounded-xl">
          <Target className="mx-auto mb-2 opacity-40" size={32} />
          <p className="text-sm font-medium">No goals registered for this project.</p>
          <p className="text-xs text-slate-500 mt-1">Create a high-level goal to trigger adaptive autonomous execution.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {goals.map(goal => (
            <div
              key={goal.id}
              className="p-5 rounded-xl bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/70 shadow-xs flex flex-col justify-between hover:border-slate-300 dark:hover:border-slate-600 transition-all"
            >
              <div>
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-base font-bold text-slate-900 dark:text-white leading-tight">
                    {goal.title}
                  </h3>
                  {getStatusBadge(goal.status)}
                </div>

                <p className="text-xs text-slate-600 dark:text-slate-300 mt-2 line-clamp-2">
                  {goal.description || 'No description provided.'}
                </p>

                {/* Progress Bar */}
                <div className="mt-4">
                  <div className="flex items-center justify-between text-xs font-mono mb-1 text-slate-500 dark:text-slate-400">
                    <span>Progress</span>
                    <span className="font-bold text-slate-700 dark:text-slate-200">{goal.progress_percentage.toFixed(0)}%</span>
                  </div>
                  <div className="w-full h-2 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
                    <div
                      className={`h-full transition-all duration-500 ${
                        goal.status === 'achieved' ? 'bg-blue-500' : 'bg-emerald-500'
                      }`}
                      style={{ width: `${Math.min(100, Math.max(0, goal.progress_percentage))}%` }}
                    />
                  </div>
                </div>

                {/* Target Criteria */}
                {goal.target_criteria && goal.target_criteria.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-700/60">
                    <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1.5 flex items-center gap-1">
                      <ListChecks size={12} /> Target Acceptance Criteria:
                    </span>
                    <ul className="space-y-1">
                      {goal.target_criteria.map((crit, idx) => (
                        <li key={idx} className="text-xs text-slate-600 dark:text-slate-300 flex items-start gap-1.5">
                          <span className="text-blue-500">•</span>
                          <span>{crit}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Action: Trigger Execution */}
              <div className="mt-5 pt-3 border-t border-slate-100 dark:border-slate-700/60 flex items-center justify-between">
                <span className="text-[11px] font-mono text-slate-400">
                  ID: {goal.id.slice(0, 8)}
                </span>
                <button
                  onClick={() => handleExecuteGoal(goal)}
                  disabled={executingGoalId === goal.id || goal.status === 'cancelled'}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors shadow-xs disabled:opacity-50"
                >
                  <Play size={13} />
                  {executingGoalId === goal.id ? 'Starting...' : 'Execute Goal'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Goal Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-xl border border-slate-200 dark:border-slate-700">
            <div className="flex items-center justify-between pb-4 border-b border-slate-100 dark:border-slate-700/60">
              <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <Target size={20} className="text-blue-500" />
                Define New Project Goal
              </h2>
              <button onClick={() => setIsModalOpen(false)} className="text-slate-400 hover:text-slate-600">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateGoal} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Goal Title *
                </label>
                <input
                  type="text"
                  required
                  value={newTitle}
                  onChange={e => setNewTitle(e.target.value)}
                  placeholder="e.g. Build Real-Time SSE Notification Pipeline"
                  className="w-full px-3 py-2 text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-hidden focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Description
                </label>
                <textarea
                  rows={3}
                  value={newDescription}
                  onChange={e => setNewDescription(e.target.value)}
                  placeholder="Describe the desired outcome, target architecture, or deliverable requirements..."
                  className="w-full px-3 py-2 text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-hidden focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Target Acceptance Criteria (one per line)
                </label>
                <textarea
                  rows={4}
                  value={newCriteriaText}
                  onChange={e => setNewCriteriaText(e.target.value)}
                  placeholder={"Database schema migration verified\nSSE client reconnect logic implemented\nPassing unit and regression test suite"}
                  className="w-full px-3 py-2 text-xs font-mono bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-hidden focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-4 border-t border-slate-100 dark:border-slate-700/60">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 text-sm font-semibold text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-xl transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating || !newTitle.trim()}
                  className="px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-500 rounded-xl transition-colors shadow-xs disabled:opacity-50"
                >
                  {creating ? 'Creating...' : 'Create Goal'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
