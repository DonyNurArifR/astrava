import type {
  Approval,
  Artifact,
  Execution,
  ModelExecution,
  Project,
  ProjectStats,
  StructuredPlan,
  StudioType,
  Task,
  UsageSummary,
} from '../types/api';

const API_BASE = '/api/v1';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const errorText = await res.text();
    let detail = errorText;
    try {
      const parsed = JSON.parse(errorText);
      detail = parsed.detail || errorText;
    } catch {
      // Keep raw text
    }
    throw new Error(detail || `HTTP Error ${res.status}`);
  }
  if (res.status === 204) {
    return {} as T;
  }
  return res.json();
}

export const api = {
  // Health
  getHealth: () => fetch(`${API_BASE}/healthz`).then(r => handleResponse<any>(r)),
  getReadiness: () => fetch(`${API_BASE}/readyz`).then(r => handleResponse<any>(r)),

  // Projects
  getProjects: (studioType?: string) => {
    const url = studioType ? `${API_BASE}/projects?studio_type=${studioType}` : `${API_BASE}/projects`;
    return fetch(url).then(r => handleResponse<Project[]>(r));
  },
  getProject: (id: string) => fetch(`${API_BASE}/projects/${id}`).then(r => handleResponse<Project>(r)),
  getProjectStats: () => fetch(`${API_BASE}/projects/stats`).then(r => handleResponse<ProjectStats>(r)),
  createProject: (data: { name: string; description?: string; studio_type: StudioType; target_objectives?: string[] }) =>
    fetch(`${API_BASE}/projects`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => handleResponse<Project>(r)),
  deleteProject: (id: string) =>
    fetch(`${API_BASE}/projects/${id}`, { method: 'DELETE' }).then(r => handleResponse<void>(r)),

  // Tasks
  getTasksByProject: (projectId: string) =>
    fetch(`${API_BASE}/tasks/project/${projectId}`).then(r => handleResponse<Task[]>(r)),
  createTask: (data: Partial<Task>) =>
    fetch(`${API_BASE}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => handleResponse<Task>(r)),

  // Executions
  getExecutions: (projectId?: string) => {
    const url = projectId ? `${API_BASE}/executions?project_id=${projectId}` : `${API_BASE}/executions`;
    return fetch(url).then(r => handleResponse<Execution[]>(r));
  },
  getExecution: (id: string) => fetch(`${API_BASE}/executions/${id}`).then(r => handleResponse<Execution>(r)),
  pauseExecution: (id: string) =>
    fetch(`${API_BASE}/executions/${id}/pause`, { method: 'POST' }).then(r => handleResponse<Execution>(r)),
  resumeExecution: (id: string) =>
    fetch(`${API_BASE}/executions/${id}/resume`, { method: 'POST' }).then(r => handleResponse<Execution>(r)),

  // Approvals
  getApprovals: (pendingOnly = false) =>
    fetch(`${API_BASE}/approvals?pending_only=${pendingOnly}`).then(r => handleResponse<Approval[]>(r)),
  decideApproval: (id: string, decision: 'approved' | 'rejected', reason?: string) =>
    fetch(`${API_BASE}/approvals/${id}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, reason, decided_by: 'Abstract' }),
    }).then(r => handleResponse<Approval>(r)),

  // Artifacts
  getArtifactsByProject: (projectId: string) =>
    fetch(`${API_BASE}/artifacts/project/${projectId}`).then(r => handleResponse<Artifact[]>(r)),
  previewArtifact: (id: string) =>
    fetch(`${API_BASE}/artifacts/${id}/preview`).then(r => {
      if (!r.ok) throw new Error('Failed to preview artifact');
      return r.text();
    }),
  getDownloadUrl: (id: string) => `${API_BASE}/artifacts/${id}/download`,

  // Intelligence & Usage
  getUsageSummary: () => fetch(`${API_BASE}/intelligence/summary`).then(r => handleResponse<UsageSummary>(r)),
  getModelExecutions: () => fetch(`${API_BASE}/intelligence/usage`).then(r => handleResponse<ModelExecution[]>(r)),

  // Orchestrator
  generatePlan: (projectId: string, objective: string, studioType: StudioType) =>
    fetch(`${API_BASE}/orchestrator/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, objective, studio_type: studioType }),
    }).then(r => handleResponse<StructuredPlan>(r)),
  executePipeline: (projectId: string, objective: string, studioType: StudioType) =>
    fetch(`${API_BASE}/orchestrator/execute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_id: projectId, objective, studio_type: studioType }),
    }).then(r => handleResponse<Execution>(r)),
  resumePipeline: (executionId: string, decision: 'approved' | 'rejected', reason?: string) =>
    fetch(`${API_BASE}/orchestrator/resume/${executionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, reason, decided_by: 'Abstract' }),
    }).then(r => handleResponse<Execution>(r)),
};
