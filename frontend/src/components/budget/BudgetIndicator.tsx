import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, TrendingUp, X } from 'lucide-react';
import { api } from '../../api/client';
import type { BudgetLimitsUpdate, BudgetStatus, BudgetSummary } from '../../types/api';

interface BudgetIndicatorProps {
  executionId: string;
  /** Changing this value re-fetches the budget (e.g. execution status or updated_at). */
  refreshKey?: string;
}

const STATUS_STYLES: Record<BudgetStatus, { label: string; className: string }> = {
  active: {
    label: 'Active',
    className: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  },
  warning: {
    label: 'Warning',
    className: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  },
  exhausted: {
    label: 'Exhausted',
    className: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  },
  completed: {
    label: 'Completed',
    className: 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  },
  cancelled: {
    label: 'Cancelled',
    className: 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  },
};

const fmtUsd = (n: number) => `$${n < 1 ? n.toFixed(4) : n.toFixed(2)}`;
const fmtInt = (n: number) => Math.round(n).toLocaleString();

/** consumed / limit. No limit -> null (no bar). Zero limit with any usage -> saturated. */
const ratioOf = (consumed: number, limit: number | null): number | null => {
  if (limit === null || limit === undefined) return null;
  if (limit <= 0) return consumed > 0 ? 1 : 0;
  return consumed / limit;
};

const barColor = (ratio: number) =>
  ratio >= 1 ? 'bg-red-500' : ratio >= 0.8 ? 'bg-amber-500' : 'bg-blue-500';

interface ProgressRowProps {
  label: string;
  badge?: React.ReactNode;
  valueText: string;
  ratio: number | null;
  footer: string;
}

const ProgressRow: React.FC<ProgressRowProps> = ({ label, badge, valueText, ratio, footer }) => (
  <div className="space-y-1">
    <div className="flex items-center justify-between gap-2">
      <span className="flex items-center gap-1.5 font-semibold text-slate-700 dark:text-slate-300">
        {label}
        {badge}
      </span>
      <span className="font-mono text-slate-500">{valueText}</span>
    </div>
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={ratio === null ? undefined : Math.min(Math.round(ratio * 100), 100)}
      className="h-2 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden"
    >
      {ratio !== null && (
        <div
          className={`h-full transition-all ${barColor(ratio)}`}
          style={{ width: `${Math.min(ratio, 1) * 100}%` }}
        />
      )}
    </div>
    <div className="text-[10px] text-slate-400 font-mono">{footer}</div>
  </div>
);

interface StatProps {
  label: string;
  value: string;
}

const Stat: React.FC<StatProps> = ({ label, value }) => (
  <div>
    <span className="text-slate-400 block">{label}</span>
    <span className="font-mono font-bold text-slate-900 dark:text-white">{value}</span>
  </div>
);

/** Parses one limit input. Blank = leave unchanged. Must be a strict increase over the current limit. */
function parseIncrease(
  raw: string,
  current: number | null,
  label: string,
  integer: boolean
): { value?: number; error?: string } {
  const trimmed = raw.trim();
  if (trimmed === '') return {};
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < 0 || (integer && !Number.isInteger(value))) {
    return { error: `${label} must be a non-negative ${integer ? 'whole number' : 'number'}.` };
  }
  if (current !== null && value <= current) {
    return { error: `${label} must be greater than the current limit (${current.toLocaleString()}).` };
  }
  return { value };
}

interface IncreaseBudgetModalProps {
  executionId: string;
  summary: BudgetSummary;
  onClose: () => void;
  onUpdated: (summary: BudgetSummary) => void;
}

