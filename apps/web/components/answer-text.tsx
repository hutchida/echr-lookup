import { CitationChip } from "./citation-chip";
import { ClaimBadge } from "./claim-badge";
import type { Segment } from "./answer-display";

/** The answer text with a citation chip after each claim and a verification badge on claims it could place. */
export function AnswerText({ segments }: { segments: Segment[] }) {
  return (
    <div data-testid="answer" className="text-base leading-8">
      {segments.map((s, i) => {
        if (s.kind === "text") return <span key={i}>{s.text}</span>;
        if (s.kind === "cite") {
          return (
            <span key={i}>
              {s.citations.map((c) => (
                <CitationChip key={c.paragraph_id} citation={c} />
              ))}
            </span>
          );
        }
        return (
          <span key={i} data-testid="claim" data-claim-id={s.claim.id}>
            {s.text}
            {s.citations.map((c) => (
              <CitationChip key={c.paragraph_id} citation={c} />
            ))}
            <ClaimBadge claim={s.claim} />
            {s.endsSentence ? "." : ""}
          </span>
        );
      })}
    </div>
  );
}
