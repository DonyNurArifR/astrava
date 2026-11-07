
import type {
  Agent,
  AgentMetrics,
  Approval,
  Artifact,
  ArtifactLineage,
  BudgetLimitsUpdate,
  BudgetSummary,
  Execution,
  GitDiffResult,
  GoalCreate,
  GoalUpdate,
  LoginResponse,
  MemoryAuditLog,
  MemoryConflictItem,
  MemoryStats,
  ModelExecution,
  ObjectiveUnderstanding,
  PaginatedResponse,
  Project,
  ProjectGoal,
  ProjectMemory,
  ProjectStats,
  RemediationSummary,
  RepoScanResult,
  SessionStatus,
  StructuredPlan,
  StudioType,
  Task,
  UsageSummary,
} from '../types/api';

import { AUTH_REQUIRED_EVENT, getCsrfToken } from './session';

export { AUTH_REQUIRED_EVENT, clearCsrfToken, setCsrfToken } from './session';

const API_BASE = '/api/v1';

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** Error raised for non-2xx responses. `message` matches the previous plain Error behaviour. */
export class ApiError extends Error {
  readonly status: number;
  readonly retryAfterSeconds: number | null;

  constructor(message: string, status: number, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

interface RequestOptions {
  /** Auth endpoints opt out: a 401 there is an answer (wrong key), not an expired session. */
  notifyAuthRequired?: boolean;
}

/**
 * The single transport for every API call. Same-origin credentials, CSRF header on unsafe
 * methods, and a 401 event so the UI can return to the sign-in screen.
 */
async function request(path: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  const csrfToken = getCsrfToken();
  if (UNSAFE_METHODS.has(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    method,
    headers,
    credentials: 'same-origin',
  });
  if (res.status === 401 && options.notifyAuthRequired !== false) {
    window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
  }
  return res;
}

function parseRetryAfter(res: Response): number | null {
  const raw = res.headers.get('Retry-After');
  if (!raw) return null;
  const seconds = Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

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
    throw new ApiError(detail || `HTTP Error ${res.status}`, res.status, parseRetryAfter(res));
  }
  if (res.status === 204) {
    return {} as T;
  }
  return res.json();
}

const jsonHeaders = { 'Content-Type': 'application/json' };

export const api = {
  // Session (M1.5-1a)
  getSession: () =>
    request('/auth/session', {}, { notifyAuthRequired: false }).then(r => handleResponse<SessionStatus>(r)),
  login: (apiKey: string) =>
    request(
      '/auth/login',
      { method: 'POST', headers: jsonHeaders, body: JSON.stringify({ api_key: apiKey }) },
      { notifyAuthRequired: false }
    ).then(r => handleResponse<LoginResponse>(r)),
  logout: () =>
    request('/auth/logout', { method: 'POST' }, { notifyAuthRequired: false }).then(r =>
      handleResponse<{ authenticated: boolean }>(r)
    ),

  // Health
  getHealth: () => request('/healthz').then(r => handleResponse<any>(r)),
  getReadiness: () => request('/readyz').then(r => handleResponse<any>(r)),

  // Projects
  getProjects: (studioType?: string) => {
    const path = studioType ? `/projects?studio_type=${studioType}` : `/projects`;
    return request(path).then(r => handleResponse<Project[]>(r));
  },
  getProject: (id: string) => request(`/projects/${id}`).then(r => handleResponse<Project>(r)),
  getProjectStats: () => request(`/projects/stats`).then(r => handleResponse<ProjectStats>(r)),
  createProject: (data: { name: string; description?: string; studio_type: StudioType; target_objectives?: string[] }) =>
    request(`/projects`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(data),
    }).then(r => handleResponse<Project>(r)),
  deleteProject: (id: string) =>
    request(`/projects/${id}`, { method: 'DELETE' }).then(r => handleResponse<void>(r)),

