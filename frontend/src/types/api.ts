export type StudioType = 'saas' | 'media';
export type ProjectStatus = 'active' | 'paused' | 'completed' | 'archived';
export type TaskStatus = 'pending' | 'in_progress' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled';
export type ExecutionStatus = 'pending' | 'running' | 'paused' | 'waiting_approval' | 'completed' | 'failed' | 'cancelled';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected';
export type RiskLevel = 'low' | 'medium' | 'high';

export interface Project {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  description: string | null;
  studio_type: StudioType;
  status: ProjectStatus;
  target_objectives: string[];
  settings_json: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string | null;
  executor_type: string;
  assigned_model: string;
  risk_level: RiskLevel;
  priority: number;
  dependency_ids: string[];
  input_data: Record<string, any>;
  output_data: Record<string, any>;
  status: TaskStatus;
  error_details: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExecutionEvent {
  id: string;
  execution_id: string;
  event_type: string;
  payload: Record<string, any>;
  created_at: string;
}

export interface Execution {
  id: string;
  workflow_id: string;
  project_id: string;
  status: ExecutionStatus;
  current_step: number;
  state_data: Record<string, any>;
  checkpoint_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  events: ExecutionEvent[];
}

export interface Approval {
  id: string;
  execution_id: string;
  task_id: string | null;
  action_type: string;
  description: string;
  risk_level: RiskLevel;
  status: ApprovalStatus;
  context_data: Record<string, any>;
  decision_reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface Artifact {
  id: string;
  project_id: string;
  execution_id: string | null;
  task_id: string | null;
  name: string;
  file_path: string;
  artifact_type: string;
  mime_type: string;
  file_size_bytes: number;
  version?: number;
  parent_artifact_id?: string | null;
  superseded_by_id?: string | null;
  verification_status?: string;
  verification_details?: Record<string, any>;
  metadata_json: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface ModelExecution {
  id: string;
  execution_id: string | null;
  task_id: string | null;
  provider: string;
  model: string;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cost_usd: number;
  exit_code: number;
  status: string;
  raw_metrics: Record<string, any>;
  created_at: string;
}

export interface UsageSummary {
  total_executions: number;
  successful_executions: number;
  failed_executions: number;
  total_duration_ms: number;
  total_tokens: number;
  total_cost_usd: number;
}

export interface ProjectStats {
  total_projects: number;
  active_projects: number;
  total_tasks: number;
  total_executions: number;
  total_artifacts: number;
}

export interface PlannedTask {
  task_id: string;
  title: string;
  description: string;
  assigned_agent_slug?: string;
  executor_type: string;
  assigned_model: string;
  risk_level: RiskLevel;
  requires_approval: boolean;
  priority: number;
  dependencies: string[];
  expected_output_artifacts: string[];
  acceptance_criteria: string[];
  verification_criteria?: string[];
}

export interface StructuredPlan {
  plan_id: string;
  project_id: string;
  objective: string;
  studio_type: StudioType;
  strategy_summary: string;
  estimated_cost_usd: number;
  selected_agent_slugs?: string[];
  tasks: PlannedTask[];
  execution_stages?: string[][];
  is_valid_dag?: boolean;
}

export interface Agent {
  id: string;
  slug: string;
  name: string;
  description: string;
  studio_type: StudioType;
  capabilities: string[];
  instructions: string;
  input_schema: Record<string, any>;
  output_schema: Record<string, any>;
  available_tools: string[];
  model_config_data: Record<string, any>;
  execution_config: Record<string, any>;
  verification_requirements: string[];
  version: string;
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ObjectiveUnderstanding {
  objective_summary: string;
  studio: StudioType;
  project_context: string;
  intended_outcome: string;
  required_capabilities: string[];
  relevant_constraints: string[];
  expected_deliverables: string[];
  complexity: 'low' | 'medium' | 'high';
  ambiguities: string[];
  missing_information: string[];
  potential_risks: string[];
  needs_clarification: boolean;
  clarification_questions: string[];
}

export type MemoryCategory =
  | 'objective'
  | 'decision'
  | 'requirement'
  | 'constraint'
  | 'discovery'
  | 'preference'
  | 'question'
  | 'risk'
  | 'milestone';

export type MemoryProvenanceType =
  | 'user_provided'
  | 'verified_finding'
  | 'agent_conclusion'
  | 'assumption';

export type MemoryStatus =
  | 'active'
  | 'proposed'
  | 'superseded'
  | 'rejected'
  | 'archived';

export type MemoryConflictStatus = 'none' | 'detected' | 'resolved';

export type MemoryAuditAction =
  | 'created'
  | 'updated'
  | 'verified'
  | 'archived'
  | 'restored'
  | 'conflict_resolved'
  | 'purged';

export interface ProjectMemory {
  id: string;
  project_id: string;
  category: MemoryCategory;
  summary: string;
  content: string;
  provenance_type: MemoryProvenanceType;
  confidence_score: number;
  is_verified: boolean;
  verified_at: string | null;
  source_execution_id: string | null;
  source_task_id: string | null;
  source_artifact_id: string | null;
  source_agent_slug: string | null;
  status: MemoryStatus;
  revision: number;
  previous_revision_id: string | null;
  conflict_status: MemoryConflictStatus;
  conflicting_memory_id: string | null;
  metadata_json: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface MemoryConflictItem {
  memory_id: string;
  summary: string;
  category: MemoryCategory;
  status: MemoryStatus;
  revision: number;
  provenance_type: MemoryProvenanceType;
  conflict_status: MemoryConflictStatus;
  conflicting_memory_id: string | null;
  partner_summary: string | null;
  partner_status: MemoryStatus | null;
  partner_provenance_type: MemoryProvenanceType | null;
  partner_revision: number | null;
  created_at: string;
}

export interface MemoryAuditLog {
  id: string;
  memory_id: string | null;
  project_id: string;
  action: MemoryAuditAction;
  actor_type: string;
  actor_id: string | null;
  reason: string | null;
  previous_state: Record<string, any> | null;
  new_state: Record<string, any> | null;
  created_at: string;
}

export interface MemoryStats {
  total_active: number;
  verified_findings: number;
  agent_conclusions: number;
  assumptions: number;
  open_conflicts: number;
  archived: number;
}

export interface ArtifactLineage {
  artifact: Artifact;
  parent: Artifact | null;
  ancestors: Artifact[];
  descendants: Artifact[];
  superseded_by: Artifact | null;
  supersedes: Artifact[];
}

// Execution budget governor (mirrors backend/app/schemas/budget.py)
export type BudgetStatus = 'active' | 'warning' | 'exhausted' | 'completed' | 'cancelled';

export interface BudgetConsumed {
  cost_usd: number;
  actual_cost_usd: number;
  estimated_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  runtime_seconds: number;
  agent_attempts: number;
  remediation_turns: number;
  replan_count: number;
}

export interface BudgetReserved {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  active_reservations: number;
}

export interface BudgetLimits {
  max_cost_usd: number | null;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  max_total_tokens: number | null;
  max_agent_attempts: number | null;
  max_task_attempts: number | null;
  max_remediation_turns: number | null;
  max_replan_count: number | null;
  max_runtime_seconds: number | null;
}

export interface BudgetSummary {
  budget_id: string;
  execution_id: string;
  status: BudgetStatus;
  exhaustion_reason: string | null;
  is_cost_estimated: boolean;
  limits: BudgetLimits;
  consumed: BudgetConsumed;
  reserved: BudgetReserved;
  remaining: Partial<Record<keyof BudgetLimits, number | null>>;
  utilization: Record<string, number | null>;
}

/** Partial update. Omitted keys keep their value; explicit null clears a limit. */
export type BudgetLimitsUpdate = Partial<BudgetLimits>;

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}
