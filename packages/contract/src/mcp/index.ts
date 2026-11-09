import type { z } from "zod";
import { McpCountCasesInput, McpCountCasesResult } from "./count";
import { McpGetCaseInput, McpGetCaseResult, McpGetParagraphsInput, McpGetParagraphsResult } from "./documents";
import { McpCheckQuoteInput, McpCheckQuoteResult, McpCorpusInfoInput, McpCorpusInfoResult } from "./info";
import { McpSearchCaseLawInput, McpSearchCaseLawResult } from "./search";

export * from "./count";
export * from "./documents";
export * from "./info";
export * from "./search";
export * from "./shared";

/** The six MCP tools: name -> [input schema, result schema]. Schema files: schema/<Mcp…Input|Result>.json. */
export const MCP_TOOLS = {
  search_case_law: [McpSearchCaseLawInput, McpSearchCaseLawResult],
  get_paragraphs: [McpGetParagraphsInput, McpGetParagraphsResult],
  get_case: [McpGetCaseInput, McpGetCaseResult],
  count_cases: [McpCountCasesInput, McpCountCasesResult],
  corpus_info: [McpCorpusInfoInput, McpCorpusInfoResult],
  check_quote: [McpCheckQuoteInput, McpCheckQuoteResult],
} as const satisfies Record<string, readonly [z.ZodType, z.ZodType]>;

export const mcpRegistry: Record<string, z.ZodType> = {
  McpSearchCaseLawInput,
  McpSearchCaseLawResult,
  McpGetParagraphsInput,
  McpGetParagraphsResult,
  McpGetCaseInput,
  McpGetCaseResult,
  McpCountCasesInput,
  McpCountCasesResult,
  McpCorpusInfoInput,
  McpCorpusInfoResult,
  McpCheckQuoteInput,
  McpCheckQuoteResult,
};
