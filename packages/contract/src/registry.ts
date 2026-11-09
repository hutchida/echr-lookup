import type { z } from "zod";
import { Answer, AnswerRequest } from "./answer";
import { ApiError } from "./api-error";
import { CaseDetail } from "./case-detail";
import { Chunk } from "./chunk";
import { CorpusStats } from "./corpus-stats";
import { CostLogEntry } from "./cost-log";
import { CostSummary } from "./cost-summary";
import { EvalItem, EvalRun, EvalRunSummary } from "./eval";
import { Health } from "./health";
import { IngestRun } from "./ingest-run";
import { EvalRunList, IngestRunList } from "./lists";
import { Paragraph } from "./paragraph";
import { SearchRequest, SearchResult } from "./search";
import { ManifestEntry, SourceDocument } from "./source-document";
import { StatsQueryResult } from "./stats";
import { mcpRegistry } from "./mcp";

/**
 * Every schema that crosses the API boundary (POST /search, POST /ask, GET /stats, GET /case/{id},
 * GET /ingest-runs, GET /eval-runs, GET /eval-runs/{id}, GET /costs, GET /health). Each entry is exported to
 * schema/<name>.json and must have a matching fixtures/<name>.json
 * (extra branches: fixtures/<name>.<variant>.json).
 * Mcp*: the MCP tools' arguments and results (src/mcp/).
 */
export const registry: Record<string, z.ZodType> = {
  Health,
  SourceDocument,
  ManifestEntry,
  Paragraph,
  Chunk,
  IngestRun,
  SearchRequest,
  SearchResult,
  AnswerRequest,
  Answer,
  StatsQueryResult,
  EvalItem,
  EvalRun,
  CostLogEntry,
  CaseDetail,
  CorpusStats,
  CostSummary,
  IngestRunList,
  EvalRunSummary,
  EvalRunList,
  ApiError,
  ...mcpRegistry,
};
