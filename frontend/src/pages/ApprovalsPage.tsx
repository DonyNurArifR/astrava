import React, { useEffect, useState } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  User,
} from 'lucide-react';
import { api } from '../api/client';
import type { Approval } from '../types/api';

export const ApprovalsPage: React.FC = () => {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [loading, setLoading] = useState(true);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [reason, setReason] = useState<{ [id: string]: string }>({});
  const [error, setError] = useState<string | null>(null);

  const loadApprovals = () => {
    setLoading(true);
    api
      .getApprovals(false)
      .then(data => {
        setApprovals(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadApprovals();
  }, []);

  const handleDecision = async (id: string, decision: 'approved' | 'rejected') => {
    setDecidingId(id);
    try {
      await api.decideApproval(id, decision, reason[id] || undefined);
      loadApprovals();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setDecidingId(null);
    }
  };

  const pendingList = approvals.filter(a => a.status === 'pending');
  const historyList = approvals.filter(a => a.status !== 'pending');

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Human Approvals</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Operator governance boundaries. Inspect risk factors and authorize critical pipeline operations.
        </p>
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-xl text-sm">
          {error}
        </div>
      )}

      {/* Pending Approvals Section */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <ShieldAlert className="text-amber-500" size={18} />
          <h3 className="font-bold text-base text-slate-900 dark:text-white">
            Pending Authorization Requests ({pendingList.length})
          </h3>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-400 text-sm">Loading requests...</div>
        ) : pendingList.length === 0 ? (
          <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-xl p-8 text-center text-emerald-700 dark:text-emerald-300 text-sm flex items-center justify-center gap-2">
            <CheckCircle size={16} className="text-emerald-500" />
            <span>All operating boundaries clear. No pending human approvals required.</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4">
            {pendingList.map(item => (
              <div
                key={item.id}
                className="bg-white dark:bg-slate-900 border border-amber-500/40 rounded-xl p-6 shadow-sm space-y-4"
              >
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="px-2.5 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 flex items-center gap-1">
                      <AlertTriangle size={11} />
                      {item.risk_level} Risk
                    </span>
                    <span className="font-mono text-xs text-slate-400">
                      Action: {item.action_type}
                    </span>
                  </div>
                  <span className="text-xs text-slate-400 flex items-center gap-1">
                    <Clock size={12} /> {new Date(item.created_at).toLocaleString()}
                  </span>
                </div>

                <div>
                  <h4 className="font-bold text-base text-slate-900 dark:text-white">
                    {item.description}
                  </h4>
                  {item.context_data && (
                    <pre className="mt-2 p-3 bg-slate-50 dark:bg-slate-800/60 rounded-lg text-xs font-mono text-slate-600 dark:text-slate-300 overflow-x-auto border border-slate-200 dark:border-slate-800">
                      {JSON.stringify(item.context_data, null, 2)}
                    </pre>
                  )}
                </div>

                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-2">
                  <input
                    type="text"
                    placeholder="Decision reasoning (optional)..."
                    value={reason[item.id] || ''}
                    onChange={e => setReason({ ...reason, [item.id]: e.target.value })}
                    className="flex-1 p-2 text-xs border border-slate-300 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none"
                  />
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleDecision(item.id, 'approved')}
                      disabled={decidingId === item.id}
                      className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition-colors shadow-sm disabled:opacity-50"
                    >
                      Authorize Action
                    </button>
                    <button
                      onClick={() => handleDecision(item.id, 'rejected')}
                      disabled={decidingId === item.id}
                      className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg text-xs font-bold transition-colors shadow-sm disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Approval History Table */}
      <div className="space-y-4 pt-4 border-t border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <ShieldCheck className="text-slate-400" size={18} />
          <h3 className="font-bold text-base text-slate-900 dark:text-white">
            Approval History ({historyList.length})
          </h3>
        </div>

        {historyList.length === 0 ? (
          <div className="p-8 text-center text-slate-400 text-sm">No historical approval records.</div>
        ) : (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800 text-slate-500 font-bold uppercase tracking-wider">
                <tr>
                  <th className="py-3 px-4">Action</th>
                  <th className="py-3 px-4">Decision</th>
                  <th className="py-3 px-4">Reason</th>
                  <th className="py-3 px-4">Decided By</th>
                  <th className="py-3 px-4">Decided At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {historyList.map(h => (
                  <tr key={h.id}>
                    <td className="py-3 px-4 font-semibold text-slate-900 dark:text-white">
                      {h.description}
                    </td>
                    <td className="py-3 px-4">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase flex items-center gap-1 w-fit ${
                          h.status === 'approved'
                            ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
                            : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                        }`}
                      >
                        {h.status === 'approved' ? <CheckCircle size={10} /> : <XCircle size={10} />}
                        {h.status}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-slate-500 italic max-w-xs truncate">
                      {h.decision_reason || '—'}
                    </td>
                    <td className="py-3 px-4 text-slate-700 dark:text-slate-300 flex items-center gap-1">
                      <User size={12} className="text-slate-400" />
                      <span>{h.decided_by || 'Abstract'}</span>
                    </td>
                    <td className="py-3 px-4 text-slate-500 font-mono text-[11px]">
                      {h.decided_at ? new Date(h.decided_at).toLocaleString() : '—'}
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