  // Tasks
  getTasksByProject: (projectId: string) =>
    request(`/tasks/project/${projectId}`).then(r => handleResponse<Task[]>(r)),
  createTask: (data: Partial<Task>) =>
    request(`/tasks`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(data),
    }).then(r => handleResponse<Task>(r)),

  // Executions
  getExecutions: (projectId?: string) => {
    const path = projectId ? `/executions?project_id=${projectId}` : `/executions`;
    return request(path).then(r => handleResponse<Execution[]>(r));
  },
  getExecution: (id: string) => request(`/executions/${id}`).then(r => handleResponse<Execution>(r)),
  pauseExecution: (id: string) =>
    request(`/executions/${id}/pause`, { method: 'POST' }).then(r => handleResponse<Execution>(r)),
  resumeExecution: (id: string) =>
    request(`/executions/${id}/resume`, { method: 'POST' }).then(r => handleResponse<Execution>(r)),
  getExecutionBudget: (executionId: string): Promise<BudgetSummary> =>
    request(`/executions/${executionId}/budget`).then(r => handleResponse<BudgetSummary>(r)),
  increaseExecutionBudget: (executionId: string, limits: BudgetLimitsUpdate): Promise<BudgetSummary> =>
    request(`/executions/${executionId}/budget/increase`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(limits),
    }).then(r => handleResponse<BudgetSummary>(r)),
  getExecutionRemediations: (executionId: string): Promise<RemediationSummary> =>
    request(`/executions/${executionId}/remediations`).then(r => handleResponse<RemediationSummary>(r)),

  // Approvals
  getApprovals: (pendingOnly = false) =>
    request(`/approvals?pending_only=${pendingOnly}`).then(r => handleResponse<Approval[]>(r)),
  // The approver identity is derived server-side from the operator session.
  decideApproval: (id: string, decision: 'approved' | 'rejected', reason?: string) =>
    request(`/approvals/${id}/decide`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ decision, reason }),
    }).then(r => handleResponse<Approval>(r)),

  // Artifacts
  getArtifactsByProject: (projectId: string) =>
    request(`/artifacts/project/${projectId}`).then(r => handleResponse<Artifact[]>(r)),
  previewArtifact: (id: string) =>
    request(`/artifacts/${id}/preview`).then(r => {
      if (!r.ok) throw new Error('Failed to preview artifact');
      return r.text();
    }),
  getDownloadUrl: (id: string) => `${API_BASE}/artifacts/${id}/download`,

  // Intelligence & Usage
  getUsageSummary: () => request(`/intelligence/summary`).then(r => handleResponse<UsageSummary>(r)),
  getModelExecutions: () => request(`/intelligence/usage`).then(r => handleResponse<ModelExecution[]>(r)),

  // Orchestrator
  understandObjective: (objective: string, studioType?: StudioType, projectId?: string) =>
    request(`/orchestrator/understand`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ objective, studio_type: studioType, project_id: projectId }),
    }).then(r => handleResponse<ObjectiveUnderstanding>(r)),
  generatePlan: (projectId: string, objective: string, studioType: StudioType) =>
    request(`/orchestrator/plan`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ project_id: projectId, objective, studio_type: studioType }),
    }).then(r => handleResponse<StructuredPlan>(r)),
  executePipeline: (projectId: string, objective: string, studioType: StudioType) =>
    request(`/orchestrator/execute`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ project_id: projectId, objective, studio_type: studioType }),
    }).then(r => handleResponse<Execution>(r)),
  resumePipeline: (executionId: string, decision: 'approved' | 'rejected', reason?: string) =>
    request(`/orchestrator/resume/${executionId}`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ decision, reason }),
    }).then(r => handleResponse<Execution>(r)),

  // Agent Registry
  getAgents: (studioType?: string, isEnabled?: boolean) => {
    let path = `/agents`;
    const params = new URLSearchParams();
    if (studioType) params.append('studio_type', studioType);
    if (isEnabled !== undefined) params.append('is_enabled', String(isEnabled));
    const qs = params.toString();
    if (qs) path += `?${qs}`;
    return request(path).then(r => handleResponse<Agent[]>(r));
  },
  getAgent: (idOrSlug: string) => request(`/agents/${idOrSlug}`).then(r => handleResponse<Agent>(r)),
  updateAgentStatus: (idOrSlug: string, isEnabled: boolean) =>
    request(`/agents/${idOrSlug}/status`, {
      method: 'PATCH',
      headers: jsonHeaders,
      body: JSON.stringify({ is_enabled: isEnabled }),
    }).then(r => handleResponse<Agent>(r)),
  seedAgents: () => request(`/agents/seed`, { method: 'POST' }).then(r => handleResponse<any>(r)),

  // Project Memory & Intelligence
  getMemoryStats: (projectId: string) =>
    request(`/projects/${projectId}/memories/stats`).then(r => handleResponse<MemoryStats>(r)),

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
    const path = `/projects/${projectId}/memories${query ? `?${query}` : ''}`;
    return request(path).then(r => handleResponse<PaginatedResponse<ProjectMemory>>(r));
  },

  getMemory: (projectId: string, memoryId: string) =>
    request(`/projects/${projectId}/memories/${memoryId}`).then(r => handleResponse<ProjectMemory>(r)),

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
    request(`/projects/${projectId}/memories`, {
      method: 'POST',
      headers: jsonHeaders,
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
    request(`/projects/${projectId}/memories/${memoryId}`, {
      method: 'PATCH',
      headers: jsonHeaders,
      body: JSON.stringify(data),
    }).then(r => handleResponse<ProjectMemory>(r)),

  archiveMemory: (projectId: string, memoryId: string, reason?: string) =>
    request(`/projects/${projectId}/memories/${memoryId}/archive`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ reason }),
    }).then(r => handleResponse<ProjectMemory>(r)),

  restoreMemory: (projectId: string, memoryId: string, reason?: string) =>
    request(`/projects/${projectId}/memories/${memoryId}/restore`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ reason }),
    }).then(r => handleResponse<ProjectMemory>(r)),

  // The verifier is derived server-side and returned in the memory's metadata_json.
  verifyMemory: (
    projectId: string,
    memoryId: string,
    data: {
      reason?: string;
      verification_details?: Record<string, any>;
    }
  ) =>
    request(`/projects/${projectId}/memories/${memoryId}/verify`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ reason: data.reason, verification_details: data.verification_details }),
    }).then(r => handleResponse<ProjectMemory>(r)),

  getConflicts: (projectId: string, category?: string, page?: number, page_size?: number) => {
    const qs = new URLSearchParams();
    if (category) qs.append('category', category);
    if (page) qs.append('page', String(page));
    if (page_size) qs.append('page_size', String(page_size));
    const query = qs.toString();
    const path = `/projects/${projectId}/memories/conflicts${query ? `?${query}` : ''}`;
    return request(path).then(r => handleResponse<PaginatedResponse<MemoryConflictItem>>(r));
  },

  resolveConflict: (
    projectId: string,
    memoryId: string,
    data: {
      resolution: 'supersede' | 'reject' | 'merge';
      reason: string;
      merged_summary?: string;
      merged_content?: string;
    }
  ) =>
    request(`/projects/${projectId}/memories/${memoryId}/resolve`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({
        resolution: data.resolution,
        reason: data.reason,
        merged_summary: data.merged_summary,
        merged_content: data.merged_content,
      }),
    }).then(r => handleResponse<ProjectMemory>(r)),

  getMemoryRevisions: (projectId: string, memoryId: string) =>
    request(`/projects/${projectId}/memories/${memoryId}/revisions`).then(r =>
      handleResponse<ProjectMemory[]>(r)
    ),

  getMemoryAudit: (
    projectId: string,
    memoryId: string,
    order: 'asc' | 'desc' = 'desc',
    page = 1,
    page_size = 50
  ) =>
    request(
      `/projects/${projectId}/memories/${memoryId}/audit?order=${order}&page=${page}&page_size=${page_size}`
    ).then(r => handleResponse<PaginatedResponse<MemoryAuditLog>>(r)),

  getArtifactLineage: (projectId: string, artifactId: string) =>
    request(`/projects/${projectId}/artifacts/${artifactId}/lineage`).then(r =>
      handleResponse<ArtifactLineage>(r)
    ),

  // Goals & Adaptive Replanning (M1.4-4)
  getProjectGoals: (projectId: string, status?: string) =>
    request(`/projects/${projectId}/goals${status ? `?status=${status}` : ''}`).then(r =>
      handleResponse<ProjectGoal[]>(r)
    ),

  createProjectGoal: (projectId: string, data: GoalCreate) =>
    request(`/projects/${projectId}/goals`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(data),
    }).then(r => handleResponse<ProjectGoal>(r)),

  updateProjectGoal: (projectId: string, goalId: string, data: GoalUpdate) =>
    request(`/projects/${projectId}/goals/${goalId}`, {
      method: 'PATCH',
      headers: jsonHeaders,
      body: JSON.stringify(data),
    }).then(r => handleResponse<ProjectGoal>(r)),

  executeGoal: (projectId: string, goalId: string) =>
    request(`/projects/${projectId}/goals/${goalId}/execute`, {
      method: 'POST',
    }).then(r => handleResponse<Execution>(r)),

  replanExecution: (executionId: string, data: { reason: string; new_tasks?: any[] }) =>
    request(`/executions/${executionId}/replan`, {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(data),
    }).then(r => handleResponse<Execution>(r)),

  // Git Worktree Sandboxing & Repo Scanning (M1.4-5)
  getExecutionDiff: (executionId: string) =>
    request(`/executions/${executionId}/diff`).then(r => handleResponse<GitDiffResult>(r)),

  mergeExecutionWorktree: (executionId: string) =>
    request(`/executions/${executionId}/merge`, {
      method: 'POST',
      headers: jsonHeaders,
    }).then(r =>
      handleResponse<{
        success: boolean;
        message: string;
        branch: string;
        target_branch: string;
        output: string;
      }>(r)
    ),

  scanProjectRepo: (projectId: string) =>
    request(`/projects/${projectId}/scan`).then(r => handleResponse<RepoScanResult>(r)),

  // Agent Observability & Metrics (M1.4-6)
  getAgentMetrics: (slug: string) =>
    request(`/agents/${slug}/metrics`).then(r => handleResponse<AgentMetrics>(r)),

  getAllAgentMetrics: (studioType?: string) =>
    request(`/agents/metrics${studioType ? `?studio_type=${studioType}` : ''}`).then(r =>
      handleResponse<AgentMetrics[]>(r)
    ),
};
