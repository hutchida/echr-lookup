import type { CorpusStats, CostSummary, EvalRunSummary, IngestRun } from "@echr/contract";

export type { CostSummary, EvalRunSummary, IngestRun };
export type CountBucket = CorpusStats["by_doc_type"][number];