const IncreaseBudgetModal: React.FC<IncreaseBudgetModalProps> = ({
  executionId,
  summary,
  onClose,
  onUpdated,
}) => {
  const [costInput, setCostInput] = useState('');
  const [tokensInput, setTokensInput] = useState('');
  const [reasonInput, setReasonInput] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cost = parseIncrease(costInput, summary.limits.max_cost_usd, 'Max cost (USD)', false);
    const tokens = parseIncrease(tokensInput, summary.limits.max_total_tokens, 'Max total tokens', true);
    const error = cost.error ?? tokens.error;
    if (error) {
      setFormError(error);
      return;
    }

    if (!reasonInput.trim() || reasonInput.trim().length < 5) {
      setFormError('Please enter an auditable reason of at least 5 characters for this increase.');
      return;
    }

    const payload: BudgetLimitsUpdate = {
      reason: reasonInput.trim(),
    };
    if (cost.value !== undefined) payload.max_cost_usd = cost.value;
    if (tokens.value !== undefined) payload.max_total_tokens = tokens.value;
    if (Object.keys(payload).length <= 1) {
      setFormError('Enter a new limit for at least one field (cost or tokens).');
      return;
    }

    setSubmitting(true);
    setFormError(null);
    try {
      const updated = await api.increaseExecutionBudget(executionId, payload);
      onUpdated(updated);
      onClose();
    } catch (err: any) {
      setFormError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const inputClass =
    'w-full px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 text-slate-900 dark:text-white font-mono text-xs focus:outline-none focus:ring-2 focus:ring-blue-500';

  return (
    <div className="fixed inset-0 bg-slate-950/70 flex items-center justify-center p-4 z-[60]">
      <form
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="increase-budget-title"
        className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl max-w-md w-full p-6 shadow-xl space-y-4"
      >
        <div className="flex items-center justify-between border-b border-slate-200 dark:border-slate-800 pb-3">
          <h4
            id="increase-budget-title"
            className="font-bold text-base text-slate-900 dark:text-white flex items-center gap-2"
          >
            <TrendingUp size={16} className="text-blue-500" />
            Increase Budget
          </h4>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-slate-400 hover:text-slate-900 dark:hover:text-white p-1 rounded"
          >
            <X size={18} />
          </button>
        </div>

        <p className="text-xs text-slate-500 dark:text-slate-400">
          Leave a field blank to keep its current limit. New values must be greater than the current limit.
        </p>

        <label className="block space-y-1 text-xs">
          <span className="font-semibold text-slate-700 dark:text-slate-300">
            Max cost (USD)
            <span className="font-mono font-normal text-slate-400 ml-2">
              current: {summary.limits.max_cost_usd === null ? 'no limit' : fmtUsd(summary.limits.max_cost_usd)}
            </span>
          </span>
          <input
            type="number"
            min="0"
            step="any"
            value={costInput}
            onChange={e => setCostInput(e.target.value)}
            placeholder="unchanged"
            className={inputClass}
          />
        </label>

        <label className="block space-y-1 text-xs">
          <span className="font-semibold text-slate-700 dark:text-slate-300">
            Max total tokens
            <span className="font-mono font-normal text-slate-400 ml-2">
              current:{' '}
              {summary.limits.max_total_tokens === null
                ? 'no limit'
                : fmtInt(summary.limits.max_total_tokens)}
            </span>
          </span>
          <input
            type="number"
            min="0"
            step="1"
            value={tokensInput}
            onChange={e => setTokensInput(e.target.value)}
            placeholder="unchanged"
            className={inputClass}
          />
        </label>

        <label className="block space-y-1 text-xs">
          <span className="font-semibold text-slate-700 dark:text-slate-300">
            Justification / Reason <span className="text-red-500">*</span>
          </span>
          <textarea
            required
            rows={2}
            value={reasonInput}
            onChange={e => setReasonInput(e.target.value)}
            placeholder="e.g. Authorized additional wave for extensive test generation"
            className={inputClass}
          />
        </label>

        {formError && (
          <div className="p-3 bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 rounded-lg text-xs">
            {formError}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 rounded border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs font-medium"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-xs font-medium"
          >
            {submitting ? 'Submitting...' : 'Submit increase'}
          </button>
        </div>
      </form>
    </div>
  );
};

export const BudgetIndicator: React.FC<BudgetIndicatorProps> = ({ executionId, refreshKey }) => {
  const [summary, setSummary] = useState<BudgetSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showIncrease, setShowIncrease] = useState(false);

  const load = useCallback(() => {
    api
      .getExecutionBudget(executionId)
      .then(data => {
        setSummary(data);
        setLoadError(null);
      })
      .catch(err => setLoadError(err.message));
  }, [executionId]);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  if (!summary) {
    return (
      <section className="space-y-2">
        <h4 className="font-bold uppercase text-[10px] tracking-wider text-slate-400">Budget</h4>
        <p className="text-xs text-slate-400">
          {loadError ? `Budget unavailable: ${loadError}` : 'Loading budget...'}
        </p>
      </section>
    );
  }

  const { limits, consumed, reserved, status, is_cost_estimated, exhaustion_reason } = summary;
  const statusStyle = STATUS_STYLES[status];
  const costRatio = ratioOf(consumed.cost_usd, limits.max_cost_usd);
  const tokenRatio = ratioOf(consumed.total_tokens, limits.max_total_tokens);

  return (
    <section className="space-y-3 p-3 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
      <div className="flex items-center justify-between">
        <h4 className="font-bold uppercase text-[10px] tracking-wider text-slate-400">Budget</h4>
        <span
          className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${statusStyle.className}`}
        >
          {statusStyle.label}
        </span>
      </div>

      {status === 'exhausted' && (
        <div
          role="alert"
          className="p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 space-y-2"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <p className="font-bold">Budget exhausted</p>
              <p className="font-mono text-[11px]">{exhaustion_reason ?? 'A budget limit was reached.'}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowIncrease(true)}
            className="px-2.5 py-1 rounded bg-red-600 hover:bg-red-500 text-white font-medium text-xs inline-flex items-center gap-1"
          >
            <TrendingUp size={11} />
            Increase Budget
          </button>
        </div>
      )}

      <div className="space-y-3 text-xs">
        <ProgressRow
          label="Cost"
          badge={
            is_cost_estimated ? (
              <span className="font-mono text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                (Estimated)
              </span>
            ) : undefined
          }
          valueText={`${fmtUsd(consumed.cost_usd)} / ${
            limits.max_cost_usd === null ? 'no limit' : fmtUsd(limits.max_cost_usd)
          }`}
          ratio={costRatio}
          footer={`Actual ${fmtUsd(consumed.actual_cost_usd)} · Estimated ${fmtUsd(consumed.estimated_cost_usd)}`}
        />

        <ProgressRow
          label="Tokens"
          valueText={`${fmtInt(consumed.total_tokens)} / ${
            limits.max_total_tokens === null ? 'no limit' : fmtInt(limits.max_total_tokens)
          }`}
          ratio={tokenRatio}
          footer={`In ${fmtInt(consumed.input_tokens)} · Out ${fmtInt(consumed.output_tokens)}`}
        />
      </div>

      <div className="grid grid-cols-3 gap-3 text-[11px] pt-1">
        <Stat
          label="Agent attempts"
          value={
            limits.max_agent_attempts === null
              ? `${consumed.agent_attempts}`
              : `${consumed.agent_attempts} / ${limits.max_agent_attempts}`
          }
        />
        <Stat
          label="Replans"
          value={
            limits.max_replan_count === null
              ? `${consumed.replan_count}`
              : `${consumed.replan_count} / ${limits.max_replan_count}`
          }
        />
        <Stat
          label="Remediation turns"
          value={
            limits.max_remediation_turns === null
              ? `${consumed.remediation_turns}`
              : `${consumed.remediation_turns} / ${limits.max_remediation_turns}`
          }
        />
      </div>

      {reserved.active_reservations > 0 && (
        <p className="text-[10px] text-slate-400 font-mono">
          {reserved.active_reservations} reservation(s) in flight · {fmtUsd(reserved.cost_usd)} reserved
        </p>
      )}

      {showIncrease && (
        <IncreaseBudgetModal
          executionId={executionId}
          summary={summary}
          onClose={() => setShowIncrease(false)}
          onUpdated={setSummary}
        />
      )}
    </section>
  );
};
