import type {
  Agent,
  Approval,
  Artifact,
  ArtifactLineage,
  BudgetLimitsUpdate,
  BudgetSummary,
  Execution,
  MemoryAuditLog,
  MemoryConflictItem,
  MemoryStats,
  ModelExecution,
  ObjectiveUnderstanding,
  PaginatedResponse,
  Project,
  ProjectMemory,
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
  getExecutionBudget: (executionId: string): Promise<BudgetSummary> =>
    fetch(`${API_BASE}/executions/${executionId}/budget`).then(r => handleResponse<BudgetSummary>(r)),
  increaseExecutionBudget: (executionId: string, limits: BudgetLimitsUpdate): Promise<BudgetSummary> =>
    fetch(`${API_BASE}/executions/${executionId}/budget/increase`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(limits),
    }).then(r => handleResponse<BudgetSummary>(r)),

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
  understandObjective: (objective: string, studioType?: StudioType, projectId?: string) =>
    fetch(`${API_BASE}/orchestrator/understand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ objective, studio_type: studioType, project_id: projectId }),
    }).then(r => handleResponse<ObjectiveUnderstanding>(r)),
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

  // Agent Registry
  getAgents: (studioType?: string, isEnabled?: boolean) => {
    let url = `${API_BASE}/agents`;
    const params = new URLSearchParams();
    if (studioType) params.append('studio_type', studioType);
    if (isEnabled !== undefined) params.append('is_enabled', String(isEnabled));
    const qs = params.toString();
    if (qs) url += `?${qs}`;
    return fetch(url).then(r => handleResponse<Agent[]>(r));
  },
  getAgent: (idOrSlug: string) =>
    fetch(`${API_BASE}/agents/${idOrSlug}`).then(r => handleResponse<Agent>(r)),
  updateAgentStatus: (idOrSlug: string, isEnabled: boolean) =>
    fetch(`${API_BASE}/agents/${idOrSlug}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_enabled: isEnabled }),
    }).then(r => handleResponse<Agent>(r)),
  seedAgents: () =>
    fetch(`${API_BASE}/agents/seed`, { method: 'POST' }).then(r => handleResponse<any>(r)),

  // Project Memory & Intelligence
  getMemoryStats: (projectId: string) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/stats`).then(r => handleResponse<MemoryStats>(r)),

  getMemories: (
    projectId: string,
    params?: {
      category?: string;
      provenance?: string;
      status?: string;
      is_verified?: boolean;
      conflict_status?: string;
      search?: string;
      include_historical?: boolean;
      page?: number;
      page_size?: number;
      sort_by?: string;
      sort_order?: string;
    }
  ) => {
    const qs = new URLSearchParams();
    if (params?.category) qs.append('category', params.category);
    if (params?.provenance) qs.append('provenance', params.provenance);
    if (params?.status) qs.append('status', params.status);
    if (params?.is_verified !== undefined) qs.append('is_verified', String(params.is_verified));
    if (params?.conflict_status) qs.append('conflict_status', params.conflict_status);
    if (params?.search) qs.append('search', params.search);
    if (params?.include_historical) qs.append('include_historical', String(params.include_historical));
    if (params?.page) qs.append('page', String(params.page));
    if (params?.page_size) qs.append('page_size', String(params.page_size));
    if (params?.sort_by) qs.append('sort_by', params.sort_by);
    if (params?.sort_order) qs.append('sort_order', params.sort_order);
    const query = qs.toString();
    const url = `${API_BASE}/projects/${projectId}/memories${query ? `?${query}` : ''}`;
    return fetch(url).then(r => handleResponse<PaginatedResponse<ProjectMemory>>(r));
  },

  getMemory: (projectId: string, memoryId: string) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/${memoryId}`).then(r => handleResponse<ProjectMemory>(r)),

  createMemory: (
    projectId: string,
    data: {
      category: string;
      summary: string;
      content: string;
      provenance_type?: string;
      confidence_score?: number;
      metadata_json?: Record<string, any>;
    }
  ) =>
    fetch(`${API_BASE}/projects/${projectId}/memories`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => handleResponse<ProjectMemory>(r)),

  updateMemory: (
    projectId: string,
    memoryId: string,
    data: {
      expected_revision: number;
      summary?: string;
      content?: string;
      metadata_json?: Record<string, any>;
      reason?: string;
    }
  ) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/${memoryId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => handleResponse<ProjectMemory>(r)),

  archiveMemory: (projectId: string, memoryId: string, reason?: string) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/${memoryId}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }).then(r => handleResponse<ProjectMemory>(r)),

  restoreMemory: (projectId: string, memoryId: string, reason?: string) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/${memoryId}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }).then(r => handleResponse<ProjectMemory>(r)),

  verifyMemory: (
    projectId: string,
    memoryId: string,
    data: {
      verified_by: string;
      reason?: string;
      verification_details?: Record<string, any>;
    }
  ) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/${memoryId}/verify`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(data.verified_by ? { 'X-ASTRAVA-ACTOR-NAME': data.verified_by } : {}),
      },
      body: JSON.stringify(data),
    }).then(r => handleResponse<ProjectMemory>(r)),

  getConflicts: (projectId: string, category?: string, page?: number, page_size?: number) => {
    const qs = new URLSearchParams();
    if (category) qs.append('category', category);
    if (page) qs.append('page', String(page));
    if (page_size) qs.append('page_size', String(page_size));
    const query = qs.toString();
    const url = `${API_BASE}/projects/${projectId}/memories/conflicts${query ? `?${query}` : ''}`;
    return fetch(url).then(r => handleResponse<PaginatedResponse<MemoryConflictItem>>(r));
  },

  resolveConflict: (
    projectId: string,
    memoryId: string,
    data: {
      resolution: 'supersede' | 'reject' | 'merge';
      reason: string;
      actor_id?: string;
      merged_summary?: string;
      merged_content?: string;
    }
  ) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/${memoryId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }).then(r => handleResponse<ProjectMemory>(r)),

  getMemoryRevisions: (projectId: string, memoryId: string) =>
    fetch(`${API_BASE}/projects/${projectId}/memories/${memoryId}/revisions`).then(r =>
      handleResponse<ProjectMemory[]>(r)
    ),

  getMemoryAudit: (
    projectId: string,
    memoryId: string,
    order: 'asc' | 'desc' = 'desc',
    page = 1,
    page_size = 50
  ) =>
    fetch(
      `${API_BASE}/projects/${projectId}/memories/${memoryId}/audit?order=${order}&page=${page}&page_size=${page_size}`
    ).then(r => handleResponse<PaginatedResponse<MemoryAuditLog>>(r)),

  getArtifactLineage: (projectId: string, artifactId: string) =>
    fetch(`${API_BASE}/projects/${projectId}/artifacts/${artifactId}/lineage`).then(r =>
      handleResponse<ArtifactLineage>(r)
    ),
};
