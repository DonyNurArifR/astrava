import React, { useEffect, useState, useCallback } from 'react';
import {
  Brain,
  Cpu,
  Coins,
  Clock,
  CheckCircle2,
  AlertCircle,
  Database,
  BarChart3,
  Search,
  Filter,
  Plus,
  GitBranch,
  ShieldAlert,
  Loader2,
  FolderGit2,
  Sparkles,
  RefreshCw,
  Archive,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  ModelExecution,
  UsageSummary,
  Project,
  ProjectMemory,
  MemoryStats,
} from '../types/api';
import { ProvenanceBadge } from '../components/intelligence/ProvenanceBadge';
import { VerificationBadge } from '../components/intelligence/VerificationBadge';
import { MemoryDetailModal } from '../components/intelligence/MemoryDetailModal';
import { MemoryFormModal } from '../components/intelligence/MemoryFormModal';
import { ConflictWorkbench } from '../components/intelligence/ConflictWorkbench';
import { ArtifactLineageExplorer } from '../components/intelligence/ArtifactLineageExplorer';

type TabType = 'memories' | 'conflicts' | 'lineage' | 'telemetry';

export const IntelligencePage: React.FC = () => {
  // Tabs & Project Selection
  const [activeTab, setActiveTab] = useState<TabType>('memories');
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>('');
  const [loadingProjects, setLoadingProjects] = useState(true);

  // Telemetry state
  const [telemetrySummary, setTelemetrySummary] = useState<UsageSummary | null>(null);
  const [telemetryExecutions, setTelemetryExecutions] = useState<ModelExecution[]>([]);
  const [loadingTelemetry, setLoadingTelemetry] = useState(false);

  // Memory Bank state
  const [memories, setMemories] = useState<ProjectMemory[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [loadingMemories, setLoadingMemories] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters & Pagination
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [provenanceFilter, setProvenanceFilter] = useState<string>('all');
  const [verifiedFilter, setVerifiedFilter] = useState<string>('all');
  const [includeArchived, setIncludeArchived] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [totalPages, setTotalPages] = useState(1);
  const [totalMemories, setTotalMemories] = useState(0);

  // Modals
  const [selectedMemory, setSelectedMemory] = useState<ProjectMemory | null>(null);
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingMemory, setEditingMemory] = useState<ProjectMemory | null>(null);

  // Load projects list
  useEffect(() => {
    setLoadingProjects(true);
    api
      .getProjects()
      .then((data) => {
        setProjects(data);
        if (data.length > 0 && !selectedProjectId) {
          setSelectedProjectId(data[0].id);
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to load projects');
      })
      .finally(() => {
        setLoadingProjects(false);
      });
  }, []);

  // Fetch telemetry data
  useEffect(() => {
    setLoadingTelemetry(true);
    Promise.all([api.getUsageSummary(), api.getModelExecutions()])
      .then(([s, execs]) => {
        setTelemetrySummary(s);
        setTelemetryExecutions(execs);
      })
      .catch((err) => {
        console.error('Failed to load telemetry data:', err);
      })
      .finally(() => {
        setLoadingTelemetry(false);
      });
  }, []);

  // Fetch memory stats
  const fetchStats = useCallback(() => {
    if (!selectedProjectId) return;
    api
      .getMemoryStats(selectedProjectId)
      .then((data) => {
        setStats(data);
      })
      .catch((err) => {
        console.error('Failed to load memory stats:', err);
      });
  }, [selectedProjectId]);

  // Fetch memories list
  const fetchMemories = useCallback(() => {
    if (!selectedProjectId) return;
    setLoadingMemories(true);
    setError(null);

    const params: {
      category?: string;
      provenance?: string;
      status?: string;
      is_verified?: boolean;
      search?: string;
      include_historical?: boolean;
      page?: number;
      page_size?: number;
    } = {
      page: currentPage,
      page_size: pageSize,
      include_historical: includeArchived,
    };

    if (searchQuery.trim()) {
      params.search = searchQuery.trim();
    }
    if (categoryFilter !== 'all') {
      params.category = categoryFilter;
    }
    if (provenanceFilter !== 'all') {
      params.provenance = provenanceFilter;
    }
    if (verifiedFilter !== 'all') {
      params.is_verified = verifiedFilter === 'verified';
    }

    api
      .getMemories(selectedProjectId, params)
      .then((res) => {
        setMemories(res.items);
        setTotalMemories(res.total);
        setTotalPages(res.total_pages);
      })
      .catch((err) => {
        setError(err.message || 'Failed to fetch memories');
      })
      .finally(() => {
        setLoadingMemories(false);
      });
  }, [
    selectedProjectId,
    currentPage,
    pageSize,
    searchQuery,
    categoryFilter,
    provenanceFilter,
    verifiedFilter,
    includeArchived,
  ]);

  useEffect(() => {
    fetchStats();
    fetchMemories();
  }, [fetchStats, fetchMemories]);

  // Action handlers
  const handleOpenDetail = (mem: ProjectMemory) => {
    setSelectedMemory(mem);
    setIsDetailOpen(true);
  };

  const handleOpenCreate = () => {
    setEditingMemory(null);
    setIsFormOpen(true);
  };

  const handleOpenEdit = (mem: ProjectMemory) => {
    setEditingMemory(mem);
    setIsDetailOpen(false);
    setIsFormOpen(true);
  };

  const handleFormSaved = (savedMem: ProjectMemory) => {
    fetchMemories();
    fetchStats();
    if (selectedMemory && selectedMemory.id === savedMem.id) {
      setSelectedMemory(savedMem);
    }
  };

  const handleMemoryUpdated = (updatedMem: ProjectMemory) => {
    setMemories((prev) => prev.map((m) => (m.id === updatedMem.id ? updatedMem : m)));
    setSelectedMemory(updatedMem);
    fetchStats();
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header with Project Selector & Action */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <Brain className="text-blue-500" size={28} />
            <span>Project Intelligence & Memory Bank</span>
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Persistent cross-execution knowledge, memory audit trails, conflict resolution,
            artifact lineage, and compute telemetry.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Project Selector */}
          <div className="flex items-center gap-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-1.5 shadow-sm">
            <FolderGit2 size={16} className="text-slate-400" />
            <select
              value={selectedProjectId}
              onChange={(e) => {
                setSelectedProjectId(e.target.value);
                setCurrentPage(1);
              }}
              disabled={loadingProjects || projects.length === 0}
              className="bg-transparent text-xs font-semibold text-slate-900 dark:text-white focus:outline-none cursor-pointer"
            >
              {projects.length === 0 ? (
                <option value="">No projects available</option>
              ) : (
                projects.map((proj) => (
                  <option key={proj.id} value={proj.id}>
                    {proj.name} ({proj.studio_type})
                  </option>
                ))
              )}
            </select>
          </div>

          {/* New Memory Action */}
          <button
            onClick={handleOpenCreate}
            disabled={!selectedProjectId}
            className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-xl text-xs font-bold shadow-sm transition-colors cursor-pointer"
          >
            <Plus size={16} />
            <span>New Memory</span>
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-xl text-sm flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
          <button
            onClick={() => setError(null)}
            className="text-xs hover:underline font-semibold"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Tabs Navigation */}
      <div className="border-b border-slate-200 dark:border-slate-800">
        <nav className="flex space-x-6 text-sm font-semibold">
          <button
            onClick={() => setActiveTab('memories')}
            className={`pb-3 flex items-center gap-2 transition-colors relative cursor-pointer ${
              activeTab === 'memories'
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500'
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            }`}
          >
            <Brain size={16} />
            <span>Memory Bank</span>
            {stats && stats.total_active > 0 && (
              <span className="px-2 py-0.5 rounded-full text-[10px] bg-blue-100 dark:bg-blue-900/50 text-blue-700 dark:text-blue-300">
                {stats.total_active}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('conflicts')}
            className={`pb-3 flex items-center gap-2 transition-colors relative cursor-pointer ${
              activeTab === 'conflicts'
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500'
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            }`}
          >
            <ShieldAlert size={16} />
            <span>Conflict Workbench</span>
            {stats && stats.open_conflicts > 0 && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500 text-white">
                {stats.open_conflicts}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('lineage')}
            className={`pb-3 flex items-center gap-2 transition-colors relative cursor-pointer ${
              activeTab === 'lineage'
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500'
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            }`}
          >
            <GitBranch size={16} />
            <span>Artifact Lineage</span>
          </button>

          <button
            onClick={() => setActiveTab('telemetry')}
            className={`pb-3 flex items-center gap-2 transition-colors relative cursor-pointer ${
              activeTab === 'telemetry'
                ? 'text-blue-600 dark:text-blue-400 border-b-2 border-blue-500'
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            }`}
          >
            <BarChart3 size={16} />
            <span>Model Telemetry & Usage</span>
          </button>
        </nav>
      </div>

      {/* TAB 1: MEMORY BANK */}
      {activeTab === 'memories' && (
        <div className="space-y-6">
          {/* Summary KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
                <span className="text-xs font-semibold uppercase tracking-wider">Active Memories</span>
                <Brain size={18} className="text-blue-500" />
              </div>
              <div className="mt-3 flex items-baseline justify-between">
                <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
                  {stats?.total_active ?? 0}
                </span>
                <span className="text-xs text-slate-400">
                  {stats?.archived ?? 0} archived
                </span>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
                <span className="text-xs font-semibold uppercase tracking-wider">Verified Findings</span>
                <CheckCircle2 size={18} className="text-emerald-500" />
              </div>
              <div className="mt-3">
                <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
                  {stats?.verified_findings ?? 0}
                </span>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
                <span className="text-xs font-semibold uppercase tracking-wider">Agent Conclusions</span>
                <Sparkles size={18} className="text-amber-500" />
              </div>
              <div className="mt-3 flex items-baseline justify-between">
                <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
                  {stats?.agent_conclusions ?? 0}
                </span>
                <span className="text-xs text-slate-400">
                  {stats?.assumptions ?? 0} assumptions
                </span>
              </div>
            </div>

            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
                <span className="text-xs font-semibold uppercase tracking-wider">Open Conflicts</span>
                <ShieldAlert
                  size={18}
                  className={(stats?.open_conflicts ?? 0) > 0 ? 'text-amber-500' : 'text-slate-400'}
                />
              </div>
              <div className="mt-3 flex items-baseline justify-between">
                <span
                  className={`text-3xl font-extrabold ${
                    (stats?.open_conflicts ?? 0) > 0
                      ? 'text-amber-600 dark:text-amber-400'
                      : 'text-slate-900 dark:text-white'
                  }`}
                >
                  {stats?.open_conflicts ?? 0}
                </span>
                {(stats?.open_conflicts ?? 0) > 0 && (
                  <button
                    onClick={() => setActiveTab('conflicts')}
                    className="text-xs font-semibold text-blue-600 dark:text-blue-400 hover:underline cursor-pointer"
                  >
                    Resolve in Workbench &rarr;
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Search & Filter Toolbar */}
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-4 shadow-sm flex flex-col md:flex-row gap-4 items-center justify-between">
            <div className="relative flex-1 w-full md:w-auto">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search memories by summary or content..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setCurrentPage(1);
                }}
                className="w-full pl-9 pr-4 py-2 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div className="flex flex-wrap items-center gap-3 w-full md:w-auto justify-end">
              {/* Category Filter */}
              <div className="flex items-center gap-1.5 text-xs text-slate-500">
                <Filter size={14} />
                <select
                  value={categoryFilter}
                  onChange={(e) => {
                    setCategoryFilter(e.target.value);
                    setCurrentPage(1);
                  }}
                  className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-medium text-slate-900 dark:text-white focus:outline-none"
                >
                  <option value="all">All Categories</option>
                  <option value="decision">Decisions</option>
                  <option value="requirement">Requirements</option>
                  <option value="architecture">Architecture</option>
                  <option value="constraint">Constraints</option>
                  <option value="discovery">Discoveries</option>
                  <option value="pattern">Patterns</option>
                  <option value="preference">Preferences</option>
                  <option value="fact">Facts</option>
                  <option value="risk">Risks</option>
                  <option value="milestone">Milestones</option>
                </select>
              </div>

              {/* Provenance Filter */}
              <select
                value={provenanceFilter}
                onChange={(e) => {
                  setProvenanceFilter(e.target.value);
                  setCurrentPage(1);
                }}
                className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-medium text-slate-900 dark:text-white focus:outline-none"
              >
                <option value="all">All Provenance</option>
                <option value="user_provided">User Provided</option>
                <option value="verified_finding">Verified Finding</option>
                <option value="agent_conclusion">Agent Conclusion</option>
                <option value="assumption">Assumption</option>
              </select>

              {/* Verification Filter */}
              <select
                value={verifiedFilter}
                onChange={(e) => {
                  setVerifiedFilter(e.target.value);
                  setCurrentPage(1);
                }}
                className="px-2.5 py-1.5 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-xs font-medium text-slate-900 dark:text-white focus:outline-none"
              >
                <option value="all">All Status</option>
                <option value="verified">Verified Only</option>
                <option value="unverified">Unverified Only</option>
              </select>

              {/* Archived Checkbox */}
              <label className="flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={includeArchived}
                  onChange={(e) => {
                    setIncludeArchived(e.target.checked);
                    setCurrentPage(1);
                  }}
                  className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                />
                <span>Include Archived</span>
              </label>

              <button
                onClick={() => {
                  fetchMemories();
                  fetchStats();
                }}
                title="Refresh"
                className="p-1.5 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-500 hover:text-slate-900 dark:hover:text-white transition-colors cursor-pointer"
              >
                <RefreshCw size={14} className={loadingMemories ? 'animate-spin' : ''} />
              </button>
            </div>
          </div>

          {/* Memories List / Table */}
          {loadingMemories ? (
            <div className="p-16 text-center text-slate-400 flex flex-col items-center justify-center gap-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl">
              <Loader2 size={28} className="animate-spin text-blue-500" />
              <span className="text-sm">Loading project memory bank...</span>
            </div>
          ) : memories.length === 0 ? (
            <div className="p-16 text-center text-slate-400 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl space-y-3">
              <Brain size={36} className="mx-auto text-slate-300 dark:text-slate-600" />
              <p className="text-sm font-medium">No project memories found.</p>
              <p className="text-xs text-slate-500 max-w-md mx-auto">
                Memories store persistent project decisions, requirements, and findings across
                autonomous agent workflows. Create your first memory or let agents capture them.
              </p>
              <button
                onClick={handleOpenCreate}
                className="mt-2 inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold cursor-pointer"
              >
                <Plus size={14} /> Create Memory
              </button>
            </div>
          ) : (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {memories.map((mem) => (
                  <div
                    key={mem.id}
                    onClick={() => handleOpenDetail(mem)}
                    className="p-4 hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors cursor-pointer flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                  >
                    <div className="space-y-1.5 min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="px-2 py-0.5 rounded text-[11px] font-bold font-mono uppercase bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300">
                          {mem.category}
                        </span>
                        <h4 className="font-semibold text-sm text-slate-900 dark:text-white truncate">
                          {mem.summary}
                        </h4>
                        {mem.status === 'archived' && (
                          <span className="px-2 py-0.2 rounded text-[10px] bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400 font-semibold flex items-center gap-1">
                            <Archive size={10} /> Archived
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2">
                        {mem.content}
                      </p>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
                        <span>Rev. {mem.revision}</span>
                        <span>
                          Updated {new Date(mem.updated_at).toLocaleDateString()}
                        </span>
                        {mem.metadata_json?.tags && Array.isArray(mem.metadata_json.tags) && (
                          <span>Tags: {mem.metadata_json.tags.join(', ')}</span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2.5 flex-shrink-0 self-start sm:self-center">
                      <ProvenanceBadge
                        provenance={mem.provenance_type}
                        confidenceScore={mem.confidence_score}
                      />
                      <VerificationBadge
                        isVerified={mem.is_verified}
                        verifiedAt={mem.verified_at}
                      />
                    </div>
                  </div>
                ))}
              </div>

              {/* Pagination Controls */}
              <div className="p-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500">
                <span>
                  Showing {memories.length} of {totalMemories} memories (Page {currentPage} of{' '}
                  {totalPages || 1})
                </span>

                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1">
                    <span>Rows:</span>
                    <select
                      value={pageSize}
                      onChange={(e) => {
                        setPageSize(Number(e.target.value));
                        setCurrentPage(1);
                      }}
                      className="bg-transparent border border-slate-200 dark:border-slate-700 rounded px-1.5 py-0.5 text-xs text-slate-900 dark:text-white"
                    >
                      <option value={10}>10</option>
                      <option value={20}>20</option>
                      <option value={50}>50</option>
                    </select>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                      disabled={currentPage <= 1}
                      className="p-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer disabled:cursor-not-allowed"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <button
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                      disabled={currentPage >= totalPages}
                      className="p-1 rounded border border-slate-200 dark:border-slate-700 disabled:opacity-40 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer disabled:cursor-not-allowed"
                    >
                      <ChevronRight size={16} />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: CONFLICT WORKBENCH */}
      {activeTab === 'conflicts' && (
        <ConflictWorkbench
          projectId={selectedProjectId}
          onConflictResolved={() => {
            fetchStats();
            fetchMemories();
          }}
        />
      )}

      {/* TAB 3: ARTIFACT LINEAGE */}
      {activeTab === 'lineage' && (
        <ArtifactLineageExplorer projectId={selectedProjectId} />
      )}

      {/* TAB 4: MODEL TELEMETRY */}
      {activeTab === 'telemetry' && (
        <div className="space-y-6">
          {/* Summary Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between text-slate-500 dark:text-slate-400">
                <span className="text-xs font-semibold uppercase tracking-wider">Total Model Runs</span>
                <Cpu size={18} className="text-blue-500" />
              </div>
              <div className="mt-3">
                <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
                  {telemetrySummary?.total_executions ?? 0}
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
                  {(telemetrySummary?.total_tokens ?? 0).toLocaleString()}
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
                  {((telemetrySummary?.total_duration_ms ?? 0) / 1000).toFixed(1)}s
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
                  ${(telemetrySummary?.total_cost_usd ?? 0).toFixed(4)}
                </span>
              </div>
            </div>
          </div>

          {/* Model Executions Log */}
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <BarChart3 className="text-blue-500" size={18} />
              <h3 className="font-bold text-base text-slate-900 dark:text-white">
                Model Execution History ({telemetryExecutions.length})
              </h3>
            </div>

            {loadingTelemetry ? (
              <div className="p-8 text-center text-slate-400 text-sm">Loading execution logs...</div>
            ) : telemetryExecutions.length === 0 ? (
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
                    {telemetryExecutions.map((ex) => (
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
      )}

      {/* Modals */}
      {selectedMemory && (
        <MemoryDetailModal
          isOpen={isDetailOpen}
          projectId={selectedProjectId}
          memory={selectedMemory}
          onClose={() => setIsDetailOpen(false)}
          onEdit={handleOpenEdit}
          onMemoryUpdated={handleMemoryUpdated}
        />
      )}

      {selectedProjectId && (
        <MemoryFormModal
          isOpen={isFormOpen}
          projectId={selectedProjectId}
          memory={editingMemory}
          onClose={() => setIsFormOpen(false)}
          onSuccess={handleFormSaved}
        />
      )}
    </div>
  );
};
