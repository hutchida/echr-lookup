import Link from "next/link";
import type { Citation } from "@echr/contract";
import { chipLabel, chipRef, displayQuote, docTypeShortLabel } from "./answer-display";

/** The document-type tag on a chip or source: a legal summary is set apart so it never passes for the judgment. */
export function DocTypeTag({ docType }: { docType: Citation["doc_type"] }) {
  const summary = docType === "legal_summary";
  return (
    <span
      data-testid="doc-type"
      data-doc-type={docType}
      className={
        summary
          ? "ml-1 rounded border border-amber-400 bg-amber-50 px-1 text-[0.7rem] font-semibold text-amber-900"
          : "ml-1 rounded bg-stone-100 px-1 text-[0.7rem] font-normal text-stone-600"
      }
    >
      {docTypeShortLabel(docType)}
    </span>
  );
}

/** A clickable "Case §ref · Type" chip that opens the exact paragraph on the case page. */
export function CitationChip({ citation }: { citation: Citation }) {
  return (
    <Link
      href={citation.link_target}
      data-testid="citation"
      data-paragraph-id={citation.paragraph_id}
      data-doc-type={citation.doc_type}
      aria-label={chipLabel(citation)}
      title={`Open paragraph ${citation.paragraph_id} (${docTypeShortLabel(citation.doc_type)}): “${displayQuote(citation.quote)}”`}
      className="ml-1 mr-0.5 inline-block whitespace-nowrap rounded-md border border-stone-300 bg-white px-1.5 py-0.5 align-baseline text-xs font-medium text-stone-800 hover:border-stone-500 hover:bg-stone-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900"
    >
      <span aria-hidden="true">¶ </span>
      {chipRef(citation)}
      <DocTypeTag docType={citation.doc_type} />
    </Link>
  );
}
