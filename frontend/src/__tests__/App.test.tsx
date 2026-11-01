import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import App from '../App';

vi.mock('../api/client', () => ({
  api: {
    getHealth: vi.fn().mockResolvedValue({ status: 'healthy', database: 'connected' }),
    getApprovals: vi.fn().mockResolvedValue([]),
    getProjects: vi.fn().mockResolvedValue([]),
    getProjectStats: vi.fn().mockResolvedValue({
      total_projects: 3,
      saas_projects: 2,
      media_projects: 1,
      total_tasks: 12,
      completed_tasks: 10,
      total_executions: 4,
      total_artifacts: 8,
      pending_approvals: 0,
      total_cost_usd: 0.045,
    }),
    getUsageSummary: vi.fn().mockResolvedValue({
      total_cost_usd: 0.045,
      total_executions: 4,
      total_tokens: 15000,
      avg_duration_ms: 1200,
      recent_executions: [],
    }),
    getExecutions: vi.fn().mockResolvedValue([]),
    getArtifactsByProject: vi.fn().mockResolvedValue([]),
    getIntelligenceSummary: vi.fn().mockResolvedValue({
      total_cost_usd: 0.045,
      total_executions: 4,
      total_tokens: 15000,
      avg_duration_ms: 1200,
      recent_executions: [],
    }),
  },
}));

describe('App', () => {
  it('renders application with sidebar and overview content', async () => {
    render(<App />);

    expect(screen.getByText('ASTRAVA')).toBeInTheDocument();
    expect(screen.getByText('Executive Overview')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Platform-wide production metrics and activity')).toBeInTheDocument();
    });
  });
});
