import React, { useEffect, useState } from 'react';
import {
  Cpu,
  Coins,
  Clock,
  CheckCircle2,
  AlertCircle,
  Database,
  BarChart3,
} from 'lucide-react';
import { api } from '../api/client';
import type { ModelExecution, UsageSummary } from '../types/api';

export const IntelligencePage: React.FC = () => {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [executions, setExecutions] = useState<ModelExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.getUsageSummary(), api.getModelExecutions()])
      .then(([s, execs]) => {
        setSummary(s);
        setExecutions(execs);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 dark:text-white">
          Intelligence & Usage Metrics
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Telemetry, token consumption, model durations, and granular execution audit records.
        </p>
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-xl text-sm">
          {error}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Model Runs</span>
            <Cpu size={18} className="text-blue-500" />
          </div>
          <div className="mt-3">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {summary?.total_executions ?? 0}
            </span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Tokens Processed</span>
            <Database size={18} className="text-purple-500" />
          </div>
          <div className="mt-3">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {(summary?.total_tokens ?? 0).toLocaleString()}
            </span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Compute Duration</span>
            <Clock size={18} className="text-amber-500" />
          </div>
          <div className="mt-3">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {((summary?.total_duration_ms ?? 0) / 1000).toFixed(1)}s
            </span>
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
            <span className="text-xs font-semibold uppercase tracking-wider">Estimated Cost</span>
            <Coins size={18} className="text-emerald-500" />
          </div>
          <div className="mt-3">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              ${(summary?.total_cost_usd ?? 0).toFixed(4)}
            </span>
          </div>
        </div>
      </div>

      {/* Model Executions Log */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <BarChart3 className="text-blue-500" size={18} />
          <h3 className="font-bold text-base text-slate-900 dark:text-white">
            Model Execution History ({executions.length})
          </h3>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-400 text-sm">Loading execution logs...</div>
        ) : executions.length === 0 ? (
          <div className="p-8 text-center text-slate-400 text-sm">No model executions recorded yet.</div>
        ) : (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800 text-slate-500 font-bold uppercase tracking-wider">
                <tr>
                  <th className="py-3 px-4">Provider</th>
                  <th className="py-3 px-4">Model</th>
                  <th className="py-3 px-4">Duration</th>
                  <th className="py-3 px-4">Input / Output Tokens</th>
                  <th className="py-3 px-4">Cache Read</th>
                  <th className="py-3 px-4">Cost</th>
                  <th className="py-3 px-4">Exit Code</th>
                  <th className="py-3 px-4">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 font-mono">
                {executions.map(ex => (
                  <tr key={ex.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                    <td className="py-3 px-4 font-bold text-slate-900 dark:text-white">
                      {ex.provider}
                    </td>
                    <td className="py-3 px-4 text-blue-600 dark:text-blue-400">
                      {ex.model}
                    </td>
                    <td className="py-3 px-4 text-slate-700 dark:text-slate-300">
                      {ex.duration_ms} ms
                    </td>
                    <td className="py-3 px-4 text-slate-700 dark:text-slate-300">
                      {ex.input_tokens.toLocaleString()} / {ex.output_tokens.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-slate-500">
                      {ex.cache_read_tokens.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 font-semibold text-emerald-600 dark:text-emerald-400">
                      ${ex.cost_usd.toFixed(5)}
                    </td>
                    <td className="py-3 px-4">
                      {ex.exit_code === 0 ? (
                        <span className="text-emerald-600 flex items-center gap-1 font-sans font-semibold">
                          <CheckCircle2 size={12} /> 0
                        </span>
                      ) : (
                        <span className="text-red-500 flex items-center gap-1 font-sans font-semibold">
                          <AlertCircle size={12} /> {ex.exit_code}
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-slate-400 text-[11px]">
                      {new Date(ex.created_at).toLocaleTimeString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
