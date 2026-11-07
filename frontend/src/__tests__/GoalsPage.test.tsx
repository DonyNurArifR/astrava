import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { GoalsPage } from '../pages/GoalsPage';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getProjects: vi.fn(),
    getProjectGoals: vi.fn(),
    createProjectGoal: vi.fn(),
    executeGoal: vi.fn(),
  },
}));

const mockProjects = [
  { id: 'proj-1', name: 'Alpha Core SaaS', slug: 'alpha-core', description: 'Core system', studio_type: 'software' },
  { id: 'proj-2', name: 'Beta Analytics', slug: 'beta-analytics', description: 'Analytics platform', studio_type: 'software' },
];

const mockGoals = [
  {
    id: 'goal-1',
    project_id: 'proj-1',
    title: 'Deploy User Authentication Service',
    description: 'Implement JWT tokens, refresh rotation, and RBAC policies.',
    target_criteria: ['JWT sign/verify', 'Postgres user schema', 'Integration tests'],
    status: 'in_progress',
    progress_percentage: 65,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'goal-2',
    project_id: 'proj-1',
    title: 'Set up Stripe Webhooks',
    description: 'Process payment confirmations and subscriptions.',
    target_criteria: ['Webhook signature verification', 'Invoice generation'],
    status: 'achieved',
    progress_percentage: 100,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

describe('GoalsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getProjects).mockResolvedValue(mockProjects as any);
    vi.mocked(api.getProjectGoals).mockResolvedValue(mockGoals as any);
    vi.mocked(api.createProjectGoal).mockResolvedValue({
      id: 'goal-3',
      project_id: 'proj-1',
      title: 'Build Notification Engine',
      description: 'Support email, SMS, and webhook notifications',
      target_criteria: ['Email template renderer', 'Retry worker'],
      status: 'pending',
      progress_percentage: 0,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    } as any);
    vi.mocked(api.executeGoal).mockResolvedValue({
      id: 'exec-goal-999',
      status: 'running',
    } as any);
  });

  it('renders goals dashboard with projects and goals', async () => {
    render(<GoalsPage />);

    expect(screen.getByText('Project Goals & Outcomes')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Deploy User Authentication Service')).toBeInTheDocument();
      expect(screen.getByText('Set up Stripe Webhooks')).toBeInTheDocument();
      expect(screen.getByText('65%')).toBeInTheDocument();
      expect(screen.getByText('100%')).toBeInTheDocument();
    });
  });

  it('filters goals by status', async () => {
    render(<GoalsPage />);

    await waitFor(() => {
      expect(screen.getByText('Deploy User Authentication Service')).toBeInTheDocument();
    });

    const achievedFilterBtn = screen.getByRole('button', { name: /Achieved/i });
    fireEvent.click(achievedFilterBtn);

    await waitFor(() => {
      expect(api.getProjectGoals).toHaveBeenCalledWith('proj-1', 'achieved');
    });
  });

  it('opens modal, creates new goal and updates list', async () => {
    render(<GoalsPage />);

    await waitFor(() => {
      expect(screen.getByText('Project Goals & Outcomes')).toBeInTheDocument();
    });

    const newGoalBtn = screen.getByRole('button', { name: /New Goal/i });
    fireEvent.click(newGoalBtn);

    expect(screen.getByText('Define New Project Goal')).toBeInTheDocument();

    const titleInput = screen.getByPlaceholderText(/e\.g\. Build Real-Time SSE Notification Pipeline/i);
    const descInput = screen.getByPlaceholderText(/Describe the desired outcome/i);
    const criteriaInput = screen.getByPlaceholderText(/Database schema migration verified/i);

    fireEvent.change(titleInput, { target: { value: 'Build Notification Engine' } });
    fireEvent.change(descInput, { target: { value: 'Support email, SMS, and webhook notifications' } });
    fireEvent.change(criteriaInput, { target: { value: 'Email template renderer\nRetry worker' } });

    const submitBtn = screen.getByRole('button', { name: /Create Goal/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.createProjectGoal).toHaveBeenCalledWith('proj-1', {
        title: 'Build Notification Engine',
        description: 'Support email, SMS, and webhook notifications',
        target_criteria: ['Email template renderer', 'Retry worker'],
      });
      expect(screen.getByText('Build Notification Engine')).toBeInTheDocument();
    });
  });

  it('executes a goal and displays execution feedback', async () => {
    render(<GoalsPage />);

    await waitFor(() => {
      expect(screen.getByText('Deploy User Authentication Service')).toBeInTheDocument();
    });

    const executeBtns = screen.getAllByRole('button', { name: /Execute Goal/i });
    expect(executeBtns.length).toBeGreaterThan(0);

    fireEvent.click(executeBtns[0]);

    await waitFor(() => {
      expect(api.executeGoal).toHaveBeenCalledWith('proj-1', 'goal-1');
      expect(
        screen.getByText(/Autonomous pipeline started for goal 'Deploy User Authentication Service'/i)
      ).toBeInTheDocument();
    });
  });
});
