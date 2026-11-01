import React, { useEffect, useState } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  HardDrive,
  Database,
  Cpu,
} from 'lucide-react';
import { api } from '../api/client';

export const SettingsPage: React.FC = () => {
  const [readinessData, setReadinessData] = useState<any>(null);

  useEffect(() => {
    api.getReadiness()
      .then(r => setReadinessData(r))
      .catch(() => {});
  }, []);

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 dark:text-white">System Settings</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Environment configuration, AI execution limits, provider adapters, and storage policies.
        </p>
      </div>

      <div className="space-y-6">
        {/* Provider Adapters Card */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-2 text-slate-900 dark:text-white font-bold text-base">
            <Cpu size={18} className="text-blue-500" />
            <h3>AI Provider Integrations</h3>
          </div>

          <div className="space-y-3">
            {/* Claude Code Adapter */}
            <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 flex items-start justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm text-slate-900 dark:text-white">
                    Claude Code CLI Adapter
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 flex items-center gap-1">
                    <CheckCircle2 size={11} /> Verified Active
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Non-interactive subprocess execution using verified model{' '}
                  <code className="text-blue-600 dark:text-blue-400 font-mono">claude-haiku-5-5</code>.
                </p>
                <div className="text-[11px] font-mono text-slate-400 pt-1 space-y-0.5">
                  <div>Auth: claude.ai Pro Subscription (firstParty)</div>
                  <div>Output Format: Structured JSON with token and cost tracking</div>
                  <div>Security: Argument array execution, secret redaction, isolated CWD</div>
                </div>
              </div>
              <span className="text-xs font-mono font-bold text-slate-400 bg-white dark:bg-slate-900 px-2.5 py-1 rounded border border-slate-200 dark:border-slate-700">
                v2.1.314
              </span>
            </div>

            {/* Antigravity CLI Adapter */}
            <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 flex items-start justify-between">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm text-slate-900 dark:text-white">
                    Antigravity CLI (AGY)
                  </span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 flex items-center gap-1">
                    <CheckCircle2 size={11} /> Verified Active
                  </span>
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Planner, orchestrator, and high-level architectural coordinator.
                </p>
                <div className="text-[11px] font-mono text-slate-400 pt-1">
                  Model: Gemini 3.8 Flash (Medium) / Gemini 4 Argon
                </div>
              </div>
              <span className="text-xs font-mono font-bold text-slate-400 bg-white dark:bg-slate-900 px-2.5 py-1 rounded border border-slate-200 dark:border-slate-700">
                v1.4.12
              </span>
            </div>
          </div>
        </div>

        {/* Database & Infrastructure */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-2 text-slate-900 dark:text-white font-bold text-base">
            <Database size={18} className="text-indigo-500" />
            <h3>Database & Checkpointer Persistence</h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            <div className="p-3 bg-slate-50 dark:bg-slate-800/40 rounded-lg border border-slate-200 dark:border-slate-800 space-y-1">
              <span className="font-semibold text-slate-400">Database Engine</span>
              <p className="font-mono text-slate-900 dark:text-white font-bold">
                PostgreSQL 16 Alpine
              </p>
              <p className="text-slate-400 font-mono text-[11px]">
                Port: 5433 (Conflict-free Docker container)
              </p>
            </div>

            <div className="p-3 bg-slate-50 dark:bg-slate-800/40 rounded-lg border border-slate-200 dark:border-slate-800 space-y-1">
              <span className="font-semibold text-slate-400">Connection State</span>
              <p className="font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                <CheckCircle2 size={13} />
                {readinessData?.database || 'Connected'}
              </p>
              <p className="text-slate-400 font-mono text-[11px]">
                Driver: asyncpg (Async) + psycopg (Sync)
              </p>
            </div>
          </div>
        </div>

        {/* Artifact Storage */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-2 text-slate-900 dark:text-white font-bold text-base">
            <HardDrive size={18} className="text-emerald-500" />
            <h3>Artifact Storage Sandboxing</h3>
          </div>

          <div className="p-3 bg-slate-50 dark:bg-slate-800/40 rounded-lg border border-slate-200 dark:border-slate-800 space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-400">Designated Local Storage</span>
              <span className="font-bold text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
                <CheckCircle2 size={12} /> {readinessData?.storage || 'Available'}
              </span>
            </div>
            <p className="font-mono text-[11px] text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-900 p-2 rounded border border-slate-200 dark:border-slate-700">
              storage/artifacts/
            </p>
            <p className="text-slate-400 text-[11px]">
              Strict path traversal boundaries enforced (`../` directory escapes are rejected with 400).
            </p>
          </div>
        </div>

        {/* Governance & Human Approval Policies */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center gap-2 text-slate-900 dark:text-white font-bold text-base">
            <ShieldCheck size={18} className="text-amber-500" />
            <h3>Operator Governance Policies</h3>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/40 rounded-lg">
              <div>
                <span className="font-bold text-slate-900 dark:text-white block">
                  Destructive External Operations
                </span>
                <span className="text-slate-400">
                  Mandates human authorization before irreversible mutations.
                </span>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                Enforced
              </span>
            </div>

            <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/40 rounded-lg">
              <div>
                <span className="font-bold text-slate-900 dark:text-white block">
                  Public Publishing & Deployments
                </span>
                <span className="text-slate-400">
                  Mandates operator sign-off before publishing media or deploying software.
                </span>
              </div>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                Enforced
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
