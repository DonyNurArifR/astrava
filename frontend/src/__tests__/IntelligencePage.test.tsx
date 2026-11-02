import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { IntelligencePage } from '../pages/IntelligencePage';

const mockProjects = [
  { id: 'proj-alpha-123', name: 'ASTRAVA Alpha', studio_type: 'saas' },
  { id: 'proj-beta-456', name: 'ASTRAVA Beta', studio_type: 'developer_tools' },
];

const mockStats = {
  total_active: 12,
  verified_findings: 5,
  agent_conclusions: 6,
  assumptions: 1,
  open_conflicts: 1,
  archived: 2,
};

const mockMemories = [
  {
    id: 'mem-1',
    project_id: 'proj-alpha-123',
    category: 'decision',
    summary: 'Use PostgreSQL with pgvector for persistence',
    content: 'Full relational schema with ACID guarantees and native vector extensions.',
    provenance_type: 'verified_finding',
    confidence_score: 0.95,
    is_verified: true,
    verified_at: '2026-11-01T12:00:00Z',
    source_execution_id: 'exec-1',
    source_task_id: 'task-1',
    source_artifact_id: null,
    source_agent_slug: 'lead_architect',
    status: 'active',
    revision: 2,
    previous_revision_id: 'mem-old-1',
    conflict_status: 'none',
    conflicting_memory_id: null,
    metadata_json: { tags: ['database', 'architecture'] },
    created_at: '2026-11-01T10:00:00Z',
    updated_at: '2026-11-01T12:00:00Z',
  },
  {
    id: 'mem-2',
    project_id: 'proj-alpha-123',
    category: 'requirement',
    summary: 'Strict optimistic concurrency control on memory updates',
    content: 'All memory update mutations must specify expected_revision to guard against race conditions.',
    provenance_type: 'user_provided',
    confidence_score: 1.0,
    is_verified: false,
    verified_at: null,
    source_execution_id: null,
    source_task_id: null,
    source_artifact_id: null,
    source_agent_slug: null,
    status: 'active',
    revision: 1,
    previous_revision_id: null,
    conflict_status: 'none',
    conflicting_memory_id: null,
    metadata_json: {},
    created_at: '2026-11-01T11:00:00Z',
    updated_at: '2026-11-01T11:00:00Z',
  },
];

const mockConflicts = [
  {
    memory_id: 'mem-conf-1',
    summary: 'Database Engine Preference: MongoDB',
    category: 'decision',
    status: 'active',
    revision: 1,
    provenance_type: 'assumption',
    conflict_status: 'detected',
    conflicting_memory_id: 'mem-conf-2',
    partner_summary: 'Database Engine Preference: PostgreSQL 16',
    partner_status: 'active',
    partner_provenance_type: 'verified_finding',
    partner_revision: 2,
    created_at: '2026-11-01T14:00:00Z',
  },
];

const mockArtifacts = [
  {
    id: 'art-1',
    project_id: 'proj-alpha-123',
    name: 'architecture_spec.md',
    file_path: 'specs/arch.md',
    artifact_type: 'specification',
    file_size_bytes: 8192,
    version: 2,
    parent_artifact_id: 'art-0',
    verification_status: 'verified',
    created_at: '2026-11-01T13:00:00Z',
  },
];

const mockLineage = {
  artifact: mockArtifacts[0],
  parent: {
    id: 'art-0',
    project_id: 'proj-alpha-123',
    name: 'architecture_spec_draft.md',
    file_path: 'specs/draft.md',
    artifact_type: 'specification',
    file_size_bytes: 4096,
    version: 1,
    parent_artifact_id: null,
    verification_status: 'unverified',
    created_at: '2026-11-01T10:00:00Z',
  },
  ancestors: [],
  descendants: [
    {
      id: 'art-2',
      project_id: 'proj-alpha-123',
      name: 'database_schema.sql',
      file_path: 'sql/schema.sql',
      artifact_type: 'code',
      file_size_bytes: 2048,
      version: 1,
      parent_artifact_id: 'art-1',
      verification_status: 'verified',
      created_at: '2026-11-01T15:00:00Z',
    },
  ],
  superseded_by: null,
  supersedes: [],
};

const mockUsageSummary = {
  total_executions: 42,
  total_tokens: 156000,
  total_duration_ms: 124500,
  total_cost_usd: 0.2345,
};

const mockModelExecutions = [
  {
    id: 'exec-1',
    provider: 'anthropic',
    model: 'claude-haiku-5-5',
    duration_ms: 1850,
    input_tokens: 3500,
    output_tokens: 650,
    cache_read_tokens: 1200,
    cost_usd: 0.0034,
    exit_code: 0,
    created_at: '2026-11-01T12:00:00Z',
  },
];

vi.mock('../api/client', () => ({
  api: {
    getProjects: vi.fn(),
    getMemoryStats: vi.fn(),
    getMemories: vi.fn(),
    getMemory: vi.fn(),
    createMemory: vi.fn(),
    updateMemory: vi.fn(),
    archiveMemory: vi.fn(),
    restoreMemory: vi.fn(),
    verifyMemory: vi.fn(),
    getConflicts: vi.fn(),
    resolveConflict: vi.fn(),
    getMemoryRevisions: vi.fn(),
    getMemoryAudit: vi.fn(),
    getArtifactsByProject: vi.fn(),
    getArtifactLineage: vi.fn(),
    getUsageSummary: vi.fn(),
    getModelExecutions: vi.fn(),
  },
}));

