import React, { useCallback, useEffect, useState } from 'react';
import {
  Terminal,
  Sparkles,
  Play,
  CheckCircle,
  Code2,
  Video,
  FileCheck,
} from 'lucide-react';
import { api } from '../api/client';
import type { Execution, Project, StructuredPlan, StudioType } from '../types/api';

export const CommandCenterPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [studioType, setStudioType] = useState<StudioType>('saas');
  const [objective, setObjective] = useState('');
  const [isGeneratingPlan, setIsGeneratingPlan] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [plan, setPlan] = useState<StructuredPlan | null>(null);
  const [activeExecution, setActiveExecution] = useState<Execution | null>(null);
  const [error, setError] = useState<string | null>(null);

  // New Project modal state
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');

  const loadProjects = useCallback(() => {
    api.getProjects().then(data => {
      setProjects(data);
      setSelectedProjectId(prev => (prev || (data.length > 0 ? data[0].id : '')));
    }).catch(err => setError(err.message));
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    try {
      const proj = await api.createProject({
        name: newProjectName.trim(),
        studio_type: studioType,
      });
      setNewProjectName('');
      setShowNewProjectModal(false);
      await loadProjects();
      setSelectedProjectId(proj.id);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleGeneratePlan = async () => {
    if (!objective.trim() || !selectedProjectId) return;
    setIsGeneratingPlan(true);
    setError(null);
    try {
      const generated = await api.generatePlan(selectedProjectId, objective, studioType);
      setPlan(generated);
      setActiveExecution(null);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsGeneratingPlan(false);
    }
  };

  const handleExecutePlan = async () => {
    if (!selectedProjectId || !objective.trim()) return;
    setIsExecuting(true);
    setError(null);
    try {
      const exec = await api.executePipeline(selectedProjectId, objective, studioType);
      setActiveExecution(exec);
      // Poll execution status
      pollExecution(exec.id);
    } catch (err: any) {
      setError(err.message);
      setIsExecuting(false);
    }
  };

  const pollExecution = (execId: string) => {
    const interval = setInterval(async () => {
      try {
        const updated = await api.getExecution(execId);
        setActiveExecution(updated);
        if (updated.status === 'completed' || updated.status === 'failed' || updated.status === 'waiting_approval') {
          clearInterval(interval);
          setIsExecuting(false);
        }
      } catch {
        clearInterval(interval);
        setIsExecuting(false);
      }
    }, 2000);
  };

  const handleApproveFromCommand = async (decision: 'approved' | 'rejected') => {
    if (!activeExecution) return;
    setIsExecuting(true);
    try {
      const resumed = await api.resumePipeline(activeExecution.id, decision, 'Operator confirmed in Command Center');
      setActiveExecution(resumed);
      if (resumed.status === 'waiting_approval' || resumed.status === 'running') {
        pollExecution(resumed.id);
      } else {
        setIsExecuting(false);
      }
    } catch (err: any) {
      setError(err.message);
      setIsExecuting(false);
    }
  };

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      {/* Page Title & Tagline */}
      <div className="space-y-1">
        <div className="flex items-center gap-2 text-blue-600 dark:text-blue-400 font-semibold text-xs tracking-wider uppercase">
          <Terminal size={14} />
          <span>ASTRAVA Orchestration Center</span>
        </div>
        <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Command Center</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Transform objectives into verified deliverables through structured planning and autonomous execution.
        </p>
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-xl text-sm">
          {error}
        </div>
      )}

      {/* Studio & Project Selector */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* SaaS Studio Option */}
        <div
          onClick={() => setStudioType('saas')}
          className={`cursor-pointer p-4 rounded-xl border transition-all ${
            studioType === 'saas'
              ? 'border-blue-500 bg-blue-500/5 dark:bg-blue-500/10 shadow-sm'
              : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
              <Code2 size={16} className="text-blue-500" />
              ASTRAVA SaaS
            </span>
            {studioType === 'saas' && <CheckCircle size={15} className="text-blue-500" />}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            PRD generation, architecture design, schema creation, code implementation & QA.
          </p>
        </div>

        {/* Media Studio Option */}
        <div
          onClick={() => setStudioType('media')}
          className={`cursor-pointer p-4 rounded-xl border transition-all ${
            studioType === 'media'
              ? 'border-purple-500 bg-purple-500/5 dark:bg-purple-500/10 shadow-sm'
              : 'border-slate-200 dark:border-slate-800 hover:border-slate-300'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-bold text-sm text-slate-900 dark:text-white flex items-center gap-2">
              <Video size={16} className="text-purple-500" />
              ASTRAVA Media
            </span>
            {studioType === 'media' && <CheckCircle size={15} className="text-purple-500" />}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Content strategy, topic research, narrative scripts, storyboards & SEO publishing prep.
          </p>
        </div>

        {/* Project Selector */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col justify-between">
          <div>
            <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block mb-1.5">
              Assigned Project
            </label>
            <select
              value={selectedProjectId}
              onChange={e => setSelectedProjectId(e.target.value)}
              className="w-full bg-slate-50 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-lg p-2 text-xs text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {projects.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.studio_type})
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={() => setShowNewProjectModal(true)}
            className="text-[11px] text-blue-600 dark:text-blue-400 font-semibold text-left hover:underline mt-2"
          >
            + Create New Project
          </button>
        </div>
      </div>

      {/* Objective Input Card */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
        <label className="block text-sm font-bold text-slate-900 dark:text-white">
          Platform Objective
        </label>
        <textarea
          rows={3}
          value={objective}
          onChange={e => setObjective(e.target.value)}
          placeholder={
            studioType === 'saas'
              ? 'e.g. Build an autonomous invoice validation and audit agent platform with webhook alerts...'
              : 'e.g. Produce a 5-minute documentary script and storyboard exploring autonomous AI coding agents...'
          }
          className="w-full p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        <div className="flex items-center justify-between pt-2">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Sparkles size={13} className="text-blue-500" />
            <span>Execution Model: Claude Haiku 5.5 (Fast, low-cost enterprise executor)</span>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleGeneratePlan}
              disabled={isGeneratingPlan || !objective.trim() || !selectedProjectId}
              className="px-4 py-2 border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50"
            >
              {isGeneratingPlan ? 'Formulating Plan...' : 'Preview Structured Plan'}
            </button>

            <button
              onClick={handleExecutePlan}
              disabled={isExecuting || !objective.trim() || !selectedProjectId}
              className="flex items-center gap-2 px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold rounded-lg transition-colors shadow-sm disabled:opacity-50"
            >
              <Play size={13} fill="white" />
              <span>{isExecuting ? 'Orchestrating...' : 'Execute Pipeline'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Plan Inspection Card */}
      {plan && !activeExecution && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-5 animate-fade-in">
          <div className="flex items-start justify-between">
            <div>
              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300">
                Validated Plan
              </span>
              <h3 className="font-bold text-base text-slate-900 dark:text-white mt-1">
                Execution Strategy
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {plan.strategy_summary}
              </p>
            </div>
            <div className="text-right">
              <span className="text-xs text-slate-400 block">Est. Cost</span>
              <span className="text-sm font-bold font-mono text-emerald-600 dark:text-emerald-400">
                ${plan.estimated_cost_usd.toFixed(4)}
              </span>
            </div>
          </div>

          <div className="space-y-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Pipeline Steps ({plan.tasks.length})
            </h4>
            <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-100 dark:border-slate-800 rounded-lg overflow-hidden">
              {plan.tasks.map((task, idx) => (
                <div key={task.task_id} className="p-3.5 flex items-start gap-4 bg-slate-50/50 dark:bg-slate-800/30">
                  <div className="w-6 h-6 rounded-full bg-blue-600/10 text-blue-600 dark:text-blue-400 flex items-center justify-center text-xs font-bold shrink-0">
                    {idx + 1}
                  </div>
                  <div className="space-y-1 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-xs text-slate-900 dark:text-white">
                        {task.title}
                      </span>
                      {task.requires_approval && (
                        <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 rounded">
                          Approval Required
                        </span>
                      )}
                      <span className="text-[10px] font-mono text-slate-400">
                        ({task.assigned_model})
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-400">{task.description}</p>
                    {task.expected_output_artifacts.length > 0 && (
                      <div className="flex items-center gap-1.5 pt-1">
                        <FileCheck size={11} className="text-slate-400" />
                        <span className="text-[10px] text-slate-400">
                          Artifacts: {task.expected_output_artifacts.join(', ')}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button
            onClick={handleExecutePlan}
            disabled={isExecuting}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold flex items-center justify-center gap-2 transition-colors shadow-sm"
          >
            <Play size={14} fill="white" />
            <span>Approve Strategy & Begin Autonomous Run</span>
          </button>
        </div>
      )}

      {/* Live Execution Tracker */}
      {activeExecution && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-base text-slate-900 dark:text-white">
                  Live Execution
                </span>
                <span className={`px-2 py-0.5 text-xs font-bold uppercase rounded ${
                  activeExecution.status === 'completed'
                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                    : activeExecution.status === 'waiting_approval'
                    ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 animate-pulse'
                    : 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                }`}>
                  {activeExecution.status}
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono mt-0.5">
                ID: {activeExecution.id}
              </p>
            </div>

            {activeExecution.status === 'waiting_approval' && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleApproveFromCommand('approved')}
                  disabled={isExecuting}
                  className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-lg transition-colors"
                >
                  Approve Next Step
                </button>
                <button
                  onClick={() => handleApproveFromCommand('rejected')}
                  disabled={isExecuting}
                  className="px-3.5 py-1.5 bg-red-600 hover:bg-red-500 text-white text-xs font-bold rounded-lg transition-colors"
                >
                  Reject
                </button>
              </div>
            )}
          </div>

          {/* Events Timeline */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Execution Event History ({activeExecution.events?.length ?? 0})
            </h4>
            <div className="bg-slate-50 dark:bg-slate-800/40 rounded-lg p-3 max-h-60 overflow-y-auto font-mono text-xs space-y-1.5 border border-slate-200 dark:border-slate-800">
              {activeExecution.events && activeExecution.events.length > 0 ? (
                activeExecution.events.map(ev => (
                  <div key={ev.id} className="flex items-start gap-2 text-slate-700 dark:text-slate-300">
                    <span className="text-slate-400 shrink-0">
                      [{new Date(ev.created_at).toLocaleTimeString()}]
                    </span>
                    <span className="text-blue-600 dark:text-blue-400 font-bold shrink-0">
                      {ev.event_type}
                    </span>
                    <span className="text-slate-500 dark:text-slate-400 truncate">
                      {JSON.stringify(ev.payload)}
                    </span>
                  </div>
                ))
              ) : (
                <div className="text-slate-400 text-center py-2">Waiting for first execution event...</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* New Project Modal */}
      {showNewProjectModal && (
        <div className="fixed inset-0 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl max-w-md w-full p-6 shadow-xl space-y-4">
            <h3 className="font-bold text-base text-slate-900 dark:text-white">
              Create Production Project
            </h3>
            <form onSubmit={handleCreateProject} className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block mb-1">
                  Project Name
                </label>
                <input
                  type="text"
                  required
                  value={newProjectName}
                  onChange={e => setNewProjectName(e.target.value)}
                  placeholder="e.g. MicroSaaS Billing Agent"
                  className="w-full p-2.5 border border-slate-300 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewProjectModal(false)}
                  className="px-3 py-1.5 text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-semibold hover:bg-blue-500"
                >
                  Create Project
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
