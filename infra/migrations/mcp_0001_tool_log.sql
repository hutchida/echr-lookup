-- MCP server call log (docs/interfaces-mcp.md section 4). Not in rag.index.db.APP_TABLES, so a
-- reset() (which drops only that fixed list) leaves it alone.
CREATE TABLE IF NOT EXISTS tool_log (
  id bigserial PRIMARY KEY,
  called_at timestamptz NOT NULL DEFAULT now(),
  tool text NOT NULL,
  args jsonb NOT NULL,
  ok boolean NOT NULL,
  error text,
  latency_ms numeric NOT NULL,
  result_bytes int NOT NULL,
  data_source text NOT NULL,
  transport text NOT NULL            -- 'stdio' | 'http'
);
CREATE INDEX IF NOT EXISTS tool_log_called_at ON tool_log (called_at);
