import React, { useEffect, useState } from 'react';
import {
  PlayCircle,
  Pause,
  Play,
  Terminal,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import type { Execution } from '../types/api';

export const ExecutionsPage: React.FC = () => {
  const [executions, setExecutions] = useState<Execution[]>([]);
  const [selectedExecution, setSelectedExecution] = useState<Execution | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadExecutions = () => {
    setLoading(true);
    api
      .getExecutions()
      .then(data => {
        setExecutions(data);
        if (selectedExecution) {
          const updated = data.find(e => e.id === selectedExecution.id);
          if (updated) setSelectedExecution(updated);
        }
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadExecutions();
    const interval = setInterval(loadExecutions, 5000);
    return () => clearInterval(interval);
  }, []);

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

              {/* Event Stream */}
              <div className="space-y-2">
                <h4 className="font-bold uppercase text-[10px] tracking-wider text-slate-400">
                  Event Stream ({selectedExecution.events?.length ?? 0})
                </h4>
                <div className="bg-slate-950 text-slate-300 rounded-lg p-3 font-mono text-[11px] space-y-1.5 max-h-64 overflow-y-auto border border-slate-800">
                  {selectedExecution.events && selectedExecution.events.length > 0 ? (
                    selectedExecution.events.map(ev => (
                      <div key={ev.id} className="flex items-start gap-2">
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
