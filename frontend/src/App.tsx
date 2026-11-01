import React, { useEffect, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import type { NavItemKey } from './components/Sidebar';
import { Header } from './components/Header';
import { ThemeProvider } from './context/ThemeContext';
import { OverviewPage } from './pages/OverviewPage';
import { CommandCenterPage } from './pages/CommandCenterPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { ExecutionsPage } from './pages/ExecutionsPage';
import { ArtifactsPage } from './pages/ArtifactsPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { AgentsPage } from './pages/AgentsPage';
import { IntelligencePage } from './pages/IntelligencePage';
import { SettingsPage } from './pages/SettingsPage';
import { api } from './api/client';

export const AppContent: React.FC = () => {
  const [activeTab, setActiveTab] = useState<NavItemKey>('overview');
  const [pendingApprovalsCount, setPendingApprovalsCount] = useState(0);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const fetchApprovalsCount = () => {
    api
      .getApprovals(true)
      .then(res => setPendingApprovalsCount(res.length))
      .catch(() => setPendingApprovalsCount(0));
  };

  useEffect(() => {
    fetchApprovalsCount();
    const interval = setInterval(fetchApprovalsCount, 6000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    setIsRefreshing(true);
    fetchApprovalsCount();
    setTimeout(() => setIsRefreshing(false), 600);
  };

  const getPageTitle = (key: NavItemKey) => {
    switch (key) {
      case 'overview':
        return { title: 'Executive Overview', subtitle: 'Platform-wide production metrics and activity' };
      case 'command-center':
        return { title: 'Autonomous Command Center', subtitle: 'Interactive planning and task orchestration' };
      case 'agents':
        return { title: 'Autonomous Agent Registry', subtitle: 'Specialized agent capabilities, instructions, and execution schemas' };
      case 'projects':
        return { title: 'Studio Projects', subtitle: 'SaaS and Media production environments' };
      case 'executions':
        return { title: 'Pipeline Executions', subtitle: 'Stateful workflow executions and checkpoint logs' };
      case 'artifacts':
        return { title: 'Deliverable Artifacts', subtitle: 'Files, specs, diffs, and generated assets' };
      case 'approvals':
        return { title: 'Human Governance Approvals', subtitle: 'Operator authorization boundaries' };
      case 'intelligence':
        return { title: 'Platform Intelligence & Telemetry', subtitle: 'Model execution metrics and token consumption' };
      case 'settings':
        return { title: 'Configuration & Infrastructure', subtitle: 'Provider adapters, storage, and health checks' };
    }
  };

  const { title, subtitle } = getPageTitle(activeTab);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-50 dark:bg-slate-950 font-sans antialiased text-slate-900 dark:text-slate-100">
      <Sidebar
        activeTab={activeTab}
        onSelectTab={setActiveTab}
        pendingApprovalsCount={pendingApprovalsCount}
      />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header
          title={title}
          subtitle={subtitle}
          onRefresh={handleRefresh}
          isRefreshing={isRefreshing}
        />

        <main className="flex-1 overflow-y-auto">
          {activeTab === 'overview' && <OverviewPage onNavigate={setActiveTab} />}
          {activeTab === 'command-center' && <CommandCenterPage />}
          {activeTab === 'agents' && <AgentsPage />}
          {activeTab === 'projects' && <ProjectsPage />}
          {activeTab === 'executions' && <ExecutionsPage />}
          {activeTab === 'artifacts' && <ArtifactsPage />}
          {activeTab === 'approvals' && <ApprovalsPage />}
          {activeTab === 'intelligence' && <IntelligencePage />}
          {activeTab === 'settings' && <SettingsPage />}
        </main>
      </div>
    </div>
  );
};

export default function App() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  );
}
