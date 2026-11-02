import React, { useState } from 'react';
import { X, AlertTriangle, Sparkles, AlertCircle } from 'lucide-react';
import { api } from '../../api/client';
import type {
  MemoryCategory,
  MemoryProvenanceType,
  ProjectMemory,
} from '../../types/api';

interface MemoryFormModalProps {
  projectId: string;
  memory?: ProjectMemory | null;
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (memory: ProjectMemory) => void;
}

const CATEGORIES: { value: MemoryCategory; label: string }[] = [
  { value: 'decision', label: 'Architectural Decision' },
  { value: 'requirement', label: 'Requirement' },
  { value: 'constraint', label: 'Technical Constraint' },
  { value: 'discovery', label: 'Discovery / Finding' },
  { value: 'milestone', label: 'Milestone' },
  { value: 'objective', label: 'Objective' },
  { value: 'preference', label: 'Team Preference' },
  { value: 'risk', label: 'Identified Risk' },
  { value: 'question', label: 'Open Question' },
];

const PROVENANCE_OPTIONS: { value: MemoryProvenanceType; label: string }[] = [
  { value: 'user_provided', label: 'User Provided (Operator Input)' },
  { value: 'verified_finding', label: 'Verified Finding' },
  { value: 'agent_conclusion', label: 'Agent Conclusion' },
  { value: 'assumption', label: 'Assumption' },
];

export const MemoryFormModal: React.FC<MemoryFormModalProps> = ({
  projectId,
  memory,
  isOpen,
  onClose,
  onSuccess,
}) => {
  const isEditing = Boolean(memory);

  const [category, setCategory] = useState<MemoryCategory>(
    memory?.category || 'decision'
  );
  const [summary, setSummary] = useState(memory?.summary || '');
  const [content, setContent] = useState(memory?.content || '');
  const [provenance, setProvenance] = useState<MemoryProvenanceType>(
    memory?.provenance_type || 'user_provided'
  );
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflictError, setConflictError] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!summary.trim() || !content.trim()) {
      setError('Both summary and content are required.');
      return;
    }

    setSubmitting(true);
    setError(null);
    setConflictError(null);

    try {
      if (isEditing && memory) {
        const updated = await api.updateMemory(projectId, memory.id, {
          expected_revision: memory.revision,
          summary: summary.trim(),
          content: content.trim(),
          reason: reason.trim() || 'Updated via Memory Bank UI',
        });
        onSuccess(updated);
        onClose();
      } else {
        const created = await api.createMemory(projectId, {
          category,
          summary: summary.trim(),
          content: content.trim(),
          provenance_type: provenance,
        });
        onSuccess(created);
        onClose();
      }
    } catch (err: any) {
      const errMsg = err?.message || 'Operation failed';
      if (errMsg.toLowerCase().includes('revision conflict') || errMsg.toLowerCase().includes('expected')) {
        setConflictError(
          'Revision Conflict: Another user or execution modified this memory. Reload to view the latest revision before retrying.'
        );
      } else {
        setError(errMsg);
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs">
      <div className="relative w-full max-w-2xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <Sparkles className="text-blue-500" size={18} />
            <h3 className="font-bold text-base text-slate-900 dark:text-white">
              {isEditing ? `Edit Memory (Revision ${memory?.revision})` : 'Create Project Memory'}
            </h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1 rounded-lg"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-4">
          {conflictError && (
            <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl text-amber-600 dark:text-amber-400 text-xs flex items-start gap-2">
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Optimistic Concurrency Conflict</p>
                <p className="mt-1">{conflictError}</p>
              </div>
            </div>
          )}

          {error && (
            <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-600 dark:text-red-400 text-xs flex items-center gap-2">
              <AlertCircle size={16} className="shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {isEditing && memory?.is_verified && (
            <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl text-blue-600 dark:text-blue-400 text-xs flex items-start gap-2">
              <AlertTriangle size={15} className="shrink-0 mt-0.5" />
              <span>
                Note: Updating the text of this verified memory will produce an immutable new
                revision (Revision {memory.revision + 1}) and reset its verification status to Unverified.
              </span>
            </div>
          )}

          {/* Category */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Category
            </label>
            <select
              value={category}
              onChange={e => setCategory(e.target.value as MemoryCategory)}
              disabled={isEditing}
              className="w-full text-xs px-3 py-2 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white disabled:opacity-60"
            >
              {CATEGORIES.map(c => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          {/* Summary */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
                Summary
              </label>
              <span className="text-[10px] text-slate-400 font-mono">
                {summary.length}/500
              </span>
            </div>
            <input
              type="text"
              value={summary}
              onChange={e => setSummary(e.target.value)}
              placeholder="e.g. Message Broker: RabbitMQ"
              maxLength={500}
              className="w-full text-xs px-3 py-2 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              required
            />
          </div>

          {/* Content */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
              Detailed Content
            </label>
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              rows={6}
              placeholder="Provide complete technical details, rationale, parameters, and constraints..."
              className="w-full text-xs px-3 py-2 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              required
            />
          </div>

          {/* Provenance (Create mode only) */}
          {!isEditing && (
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Provenance Classification
              </label>
              <select
                value={provenance}
                onChange={e => setProvenance(e.target.value as MemoryProvenanceType)}
                className="w-full text-xs px-3 py-2 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white"
              >
                {PROVENANCE_OPTIONS.map(p => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Revision Reason (Edit mode only) */}
          {isEditing && (
            <div>
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                Reason for Revision
              </label>
              <input
                type="text"
                value={reason}
                onChange={e => setReason(e.target.value)}
                placeholder="e.g. Scaling requirements updated per client SLA review"
                className="w-full text-xs px-3 py-2 bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500/30"
              />
            </div>
          )}

          {/* Footer actions */}
          <div className="flex items-center justify-end gap-2 pt-4 border-t border-slate-200 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-slate-600 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-sm disabled:opacity-50"
            >
              {submitting ? 'Saving...' : isEditing ? 'Create New Revision' : 'Create Memory'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
