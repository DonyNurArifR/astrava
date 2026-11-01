import React, { useEffect, useState } from 'react';
import {
  FolderKanban,
  Plus,
  Trash2,
  Code2,
  Video,
  CheckCircle2,
  Calendar,
} from 'lucide-react';
import { api } from '../api/client';
import type { Project, StudioType } from '../types/api';

export const ProjectsPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [filterStudio, setFilterStudio] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [studioType, setStudioType] = useState<StudioType>('saas');
  const [objectives, setObjectives] = useState('');
  const [error, setError] = useState<string | null>(null);

  const loadProjects = () => {
    setLoading(true);
    api
      .getProjects(filterStudio === 'all' ? undefined : filterStudio)
      .then(data => {
        setProjects(data);
        setLoading(false);
      })
      .catch(err => {
        setError(err.message);
        setLoading(false);
      });
  };

  useEffect(() => {
    loadProjects();
  }, [filterStudio]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const targetList = objectives
        .split('\n')
        .map(s => s.trim())
        .filter(Boolean);

      await api.createProject({
        name: name.trim(),
        description: description.trim() || undefined,
        studio_type: studioType,
        target_objectives: targetList,
      });

      setName('');
      setDescription('');
      setObjectives('');
      setShowModal(false);
      loadProjects();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to delete project "${name}"?`)) return;
    try {
      await api.deleteProject(id);
      loadProjects();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">Projects</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Enterprise production workspaces partitioned by SaaS and Media studio pipelines.
          </p>
        </div>

        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold transition-colors shadow-sm"
        >
          <Plus size={15} />
          <span>New Project</span>
        </button>
      </div>

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-xl text-sm">
          {error}
        </div>
      )}

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-800 pb-3">
        {['all', 'saas', 'media'].map(t => (
          <button
            key={t}
            onClick={() => setFilterStudio(t)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold uppercase tracking-wider transition-colors ${
              filterStudio === t
                ? 'bg-slate-900 text-white dark:bg-blue-600'
                : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
            }`}
          >
            {t === 'all' ? 'All Studios' : `${t} Studio`}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="p-12 text-center text-slate-400 text-sm">Loading projects...</div>
      ) : projects.length === 0 ? (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-12 text-center text-slate-400 space-y-3">
          <FolderKanban size={32} className="mx-auto text-slate-300" />
          <p className="text-sm">No projects found for the selected filter.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.map(p => (
            <div
              key={p.id}
              className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm hover:border-slate-300 dark:hover:border-slate-700 transition-all flex flex-col justify-between space-y-4"
            >
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span
                    className={`px-2 py-0.5 text-[10px] font-bold uppercase rounded flex items-center gap-1 ${
                      p.studio_type === 'saas'
                        ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300'
                        : 'bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300'
                    }`}
                  >
                    {p.studio_type === 'saas' ? <Code2 size={11} /> : <Video size={11} />}
                    {p.studio_type}
                  </span>
                  <button
                    onClick={() => handleDelete(p.id, p.name)}
                    className="text-slate-400 hover:text-red-500 p-1 rounded transition-colors"
                    title="Delete project"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>

                <h3 className="font-bold text-base text-slate-900 dark:text-white leading-snug">
                  {p.name}
                </h3>
                {p.description && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                    {p.description}
                  </p>
                )}
              </div>

              {p.target_objectives && p.target_objectives.length > 0 && (
                <div className="space-y-1 pt-2 border-t border-slate-100 dark:border-slate-800">
                  <span className="text-[10px] font-semibold uppercase text-slate-400 block">
                    Target Objectives
                  </span>
                  <ul className="text-xs text-slate-600 dark:text-slate-300 space-y-0.5">
                    {p.target_objectives.slice(0, 2).map((obj, i) => (
                      <li key={i} className="flex items-center gap-1.5 line-clamp-1">
                        <CheckCircle2 size={12} className="text-emerald-500 shrink-0" />
                        <span>{obj}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="pt-3 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1">
                  <Calendar size={12} />
                  {new Date(p.created_at).toLocaleDateString()}
                </span>
                <span className="font-mono">{p.slug}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl max-w-lg w-full p-6 shadow-xl space-y-5">
            <h3 className="font-bold text-lg text-slate-900 dark:text-white">Create New Project</h3>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block mb-1">
                  Project Title
                </label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="e.g. Autonomous Customer Feedback Agent"
                  className="w-full p-2.5 border border-slate-300 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block mb-1">
                  Studio Type
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label
                    className={`flex items-center gap-2 p-2.5 border rounded-lg cursor-pointer text-xs font-semibold ${
                      studioType === 'saas'
                        ? 'border-blue-500 bg-blue-500/10 text-blue-700 dark:text-blue-300'
                        : 'border-slate-300 dark:border-slate-700'
                    }`}
                  >
                    <input
                      type="radio"
                      name="studio"
                      checked={studioType === 'saas'}
                      onChange={() => setStudioType('saas')}
                      className="hidden"
                    />
                    <Code2 size={14} />
                    <span>ASTRAVA SaaS</span>
                  </label>

                  <label
                    className={`flex items-center gap-2 p-2.5 border rounded-lg cursor-pointer text-xs font-semibold ${
                      studioType === 'media'
                        ? 'border-purple-500 bg-purple-500/10 text-purple-700 dark:text-purple-300'
                        : 'border-slate-300 dark:border-slate-700'
                    }`}
                  >
                    <input
                      type="radio"
                      name="studio"
                      checked={studioType === 'media'}
                      onChange={() => setStudioType('media')}
                      className="hidden"
                    />
                    <Video size={14} />
                    <span>ASTRAVA Media</span>
                  </label>
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block mb-1">
                  Description
                </label>
                <textarea
                  rows={2}
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder="Scope, purpose, and key functional outcomes..."
                  className="w-full p-2.5 border border-slate-300 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block mb-1">
                  Target Objectives (one per line)
                </label>
                <textarea
                  rows={3}
                  value={objectives}
                  onChange={e => setObjectives(e.target.value)}
                  placeholder="Automate sentiment classification&#10;Generate technical PRD&#10;Implement webhook listener"
                  className="w-full p-2.5 border border-slate-300 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono text-xs"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-200 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-3.5 py-2 text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg text-xs font-bold hover:bg-blue-500 shadow-sm"
                >
                  Create Project
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
