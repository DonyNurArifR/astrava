import React, { useState, useEffect } from 'react';
import {
  GitBranch,
  FileCode,
  ArrowDown,
  AlertTriangle,
  CheckCircle,
  ExternalLink,
  ShieldCheck,
  ShieldAlert,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { api } from '../../api/client';
import type { Artifact, ArtifactLineage } from '../../types/api';

interface ArtifactLineageExplorerProps {
  projectId: string;
  initialArtifactId?: string;
  onArtifactSelect?: (artifactId: string) => void;
}

export const ArtifactLineageExplorer: React.FC<ArtifactLineageExplorerProps> = ({
  projectId,
  initialArtifactId,
  onArtifactSelect,
}) => {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>(initialArtifactId || '');
  const [lineage, setLineage] = useState<ArtifactLineage | null>(null);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [loadingLineage, setLoadingLineage] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch list of artifacts in project
  useEffect(() => {
    if (!projectId) return;
    setLoadingArtifacts(true);
    setError(null);
    api
      .getArtifactsByProject(projectId)
      .then((items) => {
        setArtifacts(items);
        if (items.length > 0 && !selectedArtifactId) {
          setSelectedArtifactId(items[0].id);
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to load project artifacts');
      })
      .finally(() => {
        setLoadingArtifacts(false);
      });
  }, [projectId]);

  // Load lineage when selected artifact changes
  useEffect(() => {
    if (!projectId || !selectedArtifactId) {
      setLineage(null);
      return;
    }
    setLoadingLineage(true);
    setError(null);
    api
      .getArtifactLineage(projectId, selectedArtifactId)
      .then((data) => {
        setLineage(data);
        if (onArtifactSelect) {
          onArtifactSelect(selectedArtifactId);
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch artifact lineage');
      })
      .finally(() => {
        setLoadingLineage(false);
      });
  }, [projectId, selectedArtifactId]);

  const handleSelectArtifact = (id: string) => {
    setSelectedArtifactId(id);
  };

  const formatBytes = (bytes: number) => {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  };

  const renderStatusBadge = (status?: string | null) => {
    if (!status) return null;
    const isVerified = status.toLowerCase() === 'verified';
    return (
      <span
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold ${
          isVerified
            ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
            : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20'
        }`}
      >
        {isVerified ? <ShieldCheck size={11} /> : <ShieldAlert size={11} />}
        {status}
      </span>
    );
  };

  const renderNodeCard = (art: Artifact, isCurrent = false) => {
    return (
      <div
        key={art.id}
        onClick={() => !isCurrent && handleSelectArtifact(art.id)}
        className={`p-4 rounded-xl border transition-all ${
          isCurrent
            ? 'bg-blue-50/70 dark:bg-blue-950/40 border-blue-500 ring-2 ring-blue-500/20 shadow-md'
            : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-blue-400 dark:hover:border-blue-600 cursor-pointer hover:shadow-sm'
        }`}
      >
        <div className="flex items-center justify-between gap-3 mb-2">
          <div className="flex items-center gap-2 min-w-0">
            <FileCode
              size={18}
              className={isCurrent ? 'text-blue-600 dark:text-blue-400' : 'text-slate-400'}
            />
            <span className="font-semibold text-sm text-slate-900 dark:text-white truncate">
              {art.name}
            </span>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded text-xs font-mono font-bold">
              v{art.version ?? 1}
            </span>
            {renderStatusBadge(art.verification_status)}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400 font-mono">
          <span>Type: {art.artifact_type}</span>
          <span>Size: {formatBytes(art.file_size_bytes)}</span>
          <span>{new Date(art.created_at).toLocaleDateString()}</span>
        </div>

        {isCurrent && (
          <div className="mt-3 pt-3 border-t border-blue-200/60 dark:border-blue-800/60 flex items-center justify-between text-xs">
            <span className="text-blue-600 dark:text-blue-400 font-medium">Currently Inspected</span>
            <span className="text-slate-400 font-mono text-[11px] truncate max-w-[200px]">
              ID: {art.id.slice(0, 8)}...
            </span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      {/* Header & Artifact Selector */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 p-5 rounded-xl shadow-sm">
        <div>
          <div className="flex items-center gap-2 text-slate-900 dark:text-white font-bold text-base">
            <GitBranch size={20} className="text-blue-500" />
            <span>Artifact Lineage Explorer</span>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Trace artifact evolution, parent derivations, version trees, and supersession chains.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Artifact:
          </label>
          {loadingArtifacts ? (
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Loader2 size={14} className="animate-spin text-blue-500" />
              Loading...
            </div>
          ) : artifacts.length === 0 ? (
            <span className="text-xs text-slate-400 italic">No artifacts in this project</span>
          ) : (
            <select
              value={selectedArtifactId}
              onChange={(e) => handleSelectArtifact(e.target.value)}
              className="px-3 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-medium text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {artifacts.map((art) => (
                <option key={art.id} value={art.id}>
                  {art.name} (v{art.version ?? 1}) - {art.artifact_type}
                </option>
              ))}
            </select>
          )}

          <button
            onClick={() => {
              if (selectedArtifactId) {
                setLoadingLineage(true);
                api
                  .getArtifactLineage(projectId, selectedArtifactId)
                  .then(setLineage)
                  .catch((e) => setError(e.message))
                  .finally(() => setLoadingLineage(false));
              }
            }}
            title="Refresh Lineage"
            className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <RefreshCw size={14} className={loadingLineage ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 rounded-xl text-sm flex items-center gap-2">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {loadingLineage ? (
        <div className="p-16 text-center text-slate-400 flex flex-col items-center justify-center gap-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl">
          <Loader2 size={28} className="animate-spin text-blue-500" />
          <span className="text-sm">Traced lineage hierarchy loading...</span>
        </div>
      ) : !lineage ? (
        <div className="p-12 text-center text-slate-400 text-sm bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl">
          Select an artifact to explore its provenance and derivation history.
        </div>
      ) : (
        <div className="space-y-6">
          {/* Supersession Warning Banner */}
          {lineage.superseded_by && (
            <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center justify-between text-amber-700 dark:text-amber-300">
              <div className="flex items-center gap-2 text-sm">
                <AlertTriangle size={18} className="text-amber-500 flex-shrink-0" />
                <span>
                  This artifact has been superseded by <strong>{lineage.superseded_by.name}</strong> (v
                  {lineage.superseded_by.version ?? 1}).
                </span>
              </div>
              <button
                onClick={() => lineage.superseded_by && handleSelectArtifact(lineage.superseded_by.id)}
                className="px-3 py-1 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold transition-colors flex items-center gap-1"
              >
                View Latest <ExternalLink size={12} />
              </button>
            </div>
          )}

          {/* Supersedes Notice */}
          {lineage.supersedes && lineage.supersedes.length > 0 && (
            <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl text-xs text-blue-700 dark:text-blue-300 flex items-center gap-2">
              <CheckCircle size={14} className="text-blue-500 flex-shrink-0" />
              <span>
                This version supersedes {lineage.supersedes.length} previous revision
                {lineage.supersedes.length > 1 ? 's' : ''}:{' '}
                {lineage.supersedes.map((s) => `${s.name} (v${s.version ?? 1})`).join(', ')}
              </span>
            </div>
          )}

          {/* Lineage Tree Hierarchy */}
          <div className="bg-slate-50/50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 rounded-2xl p-6 space-y-6">
            {/* 1. Ancestors Chain */}
            {lineage.ancestors && lineage.ancestors.length > 0 && (
              <div className="space-y-3">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Ancestors ({lineage.ancestors.length})
                </div>
                <div className="space-y-3">
                  {lineage.ancestors.map((ancestor) => (
                    <div key={ancestor.id} className="space-y-2">
                      {renderNodeCard(ancestor)}
                      <div className="flex justify-center text-slate-300 dark:text-slate-700">
                        <ArrowDown size={18} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 2. Direct Parent if not already in ancestors */}
            {lineage.parent && !lineage.ancestors?.some((a) => a.id === lineage.parent?.id) && (
              <div className="space-y-3">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Direct Parent
                </div>
                {renderNodeCard(lineage.parent)}
                <div className="flex justify-center text-slate-300 dark:text-slate-700">
                  <ArrowDown size={18} />
                </div>
              </div>
            )}

            {/* 3. Current Focus Artifact */}
            <div className="space-y-2">
              <div className="text-xs font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400">
                Selected Artifact Focus
              </div>
              {renderNodeCard(lineage.artifact, true)}
            </div>

            {/* 4. Descendants / Children */}
            {lineage.descendants && lineage.descendants.length > 0 ? (
              <div className="space-y-3 pt-2">
                <div className="flex justify-center text-slate-300 dark:text-slate-700">
                  <ArrowDown size={18} />
                </div>
                <div className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Derived Descendants ({lineage.descendants.length})
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {lineage.descendants.map((descendant) => renderNodeCard(descendant))}
                </div>
              </div>
            ) : (
              <div className="pt-2 text-center text-xs text-slate-400 italic">
                No derivative artifacts have been produced from this version yet.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
