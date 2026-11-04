import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ExecutionsPage } from '../pages/ExecutionsPage';

vi.mock('../api/client', () => ({
  api: {
    getExecutions: vi.fn().mockResolvedValue([
      {
        id: 'exec-1234567890abc',
        project_id: 'proj-1',
        workflow_id: 'wf-1',
        status: 'completed',
        current_step: 4,
        total_steps: 4,
        state_data: {
          objective: 'Build autonomous SaaS engine',
          tasks: [{ title: 'Generate PRD', exit_code: 0 }],
        },
        events: [
          { event_type: 'pipeline_started', created_at: new Date().toISOString() },
          { event_type: 'pipeline_completed', created_at: new Date().toISOString() },
        ],
        created_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
        completed_at: new Date().toISOString(),
      },
      {
        id: 'exec-waiting-approval',
        project_id: 'proj-2',
        workflow_id: 'wf-2',
        status: 'waiting_approval',
        current_step: 2,
        total_steps: 3,
        state_data: {
          objective: 'Produce media documentary launch',
        },
        events: [],
        created_at: new Date().toISOString(),
      },
    ]),
    pauseExecution: vi.fn().mockResolvedValue({ status: 'paused' }),
    resumeExecution: vi.fn().mockResolvedValue({ status: 'running' }),
    getExecutionBudget: vi.fn().mockResolvedValue({
      budget_id: 'b-1',
      execution_id: 'exec-1234567890abc',
      status: 'active',
      exhaustion_reason: null,
      is_cost_estimated: false,
      limits: { max_cost_usd: 1.0, max_total_tokens: 300000 },
      consumed: {
        cost_usd: 0.12,
        actual_cost_usd: 0.12,
        estimated_cost_usd: 0.0,
        input_tokens: 12000,
        output_tokens: 3000,
        total_tokens: 15000,
        runtime_seconds: 4.5,
        agent_attempts: 1,
        remediation_turns: 0,
        replan_count: 0,
      },
      reserved: {
        input_tokens: 0,
        output_tokens: 0,
        cost_usd: 0.0,
        active_reservations: 0,
      },
      remaining: { cost_usd: 0.88, total_tokens: 285000 },
      utilization: { cost_usd: 0.12, total_tokens: 0.05 },
    }),
    increaseExecutionBudget: vi.fn().mockResolvedValue({}),
  },
}));

describe('ExecutionsPage', () => {
  it('renders executions table with badges and drawer inspection', async () => {
    render(<ExecutionsPage />);

    expect(screen.getByText('Executions')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('completed')).toBeInTheDocument();
      expect(screen.getByText('waiting_approval')).toBeInTheDocument();
      expect(screen.getByText('exec-12345678...')).toBeInTheDocument();
    });

    // Click on execution ID to open drawer
    fireEvent.click(screen.getByText('exec-12345678...'));

    await waitFor(() => {
      expect(screen.getByText('Execution Inspector')).toBeInTheDocument();
      expect(screen.getByText('pipeline_started')).toBeInTheDocument();
      expect(screen.getByText('pipeline_completed')).toBeInTheDocument();
    });
  });
});
