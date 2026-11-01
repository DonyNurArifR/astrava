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
