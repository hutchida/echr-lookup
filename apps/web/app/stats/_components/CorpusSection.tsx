import type { ApiResult } from "@/lib/api";
import type { CorpusStats } from "@echr/contract";
import { articleLabel, bucketRows, formatCount, formatTimestamp, humanise } from "../_lib/format";
import { BarList } from "./BarList";
import { Section, SectionError, Stat } from "./Section";

export function CorpusSection({ result }: { result: ApiResult<CorpusStats> }) {
  if (!result.ok) {
    return (
      <Section id="corpus-h" testId="stats-counts" title="Corpus">
        <SectionError what="corpus counts" error={result.error} status={result.status} />
      </Section>
    );
  }
  const s = result.data;
  return (
    <Section
      id="corpus-h"
      testId="stats-counts"
      title="Corpus"
      note={
        <>
          Data source: <strong data-testid="stats-data-source">{s.data_source}</strong>
          {s.data_source === "snapshot" ? " (the small committed sample, not the full HUDOC download)" : ""}. Counts as of{" "}
          {formatTimestamp(s.generated_at)}.
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
        <Stat label="Documents" value={formatCount(s.totals.documents)} />
        <Stat label="Paragraphs" value={formatCount(s.totals.paragraphs)} />
        <Stat label="Chunks · fixed" value={formatCount(s.totals.chunks.fixed)} hint="Fixed-size windows" />
        <Stat label="Chunks · recursive" value={formatCount(s.totals.chunks.recursive)} hint="Split on paragraph/sentence boundaries" />
        <Stat label="Chunks · by_section" value={formatCount(s.totals.chunks.by_section)} hint="One chunk group per judgment section" />
      </dl>
      <div className="mt-6 grid gap-8 md:grid-cols-2">
        <BarList title="By document type" rows={bucketRows(s.by_doc_type, humanise)} />
        <BarList title="By outcome" rows={bucketRows(s.by_outcome, humanise)} />
        <BarList title="By chamber" rows={bucketRows(s.by_chamber)} />
        <BarList title="By article (documents touching it)" rows={bucketRows(s.by_article, articleLabel)} />
        <div className="md:col-span-2">
          <BarList title="By year" rows={bucketRows(s.by_year)} />
        </div>
      </div>
    </Section>
  );
}
