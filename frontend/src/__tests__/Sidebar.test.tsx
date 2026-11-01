import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Sidebar } from '../components/Sidebar';
import { ThemeProvider } from '../context/ThemeContext';

describe('Sidebar', () => {
  it('renders branding and navigation tabs', () => {
    const handleSelect = vi.fn();
    render(
      <ThemeProvider>
        <Sidebar activeTab="overview" onSelectTab={handleSelect} pendingApprovalsCount={3} />
      </ThemeProvider>
    );

    expect(screen.getByText('ASTRAVA')).toBeInTheDocument();
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Command Center')).toBeInTheDocument();
    expect(screen.getByText('Projects')).toBeInTheDocument();
    expect(screen.getByText('Executions')).toBeInTheDocument();
    expect(screen.getByText('Artifacts')).toBeInTheDocument();
    expect(screen.getByText('Approvals')).toBeInTheDocument();

    // Pending approvals badge
    expect(screen.getByText('3')).toBeInTheDocument();

    // Clicking a tab triggers onSelectTab
    fireEvent.click(screen.getByText('Command Center'));
    expect(handleSelect).toHaveBeenCalledWith('command-center');
  });
});
