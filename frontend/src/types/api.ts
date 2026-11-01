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
