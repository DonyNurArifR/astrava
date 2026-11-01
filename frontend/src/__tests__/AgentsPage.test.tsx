import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AgentsPage } from '../pages/AgentsPage';
import { api } from '../api/client';
import type { Agent } from '../types/api';

vi.mock('../api/client', () => ({
  api: {
    getAgents: vi.fn(),
    updateAgentStatus: vi.fn(),
    seedAgents: vi.fn(),
  },
}));

const mockAgents: Agent[] = [
  {
    id: 'agent-1-uuid',
    slug: 'product-researcher',
    name: 'Product Researcher',
    description: 'Researches market trends and customer personas',
    studio_type: 'saas',
    capabilities: ['market_research', 'persona_mapping'],
    instructions: 'You are a Principal Product Researcher.',
    input_schema: { type: 'object' },
    output_schema: { type: 'object', required: ['personas'] },
    available_tools: ['claude_code'],
    model_config_data: { model_id: 'claude-haiku-5-5' },
    execution_config: { timeout_seconds: 120, max_retries: 1 },
    verification_requirements: ['non_empty_output'],
    version: '1.0.0',
    is_enabled: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-2-uuid',
    slug: 'scriptwriter',
    name: 'Scriptwriter',
    description: 'Writes production scripts with timing and narration',
    studio_type: 'media',
    capabilities: ['screenwriting', 'dialogue'],
    instructions: 'You are an Award-Winning Multimedia Scriptwriter.',
    input_schema: { type: 'object' },
    output_schema: { type: 'object', required: ['scenes'] },
    available_tools: ['claude_code'],
    model_config_data: { model_id: 'claude-haiku-5-5' },
    execution_config: { timeout_seconds: 120, max_retries: 1 },
    verification_requirements: ['non_empty_output'],
    version: '1.0.0',
    is_enabled: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

describe('AgentsPage Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getAgents).mockResolvedValue(mockAgents);
    vi.mocked(api.updateAgentStatus).mockImplementation(async (slug, isEnabled) => {
      const target = mockAgents.find(a => a.slug === slug || a.id === slug);
      return { ...target!, is_enabled: isEnabled };
    });
  });

  it('renders agent registry header, metrics, and agent cards', async () => {
    render(<AgentsPage />);

    expect(screen.getByText('Agent Registry')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Product Researcher')).toBeInTheDocument();
      expect(screen.getByText('Scriptwriter')).toBeInTheDocument();
    });

    expect(screen.getByText('product-researcher')).toBeInTheDocument();
    expect(screen.getByText('scriptwriter')).toBeInTheDocument();
  });

  it('opens and closes the agent inspector modal', async () => {
    render(<AgentsPage />);

    await waitFor(() => {
      expect(screen.getByText('Product Researcher')).toBeInTheDocument();
    });

    const inspectButtons = screen.getAllByText('Inspect Specs');
    fireEvent.click(inspectButtons[0]);

    expect(screen.getByText('System Instructions & Directives')).toBeInTheDocument();
    expect(screen.getByText(/You are a Principal Product Researcher/i)).toBeInTheDocument();

    const closeButton = screen.getByText('Close Inspector');
    fireEvent.click(closeButton);

    expect(screen.queryByText('System Instructions & Directives')).not.toBeInTheDocument();
  });

  it('toggles agent enabled/disabled status', async () => {
    render(<AgentsPage />);

    await waitFor(() => {
      expect(screen.getByText('Product Researcher')).toBeInTheDocument();
    });

    const enabledButton = screen.getByText('Enabled');
    fireEvent.click(enabledButton);

    await waitFor(() => {
      expect(api.updateAgentStatus).toHaveBeenCalledWith('product-researcher', false);
    });
  });
});
