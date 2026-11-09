import type { AnswerClaim } from "./answer-display";
import { claimStatusInfo } from "./answer-display";

const TONE: Record<AnswerClaim["status"], string> = {
  supported: "border-emerald-300 bg-emerald-50 text-emerald-900",
  unsupported: "border-red-300 bg-red-50 text-red-900",
  unverified: "border-amber-300 bg-amber-50 text-amber-900",
};

/** Verification badge: a symbol and a word (never colour alone); the reason shows on hover/focus. */
export function ClaimBadge({ claim }: { claim: AnswerClaim }) {
  const info = claimStatusInfo(claim.status);
  return (
    <span
      data-testid="claim-status"
      data-status={claim.status}
      tabIndex={0}
      title={`${info.meaning} ${claim.reason}`.trim()}
      className={`ml-1 inline-block whitespace-nowrap rounded-full border px-2 py-0.5 align-baseline text-xs font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900 ${TONE[claim.status]}`}
    >
      <span aria-hidden="true">{info.symbol} </span>
      {info.label}
    </span>
  );
}
