import React, { useState, useEffect, useCallback } from 'react';
import {
  Bot,
  Search,
  Filter,
  CheckCircle,
  XCircle,
  Cpu,
  Layers,
  Wrench,
  FileCode,
  ShieldAlert,
  RotateCw,
  Eye,
  X,
} from 'lucide-react';
import { api } from '../api/client';
import type { Agent, StudioType } from '../types/api';

export const AgentsPage: React.FC = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState<string>('');
  const [selectedStudio, setSelectedStudio] = useState<StudioType | 'all'>('all');
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const loadAgents = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const studioFilter = selectedStudio === 'all' ? undefined : selectedStudio;
      const data = await api.getAgents(studioFilter);
      setAgents(data);
    } catch (err: any) {
      setError(err.message || 'Failed to load agents from registry');
    } finally {
      setLoading(false);
    }
  }, [selectedStudio]);

  useEffect(() => {
    let ignore = false;
    const studioFilter = selectedStudio === 'all' ? undefined : selectedStudio;
    api
      .getAgents(studioFilter)
      .then(data => {
        if (!ignore) {
          setAgents(data);
          setError(null);
          setLoading(false);
        }
      })
      .catch((err: any) => {
        if (!ignore) {
          setError(err.message || 'Failed to load agents from registry');
          setLoading(false);
        }
      });
    return () => {
      ignore = true;
    };
  }, [selectedStudio]);

  const handleToggleStatus = async (agent: Agent) => {
    try {
      setUpdatingId(agent.id);
      const updated = await api.updateAgentStatus(agent.slug, !agent.is_enabled);
      setAgents(prev => prev.map(a => (a.id === updated.id ? updated : a)));
      if (selectedAgent && selectedAgent.id === updated.id) {
        setSelectedAgent(updated);
      }
    } catch (err: any) {
      alert(`Failed to update agent status: ${err.message}`);
    } finally {
      setUpdatingId(null);
    }
  };

  const filteredAgents = agents.filter(agent => {
    const matchesSearch =
      agent.name.toLowerCase().includes(search.toLowerCase()) ||
      agent.slug.toLowerCase().includes(search.toLowerCase()) ||
      agent.capabilities.some(c => c.toLowerCase().includes(search.toLowerCase()));
    return matchesSearch;
  });

  const saasCount = agents.filter(a => a.studio_type === 'saas').length;
  const mediaCount = agents.filter(a => a.studio_type === 'media').length;
  const enabledCount = agents.filter(a => a.is_enabled).length;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white flex items-center gap-2">
            <Bot className="text-blue-500" size={26} />
            Agent Registry
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Configurable autonomous agent capabilities, system instructions, and execution schemas.
          </p>
        </div>
        <button
          onClick={loadAgents}
          disabled={loading}
          className="inline-flex items-center gap-2 px-3 py-2 text-xs font-medium rounded-lg bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors"
        >
          <RotateCw size={14} className={loading ? 'animate-spin' : ''} />
          Refresh Registry
        </button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 rounded-xl p-4 shadow-xs">
          <div className="text-xs text-slate-500 dark:text-slate-400">Total Registered</div>
          <div className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{agents.length}</div>
        </div>
        <div className="bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 rounded-xl p-4 shadow-xs">
          <div className="text-xs text-slate-500 dark:text-slate-400">Active & Enabled</div>
          <div className="text-2xl font-bold text-emerald-600 dark:text-emerald-400 mt-1">{enabledCount}</div>
        </div>
        <div className="bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 rounded-xl p-4 shadow-xs">
          <div className="text-xs text-slate-500 dark:text-slate-400">SaaS Studio Agents</div>
          <div className="text-2xl font-bold text-blue-600 dark:text-blue-400 mt-1">{saasCount}</div>
        </div>
        <div className="bg-white dark:bg-slate-800/80 border border-slate-200 dark:border-slate-700/60 rounded-xl p-4 shadow-xs">
          <div className="text-xs text-slate-500 dark:text-slate-400">Media Studio Agents</div>
          <div className="text-2xl font-bold text-purple-600 dark:text-purple-400 mt-1">{mediaCount}</div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between bg-white dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl p-3">
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-72">
            <Search className="absolute left-3 top-2.5 text-slate-400" size={16} />
            <input
              type="text"
              placeholder="Search agents or capabilities..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/60 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        <div className="flex items-center gap-1 w-full sm:w-auto justify-end">
          <span className="text-xs font-medium text-slate-400 mr-2 flex items-center gap-1">
            <Filter size={12} /> Studio:
          </span>
          {(['all', 'saas', 'media'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setSelectedStudio(tab)}
              className={`px-3 py-1.5 text-xs font-semibold rounded-lg capitalize transition-colors ${
                selectedStudio === tab
                  ? 'bg-blue-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-700/60'
              }`}
            >
              {tab === 'all' ? 'All Studios' : tab.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Agents Grid */}
      {loading ? (
        <div className="text-center py-16 text-slate-400 dark:text-slate-500">
          <RotateCw className="animate-spin mx-auto mb-2" size={24} />
          Loading registered agents...
        </div>
      ) : error ? (
        <div className="p-4 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 text-red-700 dark:text-red-400 text-sm">
          {error}
        </div>
      ) : filteredAgents.length === 0 ? (
        <div className="text-center py-16 text-slate-400 dark:text-slate-500 border border-dashed border-slate-200 dark:border-slate-700 rounded-xl">
          No agents found matching your query.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredAgents.map(agent => (
            <div
              key={agent.id}
              className={`bg-white dark:bg-slate-800/80 border rounded-xl p-5 shadow-xs transition-all hover:border-slate-400 dark:hover:border-slate-600 flex flex-col justify-between ${
                agent.is_enabled
                  ? 'border-slate-200 dark:border-slate-700/70'
                  : 'border-slate-200 dark:border-slate-800 opacity-60 bg-slate-50/50 dark:bg-slate-900/40'
              }`}
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5">
                    <div
                      className={`p-2 rounded-lg ${
                        agent.studio_type === 'saas'
                          ? 'bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400'
                          : 'bg-purple-50 dark:bg-purple-950/50 text-purple-600 dark:text-purple-400'
                      }`}
                    >
                      <Bot size={20} />
                    </div>
                    <div>
                      <h3 className="font-semibold text-slate-900 dark:text-white text-sm">
                        {agent.name}
                      </h3>
                      <span className="text-[11px] font-mono text-slate-400 dark:text-slate-500">
                        {agent.slug}
                      </span>
                    </div>
                  </div>

                  <span
                    className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded-full border ${
                      agent.studio_type === 'saas'
                        ? 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800'
                        : 'bg-purple-50 text-purple-600 border-purple-200 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-800'
                    }`}
                  >
                    {agent.studio_type}
                  </span>
                </div>

                <p className="text-xs text-slate-600 dark:text-slate-300 mt-3 line-clamp-2 leading-relaxed">
                  {agent.description}
                </p>

                <div className="mt-4 space-y-2">
                  <div className="flex flex-wrap gap-1.5">
                    {agent.capabilities.map(cap => (
                      <span
                        key={cap}
                        className="text-[11px] px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700/60 text-slate-700 dark:text-slate-300 font-mono"
                      >
                        {cap}
                      </span>
                    ))}
                  </div>

                  <div className="flex items-center gap-3 text-[11px] text-slate-400 dark:text-slate-500 pt-2 border-t border-slate-100 dark:border-slate-700/50">
                    <span className="flex items-center gap-1">
                      <Cpu size={12} />
                      {agent.model_config_data?.model_id || 'claude-haiku-5-5'}
                    </span>
                    <span className="flex items-center gap-1">
                      <Wrench size={12} />
                      {agent.available_tools.length} tool(s)
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-700/60 flex items-center justify-between">
                <button
                  onClick={() => setSelectedAgent(agent)}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-600 dark:text-blue-400 hover:underline"
                >
                  <Eye size={14} />
                  Inspect Specs
                </button>

                <button
                  onClick={() => handleToggleStatus(agent)}
                  disabled={updatingId === agent.id}
                  className={`inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-md font-medium transition-colors ${
                    agent.is_enabled
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/60'
                      : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                  }`}
                >
                  {agent.is_enabled ? (
                    <>
                      <CheckCircle size={12} /> Enabled
                    </>
                  ) : (
                    <>
                      <XCircle size={12} /> Disabled
                    </>
                  )}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Agent Inspector Modal */}
      {selectedAgent && (
        <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400">
                  <Bot size={24} />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900 dark:text-white flex items-center gap-2">
                    {selectedAgent.name}
                    <span className="text-xs font-mono font-normal text-slate-400">
                      v{selectedAgent.version}
                    </span>
                  </h2>
                  <p className="text-xs text-slate-500 font-mono">{selectedAgent.slug}</p>
                </div>
              </div>
              <button
                onClick={() => setSelectedAgent(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            <div className="p-5 overflow-y-auto space-y-5 text-sm">
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1.5">
                  Role Description
                </h4>
                <p className="text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg border border-slate-200 dark:border-slate-700/60 leading-relaxed text-xs">
                  {selectedAgent.description}
                </p>
              </div>

              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center gap-1.5">
                  <FileCode size={14} /> System Instructions & Directives
                </h4>
                <pre className="text-xs font-mono bg-slate-950 text-slate-200 p-3.5 rounded-lg border border-slate-800 overflow-x-auto whitespace-pre-wrap leading-relaxed">
                  {selectedAgent.instructions}
                </pre>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center gap-1.5">
                    <Layers size={14} /> Output Contract Schema
                  </h4>
                  <pre className="text-[11px] font-mono bg-slate-950 text-emerald-400 p-3 rounded-lg border border-slate-800 overflow-x-auto max-h-40">
                    {JSON.stringify(selectedAgent.output_schema, null, 2)}
                  </pre>
                </div>
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center gap-1.5">
                    <ShieldAlert size={14} /> Verification Criteria
                  </h4>
                  <div className="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg border border-slate-200 dark:border-slate-700/60 space-y-1.5 max-h-40 overflow-y-auto">
                    {selectedAgent.verification_requirements.map((req, i) => (
                      <div key={i} className="text-xs text-slate-600 dark:text-slate-300 font-mono flex items-center gap-1.5">
                        <CheckCircle size={12} className="text-blue-500" />
                        {req}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            <div className="p-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 flex items-center justify-between">
              <div className="text-xs text-slate-400 font-mono">
                Model: {selectedAgent.model_config_data?.model_id} (Timeout: {selectedAgent.execution_config?.timeout_seconds}s)
              </div>
              <button
                onClick={() => setSelectedAgent(null)}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
