import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { CommandCenterPage } from '../pages/CommandCenterPage';

vi.mock('../api/client', () => ({
  api: {
    getProjects: vi.fn().mockResolvedValue([
      {
        id: 'proj-123',
        name: 'Autonomous SaaS Alpha',
        studio_type: 'saas',
        slug: 'autonomous-saas-alpha',
        target_objectives: ['Build SaaS MVP'],
        created_at: new Date().toISOString(),
      },
    ]),
    generatePlan: vi.fn().mockResolvedValue({
      plan_id: 'plan-1',
      objective: 'Build autonomous SaaS engine',
      studio_type: 'saas',
      tasks: [
        {
          task_id: 'task-1',
          title: 'Generate PRD',
          description: 'PRD description',
          priority: 1,
          risk_level: 'low',
          requires_approval: false,
        },
      ],
      estimated_cost_usd: 0.05,
    }),
  },
}));

describe('CommandCenterPage', () => {
  it('renders project selector, studio switcher, and objective textarea', async () => {
    render(<CommandCenterPage />);

    expect(screen.getByText('ASTRAVA Orchestration Center')).toBeInTheDocument();
    expect(screen.getByText('ASTRAVA SaaS')).toBeInTheDocument();
    expect(screen.getByText('ASTRAVA Media')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/Autonomous SaaS Alpha/i)).toBeInTheDocument();
    });

    // Toggle to Media Studio
    const mediaCard = screen.getByText('ASTRAVA Media');
    fireEvent.click(mediaCard);

    // Enter objective in Media Studio
    const textarea = screen.getByPlaceholderText(/e\.g\. Produce a 5-minute documentary script/i);
    expect(textarea).toBeInTheDocument();
    fireEvent.change(textarea, { target: { value: 'Produce video launch trailer' } });
    expect((textarea as HTMLTextAreaElement).value).toBe('Produce video launch trailer');
  });
});
