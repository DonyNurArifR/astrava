import React, { useCallback, useEffect, useState } from 'react';
import {
  Terminal,
  Sparkles,
  Play,
  CheckCircle,
  Code2,
  Video,
  FileCheck,
  Bot,
  Brain,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  Layers,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  Execution,
  ObjectiveUnderstanding,
  Project,
  StructuredPlan,
  StudioType,
} from '../types/api';

export const CommandCenterPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [studioType, setStudioType] = useState<StudioType>('saas');
  const [objective, setObjective] = useState('');
  const [isUnderstanding, setIsUnderstanding] = useState(false);
  const [understanding, setUnderstanding] = useState<ObjectiveUnderstanding | null>(null);
  const [isGeneratingPlan, setIsGeneratingPlan] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [plan, setPlan] = useState<StructuredPlan | null>(null);
  const [activeExecution, setActiveExecution] = useState<Execution | null>(null);
  const [error, setError] = useState<string | null>(null);

  // New Project modal state
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');

  const loadProjects = useCallback(() => {
    api
      .getProjects()
      .then(data => {
        setProjects(data);
        setSelectedProjectId(prev => prev || (data.length > 0 ? data[0].id : ''));
      })
      .catch(err => setError(err.message));
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

  const handleUnderstandObjective = async () => {
    if (!objective.trim()) return;
    setIsUnderstanding(true);
    setError(null);
    try {
      const res = await api.understandObjective(objective, studioType, selectedProjectId);
      setUnderstanding(res);
      if (res.studio !== studioType) {
        setStudioType(res.studio);
      }
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsUnderstanding(false);
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
        if (
          updated.status === 'completed' ||
          updated.status === 'failed' ||
          updated.status === 'waiting_approval'
        ) {
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
      const resumed = await api.resumePipeline(
        activeExecution.id,
        decision,
        'Operator confirmed in Command Center'
      );
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
          Transform objectives into verified multi-agent deliverables through semantic interpretation and structured DAG orchestration.
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
            Parallel research & competitor benchmarking, PRD authoring, modular architecture & verified code delivery.
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
            Parallel topic & audience research, narrative strategy, scriptwriting, storyboard, and SEO publishing manifests.
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

        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pt-2">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Sparkles size={13} className="text-blue-500" />
            <span>Execution Model: Claude Haiku 5.5 (Configured executor model)</span>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              onClick={handleUnderstandObjective}
              disabled={isUnderstanding || !objective.trim()}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50"
            >
              <Brain size={14} className="text-purple-500" />
              <span>{isUnderstanding ? 'Interpreting...' : 'Understand Objective'}</span>
            </button>

            <button
              onClick={handleGeneratePlan}
              disabled={isGeneratingPlan || !objective.trim() || !selectedProjectId}
              className="px-4 py-2 border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50"
            >
              {isGeneratingPlan ? 'Formulating Plan...' : 'Generate Multi-Agent Plan'}
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

      {/* Semantic Objective Understanding Card */}
      {understanding && (
        <div className="bg-white dark:bg-slate-900 border border-purple-200 dark:border-purple-900/60 rounded-xl p-6 shadow-sm space-y-4 animate-fade-in">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-purple-50 dark:bg-purple-950/50 text-purple-600 dark:text-purple-400">
                <Brain size={20} />
              </div>
              <div>
                <span className="text-[10px] uppercase font-bold tracking-wider text-purple-600 dark:text-purple-400">
                  Semantic Objective Interpretation
                </span>
                <h3 className="font-bold text-base text-slate-900 dark:text-white">
                  {understanding.intended_outcome}
                </h3>
              </div>
            </div>
            <span
              className={`text-xs font-bold uppercase px-2.5 py-1 rounded-full border ${
                understanding.complexity === 'high'
                  ? 'bg-amber-50 text-amber-700 border-amber-300 dark:bg-amber-950/40 dark:text-amber-300'
                  : understanding.complexity === 'low'
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-300 dark:bg-emerald-950/40 dark:text-emerald-300'
                  : 'bg-blue-50 text-blue-700 border-blue-300 dark:bg-blue-950/40 dark:text-blue-300'
              }`}
            >
              Complexity: {understanding.complexity}
            </span>
          </div>

          {understanding.needs_clarification && (
            <div className="p-3.5 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900/50 text-amber-800 dark:text-amber-300 text-xs space-y-1.5">
              <div className="font-bold flex items-center gap-1.5">
                <AlertTriangle size={14} /> Clarification Recommended
              </div>
              <ul className="list-disc list-inside space-y-0.5 text-[11px]">
                {understanding.clarification_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-1.5">
                Required Agent Capabilities
              </span>
              <div className="flex flex-wrap gap-1.5">
                {understanding.required_capabilities.map(cap => (
                  <span
                    key={cap}
                    className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-mono text-[11px]"
                  >
                    {cap}
                  </span>
                ))}
              </div>
            </div>
            <div>
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 block mb-1.5">
                Expected Deliverables
              </span>
              <div className="flex flex-wrap gap-1.5">
                {understanding.expected_deliverables.map(deliv => (
                  <span
                    key={deliv}
                    className="px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 font-mono text-[11px] border border-emerald-200 dark:border-emerald-800/40"
                  >
                    {deliv}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Plan Inspection Card with DAG Stages */}
      {plan && !activeExecution && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-6 animate-fade-in">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300">
                  Validated Multi-Agent Graph (DAG)
                </span>
                <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                  <ShieldCheck size={14} /> Zero Cycles Detected
                </span>
              </div>
              <h3 className="font-bold text-base text-slate-900 dark:text-white mt-1">
                Execution Strategy & Agent Assignment
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {plan.strategy_summary}
              </p>
            </div>
            <div className="text-right">
              <span className="text-xs text-slate-400 block">Est. Execution Cost</span>
              <span className="text-sm font-bold font-mono text-emerald-600 dark:text-emerald-400">
                ${plan.estimated_cost_usd.toFixed(4)}
              </span>
            </div>
          </div>

          {/* Execution Stages Preview */}
          {plan.execution_stages && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Layers size={13} />
                Execution Wave Stages ({plan.execution_stages.length} Stages)
              </h4>
              <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs">
                {plan.execution_stages.map((stageTasks, sIdx) => (
                  <React.Fragment key={sIdx}>
                    <div className="px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 font-mono text-[11px] whitespace-nowrap">
                      <span className="font-bold text-blue-600 dark:text-blue-400 mr-1.5">
                        Stage {sIdx + 1}:
                      </span>
                      <span>{stageTasks.length} Task(s) {stageTasks.length > 1 && '(Parallel)'}</span>
                    </div>
                    {sIdx < (plan.execution_stages?.length || 0) - 1 && (
                      <ArrowRight size={14} className="text-slate-400 shrink-0" />
                    )}
                  </React.Fragment>
                ))}
              </div>
            </div>
          )}

          {/* Task Dependency & Agent Breakdown */}
          <div className="space-y-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Tasks & Responsible Agents ({plan.tasks.length})
            </h4>
            <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-100 dark:border-slate-800 rounded-lg overflow-hidden">
              {plan.tasks.map((task, idx) => (
                <div key={task.task_id} className="p-3.5 flex items-start gap-4 bg-slate-50/50 dark:bg-slate-800/30">
                  <div className="w-6 h-6 rounded-full bg-blue-600/10 text-blue-600 dark:text-blue-400 flex items-center justify-center text-xs font-bold shrink-0">
                    {idx + 1}
                  </div>
                  <div className="space-y-1.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-xs text-slate-900 dark:text-white">
                        {task.title}
                      </span>

                      {task.assigned_agent_slug && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono font-semibold rounded bg-purple-50 text-purple-700 dark:bg-purple-950/50 dark:text-purple-300 border border-purple-200 dark:border-purple-800/40">
                          <Bot size={11} />
                          {task.assigned_agent_slug}
                        </span>
                      )}

                      {task.requires_approval && (
                        <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300 rounded">
                          Approval Gate
                        </span>
                      )}

                      <span className="text-[10px] font-mono text-slate-400">
                        ({task.assigned_model})
                      </span>
                    </div>

                    <p className="text-xs text-slate-500 dark:text-slate-400">{task.description}</p>

                    <div className="flex flex-wrap items-center gap-3 pt-1 text-[10px] text-slate-400">
                      {task.dependencies.length > 0 ? (
                        <span>Depends on: <span className="font-mono text-slate-500 dark:text-slate-300">{task.dependencies.join(', ')}</span></span>
                      ) : (
                        <span className="text-emerald-600 dark:text-emerald-400">Independent (Can run concurrently)</span>
                      )}

                      {task.expected_output_artifacts.length > 0 && (
                        <span className="flex items-center gap-1">
                          <FileCheck size={11} />
                          {task.expected_output_artifacts.join(', ')}
                        </span>
                      )}
                    </div>
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
            <span>Approve Strategy & Launch Autonomous Multi-Agent Pipeline</span>
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
                  Multi-Agent Execution Pipeline
                </span>
                <span
                  className={`px-2 py-0.5 text-xs font-bold uppercase rounded ${
                    activeExecution.status === 'completed'
                      ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                      : activeExecution.status === 'waiting_approval'
                      ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 animate-pulse'
                      : activeExecution.status === 'failed'
                      ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                      : 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                  }`}
                >
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
                  onClick={() => handleApproveFromCommand('rejected')}
                  disabled={isExecuting}
                  className="px-3 py-1.5 text-xs font-bold text-red-600 border border-red-200 dark:border-red-900/50 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/30"
                >
                  Reject
                </button>
                <button
                  onClick={() => handleApproveFromCommand('approved')}
                  disabled={isExecuting}
                  className="px-4 py-1.5 text-xs font-bold text-white bg-blue-600 hover:bg-blue-500 rounded-lg shadow-sm"
                >
                  Authorize & Resume
                </button>
              </div>
            )}
          </div>

          {/* Progress Overview */}
          <div className="space-y-2">
            <div className="flex justify-between text-xs text-slate-500">
              <span>Completed Tasks: {activeExecution.state_data?.completed_task_ids?.length || 0} / {activeExecution.state_data?.tasks?.length || 0}</span>
              <span>Status: {activeExecution.status}</span>
            </div>
            <div className="w-full bg-slate-100 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
              <div
                className="bg-blue-600 h-full transition-all duration-500"
                style={{
                  width: `${
                    activeExecution.state_data?.tasks?.length
                      ? ((activeExecution.state_data?.completed_task_ids?.length || 0) /
                          activeExecution.state_data.tasks.length) *
                        100
                      : 0
                  }%`,
                }}
              />
            </div>
          </div>

          {/* Tasks in Pipeline */}
          {activeExecution.state_data?.tasks && (
            <div className="space-y-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                Agent Tasks & Concurrency Lifecycle
              </span>
              <div className="space-y-2">
                {activeExecution.state_data.tasks.map((t: any) => {
                  const isCompleted = activeExecution.state_data?.completed_task_ids?.includes(t.task_id);
                  const isFailed = t.status === 'failed' || activeExecution.state_data?.failed_task_ids?.includes(t.task_id);
                  const isWaitingApproval = activeExecution.state_data?.active_approval_id === t.task_id;
                  const isRunning = activeExecution.state_data?.current_ready_task_ids?.includes(t.task_id) && activeExecution.status === 'running';
                  const isParallel = isRunning && (activeExecution.state_data?.current_ready_task_ids?.length || 0) > 1;
                  const isBlocked = !isCompleted && !isFailed && !isRunning && !isWaitingApproval &&
                    t.dependencies?.some((d: string) => activeExecution.state_data?.failed_task_ids?.includes(d));

                  return (
                    <div
                      key={t.task_id}
                      className="p-3.5 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40 space-y-2 text-xs"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2.5">
                          {isCompleted ? (
                            <CheckCircle size={15} className="text-emerald-500 shrink-0" />
                          ) : isFailed ? (
                            <AlertTriangle size={15} className="text-red-500 shrink-0" />
                          ) : isWaitingApproval ? (
                            <ShieldCheck size={15} className="text-amber-500 shrink-0 animate-pulse" />
                          ) : isRunning ? (
                            <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin shrink-0" />
                          ) : (
                            <div className="w-3.5 h-3.5 rounded-full border-2 border-slate-400 shrink-0" />
                          )}
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-900 dark:text-white">
                              {t.title}
                            </span>
                            {t.assigned_agent_slug && (
                              <span className="inline-flex items-center gap-1 font-mono text-[10px] px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-950/50 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/40">
                                <Bot size={10} />
                                @{t.assigned_agent_slug}
                              </span>
                            )}
                            {t.retry_count > 0 && (
                              <span className="font-mono text-[9px] px-1.5 py-0.2 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300">
                                Retry #{t.retry_count}
                              </span>
                            )}
                          </div>
                        </div>

                        <span
                          className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                            isCompleted
                              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
                              : isFailed
                              ? 'bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300'
                              : isWaitingApproval
                              ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300 animate-pulse'
                              : isRunning
                              ? 'bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 animate-pulse'
                              : isBlocked
                              ? 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
                              : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                          }`}
                        >
                          {isCompleted
                            ? 'Completed'
                            : isFailed
                            ? 'Failed'
                            : isWaitingApproval
                            ? 'Awaiting Approval'
                            : isRunning
                            ? isParallel
                              ? 'Running (Parallel Wave)'
                              : 'Running'
                            : isBlocked
                            ? 'Blocked'
                            : 'Planned'}
                        </span>
                      </div>

                      {/* Context Provenance & Dependents */}
                      {t.used_context_sources && t.used_context_sources.length > 0 && (
                        <div className="pl-6 pt-0.5 text-[10px] text-slate-400 flex items-center gap-1.5">
                          <span className="font-semibold text-slate-500 dark:text-slate-400">Context Source:</span>
                          <div className="flex flex-wrap gap-1">
                            {t.used_context_sources.map((src: any) => (
                              <span
                                key={src.task_id}
                                className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono text-slate-600 dark:text-slate-300"
                              >
                                {src.title} (@{src.agent_slug})
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* New Project Modal */}
      {showNewProjectModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 w-full max-w-md shadow-xl space-y-4">
            <h3 className="font-bold text-base text-slate-900 dark:text-white">
              Create New {studioType === 'saas' ? 'SaaS' : 'Media'} Project
            </h3>
            <form onSubmit={handleCreateProject} className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-600 dark:text-slate-300 block mb-1">
                  Project Name
                </label>
                <input
                  type="text"
                  required
                  value={newProjectName}
                  onChange={e => setNewProjectName(e.target.value)}
                  placeholder="e.g. Invoicing AI Suite"
                  className="w-full p-2.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowNewProjectModal(false)}
                  className="px-3 py-1.5 text-xs text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 text-xs font-bold text-white bg-blue-600 hover:bg-blue-500 rounded-lg shadow-sm"
                >
                  Create
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
