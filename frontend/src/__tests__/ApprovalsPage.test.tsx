import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ApprovalsPage } from '../pages/ApprovalsPage';

vi.mock('../api/client', () => ({
  api: {
    getApprovals: vi.fn().mockImplementation((pendingOnly) => {
      if (pendingOnly) {
        return Promise.resolve([
          {
            id: 'appr-1',
            execution_id: 'exec-1',
            action_type: 'high_risk_task_execution',
            description: 'Approval requested for task: Prepare Metadata & SEO',
            risk_level: 'medium',
            status: 'pending',
            context_data: { task: { title: 'Prepare Metadata & SEO' } },
            created_at: new Date().toISOString(),
          },
        ]);
      }
      return Promise.resolve([
        {
          id: 'appr-1',
          execution_id: 'exec-1',
          action_type: 'high_risk_task_execution',
          description: 'Approval requested for task: Prepare Metadata & SEO',
          risk_level: 'medium',
          status: 'pending',
          context_data: { task: { title: 'Prepare Metadata & SEO' } },
          created_at: new Date().toISOString(),
        },
        {
          id: 'appr-hist-1',
          execution_id: 'exec-2',
          action_type: 'high_risk_task_execution',
          description: 'Approval requested for deployment script',
          risk_level: 'high',
          status: 'approved',
          decision_reason: 'Verified by lead engineer',
          decided_by: 'Abstract',
          decided_at: new Date().toISOString(),
          created_at: new Date().toISOString(),
        },
      ]);
    }),
    decideApproval: vi.fn().mockResolvedValue({ status: 'approved' }),
  },
}));

describe('ApprovalsPage', () => {
  it('renders pending approval and historical approval records, handles decision', async () => {
    const { api } = await import('../api/client');
    render(<ApprovalsPage />);

    expect(screen.getByText('Human Approvals')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/Approval requested for task: Prepare Metadata & SEO/i)).toBeInTheDocument();
      expect(screen.getByText('Approval History (1)')).toBeInTheDocument();
    });

    // Enter decision rationale
    const reasonInput = screen.getByPlaceholderText(/Decision reasoning/i);
    fireEvent.change(reasonInput, { target: { value: 'Approved via testing suite' } });

    // Click Approve
    const approveBtn = screen.getByText('Authorize Action');
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(api.decideApproval).toHaveBeenCalledWith('appr-1', 'approved', 'Approved via testing suite');
    });
  });
});
