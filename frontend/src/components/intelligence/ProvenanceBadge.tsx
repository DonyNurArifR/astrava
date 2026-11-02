import React from 'react';
import type { MemoryProvenanceType } from '../../types/api';

interface ProvenanceBadgeProps {
  provenance: MemoryProvenanceType;
  confidenceScore?: number;
  showScore?: boolean;
}

const PROVENANCE_CONFIG: Record<
  MemoryProvenanceType,
  { label: string; badgeClass: string; score: number }
> = {
  user_provided: {
    label: 'User Provided',
    badgeClass: 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20',
    score: 1.0,
  },
  verified_finding: {
    label: 'Verified Finding',
    badgeClass: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20',
    score: 0.95,
  },
  agent_conclusion: {
    label: 'Agent Conclusion',
    badgeClass: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20',
    score: 0.7,
  },
  assumption: {
    label: 'Assumption',
    badgeClass: 'bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20',
    score: 0.5,
  },
};

export const ProvenanceBadge: React.FC<ProvenanceBadgeProps> = ({
  provenance,
  confidenceScore,
  showScore = false,
}) => {
  const config = PROVENANCE_CONFIG[provenance] || {
    label: provenance,
    badgeClass: 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20',
    score: 0.5,
  };

  const scoreToDisplay = confidenceScore !== undefined ? confidenceScore : config.score;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border ${config.badgeClass}`}
      title={`Provenance: ${config.label} (Heuristic ranking weight: ${scoreToDisplay.toFixed(2)})`}
    >
      <span>{config.label}</span>
      {showScore && (
        <span className="text-[10px] font-mono opacity-80 border-l border-current/20 pl-1">
          {(scoreToDisplay * 100).toFixed(0)}%
        </span>
      )}
    </span>
  );
};
