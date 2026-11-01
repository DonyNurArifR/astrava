import React, { useCallback, useEffect, useState } from 'react';
import {
  PlayCircle,
  Pause,
  Play,
  Terminal,
  X,
  Bot,
  CheckCircle,
  AlertTriangle,
  ShieldCheck,
  FileCheck,
} from 'lucide-react';
import { api } from '../api/client';
import type { Execution } from '../types/api';

export const ExecutionsPage: React.FC = () => {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [selectedExecution, setSelectedExecution] = useState<Execution | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExecutions = useCallback(() => {
    api
      .getExecutions()
      .then(data => {
        setExecutions(data);
        setSelectedExecution(prev => (prev ? data.find(e => e.id === prev.id) || prev : null));
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    loadExecutions();
    const interval = setInterval(loadExecutions, 5000);
    return () => clearInterval(interval);
  }, [loadExecutions]);

  const handlePause = async (id: string) => {
    setActionLoading(true);
    try {
      await api.pauseExecution(id);
      loadExecutions();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleResume = async (id: string) => {
    setActionLoading(true);
    try {
      await api.resumeExecution(id);
      loadExecutions();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Executions</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Real-time workflow runs, step transitions, state checkpoints, and operator interventions.
          </p>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-xl text-sm">
          {error}
        </div>
      )}

      {loading && executions.length === 0 ? (
        <div className="p-12 text-center text-slate-400 text-sm">Loading execution pipeline data...</div>
      ) : executions.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-12 text-center text-slate-400 space-y-2">
          <PlayCircle size={32} className="mx-auto text-slate-300" />
          <p className="text-sm">No workflow executions recorded yet.</p>
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800 text-slate-500 font-bold uppercase tracking-wider">
              <tr>
                <th className="py-3 px-4">Execution ID</th>
                <th className="py-3 px-4">Status</th>
                <th className="py-3 px-4">Current Step</th>
                <th className="py-3 px-4">Started At</th>
                <th className="py-3 px-4">Events</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {executions.map(e => (
                <tr
                  key={e.id}
                  className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
                >
                  <td className="py-3.5 px-4 font-mono font-bold text-slate-900 dark:text-white">
                    <button
                      onClick={() => setSelectedExecution(e)}
                      className="text-blue-600 dark:text-blue-400 hover:underline"
                    >
                      {e.id.slice(0, 13)}...
                    </button>
                  </td>
                  <td className="py-3.5 px-4">
                    <span
                      className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded ${
                        e.status === 'completed'
                          ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                          : e.status === 'waiting_approval'
                          ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 animate-pulse'
                          : e.status === 'paused'
                          ? 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                          : e.status === 'failed'
                          ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                          : 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                      }`}
                    >
                      {e.status}
                    </span>
                  </td>
                  <td className="py-3.5 px-4 font-semibold text-slate-700 dark:text-slate-300">
                    Step {e.current_step}
                  </td>
                  <td className="py-3.5 px-4 text-slate-500">
                    {e.started_at ? new Date(e.started_at).toLocaleString() : 'Pending'}
                  </td>
                  <td className="py-3.5 px-4 text-slate-500 font-mono">
                    {e.events ? `${e.events.length} events` : '0'}
                  </td>
                  <td className="py-3.5 px-4 text-right space-x-2">
                    {e.status === 'running' && (
                      <button
                        onClick={() => handlePause(e.id)}
                        disabled={actionLoading}
                        className="px-2.5 py-1 rounded bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-700 dark:text-slate-300 font-medium inline-flex items-center gap-1"
                      >
                        <Pause size={11} />
                        <span>Pause</span>
                      </button>
                    )}
                    {e.status === 'paused' && (
                      <button
                        onClick={() => handleResume(e.id)}
                        disabled={actionLoading}
                        className="px-2.5 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium inline-flex items-center gap-1"
                      >
                        <Play size={11} fill="white" />
                        <span>Resume</span>
                      </button>
                    )}
                    <button
                      onClick={() => setSelectedExecution(e)}
                      className="px-2.5 py-1 rounded border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300"
                    >
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Execution Detail Modal */}
      {selectedExecution && (
        <div className="fixed inset-0 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl max-w-2xl w-full p-6 shadow-xl space-y-5 max-h-[85vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-3">
              <div>
                <h3 className="font-bold text-base text-slate-900 dark:text-white flex items-center gap-2">
                  <Terminal size={16} className="text-blue-500" />
                  Execution Inspector
                </h3>
                <span className="font-mono text-xs text-slate-400">
                  {selectedExecution.id}
                </span>
              </div>
              <button
                onClick={() => setSelectedExecution(null)}
                className="text-slate-400 hover:text-slate-900 dark:hover:text-white p-1 rounded"
              >
                <X size={18} />
              </button>
            </div>

            <div className="overflow-y-auto space-y-4 pr-1 text-xs">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-50 dark:bg-slate-800/40 p-3 rounded-lg border border-slate-200 dark:border-slate-800">
                <div>
                  <span className="text-slate-400 block">Status</span>
                  <span className="font-bold uppercase text-slate-900 dark:text-white">
                    {selectedExecution.status}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block">Current Step</span>
                  <span className="font-bold text-slate-900 dark:text-white">
                    Step {selectedExecution.current_step}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block">Started</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {selectedExecution.started_at ? new Date(selectedExecution.started_at).toLocaleTimeString() : 'N/A'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block">Completed</span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {selectedExecution.completed_at ? new Date(selectedExecution.completed_at).toLocaleTimeString() : 'In Progress'}
                  </span>
                </div>
              </div>

              {selectedExecution.error_message && (
                <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-lg">
                  {selectedExecution.error_message}
                </div>
              )}

              {/* Multi-Agent DAG Tasks & Lifecycle */}
              {selectedExecution.state_data?.tasks && (
                <div className="space-y-2">
                  <h4 className="font-bold uppercase text-[10px] tracking-wider text-slate-400">
                    Agent Tasks & Concurrency Lifecycle ({selectedExecution.state_data.tasks.length})
                  </h4>
                  <div className="space-y-2">
                    {selectedExecution.state_data.tasks.map((t: any, tIdx: number) => {
                      const isCompleted = selectedExecution.state_data?.completed_task_ids?.includes(t.task_id);
                      const isFailed = t.status === 'failed' || selectedExecution.state_data?.failed_task_ids?.includes(t.task_id);
                      const isWaitingApproval = selectedExecution.state_data?.active_approval_id === t.task_id;
                      const isRunning = selectedExecution.state_data?.current_ready_task_ids?.includes(t.task_id) && selectedExecution.status === 'running';
                      const isParallel = isRunning && (selectedExecution.state_data?.current_ready_task_ids?.length || 0) > 1;
                      const isBlocked = !isCompleted && !isFailed && !isRunning && !isWaitingApproval &&
                        t.dependencies?.some((d: string) => selectedExecution.state_data?.failed_task_ids?.includes(d));

                      return (
                        <div
                          key={t.task_id || `task-${tIdx}`}
                          className="p-3 rounded-lg border border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40 space-y-1.5 text-xs"
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              {isCompleted ? (
                                <CheckCircle size={14} className="text-emerald-500 shrink-0" />
                              ) : isFailed ? (
                                <AlertTriangle size={14} className="text-red-500 shrink-0" />
                              ) : isWaitingApproval ? (
                                <ShieldCheck size={14} className="text-amber-500 shrink-0 animate-pulse" />
                              ) : isRunning ? (
                                <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin shrink-0" />
                              ) : (
                                <div className="w-3.5 h-3.5 rounded-full border-2 border-slate-400 shrink-0" />
                              )}
                              <span className="font-semibold text-slate-900 dark:text-white">
                                {t.title}
                              </span>
                              {t.assigned_agent_slug && (
                                <span className="inline-flex items-center gap-1 font-mono text-[9px] px-1.5 py-0.5 rounded bg-purple-50 dark:bg-purple-950/50 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/40">
                                  <Bot size={9} />
                                  @{t.assigned_agent_slug}
                                </span>
                              )}
                              {t.retry_count > 0 && (
                                <span className="font-mono text-[9px] px-1.5 py-0.2 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-800 dark:text-amber-300">
                                  Retry #{t.retry_count}
                                </span>
                              )}
                            </div>

                            <span
                              className={`text-[9px] font-mono font-bold px-2 py-0.5 rounded ${
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

                          {t.used_context_sources && t.used_context_sources.length > 0 && (
                            <div className="pl-5 text-[10px] text-slate-400 flex items-center gap-1">
                              <span className="font-medium text-slate-500">Context Source:</span>
                              <div className="flex flex-wrap gap-1">
                                {t.used_context_sources.map((src: any) => (
                                  <span
                                    key={src.task_id}
                                    className="px-1.5 py-0.2 rounded bg-slate-100 dark:bg-slate-800 font-mono text-slate-600 dark:text-slate-300"
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

              {/* Artifacts if recorded */}
              {selectedExecution.state_data?.artifacts && selectedExecution.state_data.artifacts.length > 0 && (
                <div className="space-y-2">
                  <h4 className="font-bold uppercase text-[10px] tracking-wider text-slate-400">
                    Generated Deliverables & Artifacts ({selectedExecution.state_data.artifacts.length})
                  </h4>
                  <div className="divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden">
                    {selectedExecution.state_data.artifacts.map((art: any, i: number) => (
                      <div key={i} className="p-2.5 flex items-center justify-between bg-slate-50/50 dark:bg-slate-800/30">
                        <div className="flex items-center gap-2">
                          <FileCheck size={14} className="text-emerald-500 shrink-0" />
                          <span className="font-mono font-semibold text-slate-800 dark:text-slate-200">
                            {art.name}
                          </span>
                        </div>
                        <span className="text-[10px] font-mono text-slate-400">
                          {art.size_bytes ? `${art.size_bytes} bytes` : 'Stored on disk'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Event Stream */}
              <div className="space-y-2">
                <h4 className="font-bold uppercase text-[10px] tracking-wider text-slate-400">
                  Event Stream ({selectedExecution.events?.length ?? 0})
                </h4>
                <div className="bg-slate-950 text-slate-300 rounded-lg p-3 font-mono text-[11px] space-y-1.5 max-h-64 overflow-y-auto border border-slate-800">
                  {selectedExecution.events && selectedExecution.events.length > 0 ? (
                    selectedExecution.events.map((ev, i) => (
                      <div key={ev.id || `${ev.event_type}-${i}`} className="flex items-start gap-2">
                        <span className="text-slate-500 shrink-0">
                          [{new Date(ev.created_at).toLocaleTimeString()}]
                        </span>
                        <span className="text-blue-400 font-semibold shrink-0">{ev.event_type}</span>
                        <span className="text-slate-300">{JSON.stringify(ev.payload)}</span>
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-500">No events recorded.</div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
