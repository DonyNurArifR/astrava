import React from 'react';
import { CheckCircle2, ShieldAlert } from 'lucide-react';

interface VerificationBadgeProps {
  isVerified: boolean;
  verifiedBy?: string | null;
  verifiedAt?: string | null;
}

export const VerificationBadge: React.FC<VerificationBadgeProps> = ({
  isVerified,
  verifiedBy,
  verifiedAt,
}) => {
  if (isVerified) {
    const tooltip = verifiedBy
      ? `Verified by ${verifiedBy}${verifiedAt ? ` on ${new Date(verifiedAt).toLocaleDateString()}` : ''}`
      : 'Formally verified finding';

    return (
      <span
        className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20"
        title={tooltip}
      >
        <CheckCircle2 size={12} className="shrink-0" />
        <span>Verified</span>
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-500/10 text-slate-500 dark:text-slate-400 border border-slate-500/20"
      title="Unverified assertion or conclusion"
    >
      <ShieldAlert size={12} className="shrink-0" />
      <span>Unverified</span>
    </span>
  );
};
