import React, { useEffect, useState } from 'react';
import {
  X,
  History,
  FileText,
  ShieldCheck,
  Archive,
  RefreshCw,
  Edit3,
  CheckCircle2,
  Clock,
  User,
  AlertTriangle,
} from 'lucide-react';
import { api } from '../../api/client';
import type {
  MemoryAuditLog,
  ProjectMemory,
} from '../../types/api';
import { ProvenanceBadge } from './ProvenanceBadge';
import { VerificationBadge } from './VerificationBadge';

interface MemoryDetailModalProps {
  projectId: string;
  memory: ProjectMemory | null;
  isOpen: boolean;
  onClose: () => void;
  onEdit: (memory: ProjectMemory) => void;
  onMemoryUpdated: (updated: ProjectMemory) => void;
}

type TabType = 'overview' | 'revisions' | 'audit';

export const MemoryDetailModal: React.FC<MemoryDetailModalProps> = ({
  projectId,
  memory,
  isOpen,
  onClose,
  onEdit,
  onMemoryUpdated,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [revisions, setRevisions] = useState<ProjectMemory[]>([]);
  const [auditLogs, setAuditLogs] = useState<MemoryAuditLog[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  // Verification modal state
  const [showVerifyModal, setShowVerifyModal] = useState(false);
  const [verifierName, setVerifierName] = useState('Abstract');
  const [verifyReason, setVerifyReason] = useState('');
  const [verifying, setVerifying] = useState(false);

  // Archive / Restore action state
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !memory) return;
    setActiveTab('overview');
    setHistoryError(null);

    // Fetch revisions and audit in background
    setLoadingHistory(true);
    Promise.all([
      api.getMemoryRevisions(projectId, memory.id).catch(() => []),
      api.getMemoryAudit(projectId, memory.id, 'desc', 1, 50).then(r => (Array.isArray(r) ? r : r?.items) || []).catch(() => []),
    ])
      .then(([revs, logs]) => {
        setRevisions(revs);
        setAuditLogs(logs);
        setLoadingHistory(false);
      })
      .catch(err => {
        setHistoryError(err.message);
        setLoadingHistory(false);
      });
  }, [isOpen, memory, projectId]);

  if (!isOpen || !memory) return null;

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    setVerifying(true);
    try {
      const verified = await api.verifyMemory(projectId, memory.id, {
        verified_by: verifierName.trim() || 'Abstract',
        reason: verifyReason.trim() || 'Verified via Memory Bank UI',
      });
      onMemoryUpdated(verified);
      setShowVerifyModal(false);
    } catch (err: any) {
      alert(err.message || 'Verification failed');
    } finally {
      setVerifying(false);
    }
  };

  const handleArchiveToggle = async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      if (memory.status === 'archived') {
        const restored = await api.restoreMemory(projectId, memory.id, 'Restored via Memory Bank UI');
        onMemoryUpdated(restored);
      } else {
        const archived = await api.archiveMemory(projectId, memory.id, 'Archived via Memory Bank UI');
        onMemoryUpdated(archived);
      }
    } catch (err: any) {
      setActionError(err.message || 'Lifecycle transition failed');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
      <div className="relative w-full max-w-3xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xs uppercase tracking-wider font-mono font-bold text-blue-600 dark:text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded">
                {memory.category}
              </span>
              <span className="text-xs font-mono text-slate-400">
                Rev {memory.revision}
              </span>
              {memory.status === 'archived' && (
                <span className="text-xs font-mono text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                  Archived
                </span>
              )}
            </div>
            <h3 className="text-base font-bold text-slate-900 dark:text-white line-clamp-1">
              {memory.summary}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1 rounded-lg"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-4 px-6 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 text-xs">
          <button
            onClick={() => setActiveTab('overview')}
            className={`py-3 font-semibold flex items-center gap-1.5 border-b-2 transition-colors ${
              activeTab === 'overview'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            <FileText size={14} /> Overview
          </button>
          <button
            onClick={() => setActiveTab('revisions')}
            className={`py-3 font-semibold flex items-center gap-1.5 border-b-2 transition-colors ${
              activeTab === 'revisions'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            <History size={14} /> Revision History ({revisions.length || memory.revision})
          </button>
          <button
            onClick={() => setActiveTab('audit')}
            className={`py-3 font-semibold flex items-center gap-1.5 border-b-2 transition-colors ${
              activeTab === 'audit'
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
            }`}
          >
            <Clock size={14} /> Audit Trail ({auditLogs.length})
          </button>
        </div>

        {/* Body Content */}
        <div className="flex-1 overflow-y-auto p-6 text-xs">
          {actionError && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-xl text-red-600 dark:text-red-400 text-xs flex items-center gap-2">
              <AlertTriangle size={14} /> {actionError}
            </div>
          )}

          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Badges Bar */}
              <div className="flex flex-wrap items-center gap-2">
                <ProvenanceBadge
                  provenance={memory.provenance_type}
                  confidenceScore={memory.confidence_score}
                  showScore
                />
                <VerificationBadge
                  isVerified={memory.is_verified}
                  verifiedBy={memory.metadata_json?.verified_by}
                  verifiedAt={memory.verified_at}
                />
                <span className="text-slate-400 font-mono text-[11px] ml-auto">
                  ID: {memory.id}
                </span>
              </div>

              {/* Factual Content */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">
                  Content Specification
                </h4>
                <div className="p-4 bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800 rounded-xl font-mono text-slate-800 dark:text-slate-200 whitespace-pre-wrap leading-relaxed">
                  {memory.content}
                </div>
              </div>

              {/* Technical Metadata Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 p-4 bg-slate-50 dark:bg-slate-800/30 border border-slate-200 dark:border-slate-800 rounded-xl">
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                    Status
                  </span>
                  <span className="font-mono font-medium text-slate-800 dark:text-slate-200 capitalize">
                    {memory.status}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                    Revision
                  </span>
                  <span className="font-mono font-medium text-slate-800 dark:text-slate-200">
                    v{memory.revision}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                    Conflict Status
                  </span>
                  <span className="font-mono font-medium text-slate-800 dark:text-slate-200 capitalize">
                    {memory.conflict_status}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                    Created
                  </span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {new Date(memory.created_at).toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                    Last Updated
                  </span>
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {new Date(memory.updated_at).toLocaleString()}
                  </span>
                </div>
                {memory.source_agent_slug && (
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase font-semibold">
                      Producing Agent
                    </span>
                    <span className="font-mono text-blue-600 dark:text-blue-400">
                      @{memory.source_agent_slug}
                    </span>
                  </div>
                )}
              </div>

              {/* Verifier Attribution if available */}
              {memory.is_verified && memory.metadata_json?.verified_by && (
                <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl flex items-center justify-between">
                  <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
                    <CheckCircle2 size={16} />
                    <span>
                      Verified by <strong className="font-mono">{memory.metadata_json.verified_by}</strong>
                      {memory.verified_at && ` on ${new Date(memory.verified_at).toLocaleString()}`}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'revisions' && (
            <div className="space-y-4">
              {historyError && (
                <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-500 rounded-lg text-xs">
                  {historyError}
                </div>
              )}
              {loadingHistory ? (
                <div className="py-8 text-center text-slate-400">Loading revision history...</div>
              ) : revisions.length === 0 ? (
                <div className="py-8 text-center text-slate-400">Current revision is the only revision.</div>
              ) : (
                <div className="space-y-3">
                  {revisions.map((rev) => {
                    const isCurrent = rev.id === memory.id;
                    return (
                      <div
                        key={rev.id}
                        className={`p-4 rounded-xl border transition-all ${
                          isCurrent
                            ? 'bg-blue-50/50 dark:bg-blue-900/10 border-blue-500/30'
                            : 'bg-slate-50 dark:bg-slate-800/40 border-slate-200 dark:border-slate-800'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono font-bold text-xs text-blue-600 dark:text-blue-400">
                              Revision {rev.revision}
                            </span>
                            {isCurrent && (
                              <span className="text-[10px] bg-blue-500 text-white font-bold px-1.5 py-0.5 rounded">
                                Current Active
                              </span>
                            )}
                            <span className="text-[11px] text-slate-400 capitalize">
                              ({rev.status})
                            </span>
                          </div>
                          <span className="text-[10px] text-slate-400 font-mono">
                            {new Date(rev.created_at).toLocaleString()}
                          </span>
                        </div>
                        <p className="font-semibold text-slate-900 dark:text-white mb-1">
                          {rev.summary}
                        </p>
                        <p className="font-mono text-slate-700 dark:text-slate-300 text-[11px] bg-white dark:bg-slate-900 p-2 rounded border border-slate-200 dark:border-slate-800">
                          {rev.content}
                        </p>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {activeTab === 'audit' && (
            <div className="space-y-4">
              {loadingHistory ? (
                <div className="py-8 text-center text-slate-400">Loading audit history...</div>
              ) : auditLogs.length === 0 ? (
                <div className="py-8 text-center text-slate-400">No audit records found.</div>
              ) : (
                <div className="relative border-l-2 border-slate-200 dark:border-slate-800 ml-4 space-y-4 py-2">
                  {auditLogs.map(log => (
                    <div key={log.id} className="relative pl-6">
                      <div className="absolute -left-1.5 top-1 w-3 h-3 rounded-full bg-blue-500 border-2 border-white dark:border-slate-900" />
                      <div className="p-3 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-800 rounded-xl space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-bold text-xs uppercase tracking-wider text-slate-800 dark:text-slate-200">
                            {log.action}
                          </span>
                          <span className="text-[10px] font-mono text-slate-400">
                            {new Date(log.created_at).toLocaleString()}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-slate-500 text-[11px]">
                          <User size={12} />
                          <span>
                            Actor: <strong>{log.actor_type}</strong> {log.actor_id ? `(${log.actor_id})` : ''}
                          </span>
                        </div>
                        {log.reason && (
                          <p className="text-slate-600 dark:text-slate-400 italic text-[11px]">
                            "{log.reason}"
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
          <div className="flex items-center gap-2">
            {!memory.is_verified && memory.status === 'active' && (
              <button
                onClick={() => setShowVerifyModal(true)}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-xs"
              >
                <ShieldCheck size={14} /> Verify Memory
              </button>
            )}
            {memory.status !== 'superseded' && (
              <button
                onClick={handleArchiveToggle}
                disabled={actionLoading}
                className="px-3 py-1.5 bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 rounded-lg text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
              >
                {memory.status === 'archived' ? (
                  <>
                    <RefreshCw size={14} /> Restore
                  </>
                ) : (
                  <>
                    <Archive size={14} /> Archive
                  </>
                )}
              </button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {memory.status === 'active' && (
              <button
                onClick={() => {
                  onEdit(memory);
                  onClose();
                }}
                className="px-4 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-xs"
              >
                <Edit3 size={14} /> Edit Memory
              </button>
            )}
            <button
              onClick={onClose}
              className="px-4 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
            >
              Close
            </button>
          </div>
        </div>

        {/* Verification Submodal */}
        {showVerifyModal && (
          <div className="absolute inset-0 z-50 flex items-center justify-center p-6 bg-slate-900/70 backdrop-blur-xs">
            <div className="w-full max-w-md bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400 font-bold text-sm">
                <ShieldCheck size={18} />
                <span>Authorize & Verify Finding</span>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Verifying promotes this memory from an unverified conclusion to an official verified finding
                with persistent audit attribution.
              </p>
              <form onSubmit={handleVerify} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Verifier Identifier
                  </label>
                  <input
                    type="text"
                    value={verifierName}
                    onChange={e => setVerifierName(e.target.value)}
                    className="w-full text-xs px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Verification Reason / Evidence Notes
                  </label>
                  <input
                    type="text"
                    value={verifyReason}
                    onChange={e => setVerifyReason(e.target.value)}
                    placeholder="e.g. Code reviewed against HIPAA data isolation requirements"
                    className="w-full text-xs px-3 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white"
                  />
                </div>
                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowVerifyModal(false)}
                    className="px-3 py-1.5 text-xs text-slate-500 hover:text-slate-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={verifying}
                    className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold disabled:opacity-50"
                  >
                    {verifying ? 'Verifying...' : 'Confirm Verification'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
