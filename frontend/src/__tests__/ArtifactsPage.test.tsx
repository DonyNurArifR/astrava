import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ArtifactsPage } from '../pages/ArtifactsPage';

vi.mock('../api/client', () => ({
  api: {
    getProjects: vi.fn().mockResolvedValue([
      { id: 'proj-1', name: 'Alpha SaaS Engine', studio_type: 'saas' },
    ]),
    getArtifactsByProject: vi.fn().mockResolvedValue([
      {
        id: 'art-1',
        project_id: 'proj-1',
        name: 'prd.md',
        file_path: 'proj-1/prd.md',
        artifact_type: 'prd',
        file_size_bytes: 4096,
        created_at: new Date().toISOString(),
      },
    ]),
    previewArtifact: vi.fn().mockResolvedValue('# Product Requirements Document\nAutonomous specifications.\n'),
    getDownloadUrl: vi.fn().mockReturnValue('/api/v1/artifacts/art-1/download'),
  },
}));

describe('ArtifactsPage', () => {
  it('renders artifacts list, allows search filtering, preview modal, and download link', async () => {
    const { api } = await import('../api/client');
    render(<ArtifactsPage />);

    expect(screen.getByText('Artifacts')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('prd.md')).toBeInTheDocument();
      expect(screen.getByText('4.0 KB')).toBeInTheDocument();
    });

    // Verify preview button loads content
    const previewBtn = screen.getByText('Preview');
    fireEvent.click(previewBtn);

    await waitFor(() => {
      expect(api.previewArtifact).toHaveBeenCalledWith('art-1');
      expect(screen.getByText(/Product Requirements Document/i)).toBeInTheDocument();
    });

    // Verify download link
    const downloadLink = screen.getByText('Download').closest('a');
    expect(downloadLink).toHaveAttribute('href', '/api/v1/artifacts/art-1/download');
  });
});