describe('IntelligencePage', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    const { api } = await import('../api/client');
    const mockApi = api as any;

    mockApi.getProjects.mockResolvedValue(mockProjects);
    mockApi.getMemoryStats.mockResolvedValue(mockStats);
    mockApi.getMemories.mockResolvedValue({
      items: mockMemories,
      total: 2,
      page: 1,
      page_size: 10,
      total_pages: 1,
    });
    mockApi.getConflicts.mockResolvedValue({
      items: mockConflicts,
      total: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    });
    mockApi.getArtifactsByProject.mockResolvedValue(mockArtifacts);
    mockApi.getArtifactLineage.mockResolvedValue(mockLineage);
    mockApi.getUsageSummary.mockResolvedValue(mockUsageSummary);
    mockApi.getModelExecutions.mockResolvedValue(mockModelExecutions);
    mockApi.getMemoryRevisions.mockResolvedValue([mockMemories[0]]);
    mockApi.getMemoryAudit.mockResolvedValue({
      items: [
        {
          id: 'aud-1',
          memory_id: 'mem-1',
          project_id: 'proj-alpha-123',
          action: 'verified',
          actor_type: 'operator',
          actor_id: 'Abstract',
          reason: 'Confirmed pgvector compatibility',
          previous_state: null,
          new_state: null,
          created_at: '2026-11-01T12:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    });
  });

  it('renders page header, project selector, and memory bank statistics', async () => {
    render(<IntelligencePage />);

    expect(screen.getByText('Project Intelligence & Memory Bank')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('ASTRAVA Alpha (saas)')).toBeInTheDocument();
      expect(screen.getAllByText('12').length).toBeGreaterThanOrEqual(1); // active memories
      expect(screen.getByText('5')).toBeInTheDocument(); // verified findings
      expect(screen.getByText('6')).toBeInTheDocument(); // agent conclusions
      expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(1); // open conflicts
    });

    // Check memory items rendered
    expect(
      screen.getByText('Use PostgreSQL with pgvector for persistence')
    ).toBeInTheDocument();
    expect(
      screen.getByText('Strict optimistic concurrency control on memory updates')
    ).toBeInTheDocument();
    expect(screen.getAllByText('Verified Finding').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('User Provided').length).toBeGreaterThanOrEqual(1);
  });

  it('allows switching to Conflict Workbench and reviewing conflicts', async () => {
    render(<IntelligencePage />);

    await waitFor(() => {
      expect(screen.getByText('ASTRAVA Alpha (saas)')).toBeInTheDocument();
    });

    const conflictTabBtn = screen.getByRole('button', { name: /Conflict Workbench/i });
    fireEvent.click(conflictTabBtn);

    await waitFor(() => {
      expect(screen.getByText(/Detected Conflicts/i)).toBeInTheDocument();
      expect(
        screen.getAllByText('Database Engine Preference: MongoDB').length
      ).toBeGreaterThanOrEqual(1);
    });
  });

  it('allows switching to Artifact Lineage tab and inspecting derivation tree', async () => {
    render(<IntelligencePage />);

    await waitFor(() => {
      expect(screen.getByText('ASTRAVA Alpha (saas)')).toBeInTheDocument();
    });

    const lineageTabBtn = screen.getByRole('button', { name: /Artifact Lineage/i });
    fireEvent.click(lineageTabBtn);

    await waitFor(() => {
      expect(screen.getByText('Artifact Lineage Explorer')).toBeInTheDocument();
      expect(screen.getByText('architecture_spec.md')).toBeInTheDocument();
      expect(screen.getByText('Direct Parent')).toBeInTheDocument();
      expect(screen.getByText('Derived Descendants (1)')).toBeInTheDocument();
      expect(screen.getByText('database_schema.sql')).toBeInTheDocument();
    });
  });

  it('allows switching to Model Telemetry tab and viewing compute metrics', async () => {
    render(<IntelligencePage />);

    await waitFor(() => {
      expect(screen.getByText('ASTRAVA Alpha (saas)')).toBeInTheDocument();
    });

    const telemetryTabBtn = screen.getByRole('button', { name: /Model Telemetry & Usage/i });
    fireEvent.click(telemetryTabBtn);

    await waitFor(() => {
      expect(screen.getByText('Total Model Runs')).toBeInTheDocument();
      expect(screen.getByText('Tokens Processed')).toBeInTheDocument();
      expect(screen.getByText('156,000')).toBeInTheDocument();
      expect(screen.getByText('$0.2345')).toBeInTheDocument();
      expect(screen.getByText('claude-haiku-5-5')).toBeInTheDocument();
    });
  });

  it('opens memory detail modal on memory row click', async () => {
    render(<IntelligencePage />);

    await waitFor(() => {
      expect(
        screen.getByText('Use PostgreSQL with pgvector for persistence')
      ).toBeInTheDocument();
    });

    const memoryItem = screen.getByText('Use PostgreSQL with pgvector for persistence');
    fireEvent.click(memoryItem);

    await waitFor(() => {
      expect(screen.getByText('Content Specification')).toBeInTheDocument();
      expect(screen.getByText(/Revision History/i)).toBeInTheDocument();
    });
  });

  it('opens memory creation modal on New Memory click', async () => {
    render(<IntelligencePage />);

    await waitFor(() => {
      expect(screen.getByText('ASTRAVA Alpha (saas)')).toBeInTheDocument();
    });

    const newBtn = screen.getByRole('button', { name: /New Memory/i });
    expect(newBtn).not.toBeDisabled();
    fireEvent.click(newBtn);

    await waitFor(() => {
      expect(screen.getByText('Create Project Memory')).toBeInTheDocument();
      expect(
        screen.getByPlaceholderText('e.g. Message Broker: RabbitMQ')
      ).toBeInTheDocument();
    });
  });
});
