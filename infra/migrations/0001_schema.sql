-- Gate 1 schema (docs/interfaces.md section 3). Regular tables only (D-001).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;

CREATE TABLE documents (
  item_id text PRIMARY KEY,
  case_name text NOT NULL,
  application_numbers text[] NOT NULL,
  ecli text,
  doc_type text NOT NULL,
  chamber text,
  date date NOT NULL,
  articles text[] NOT NULL,
  outcome_raw text,
  outcome text NOT NULL,
  importance int,
  language text NOT NULL,
  source_url text NOT NULL,
  sha256 text NOT NULL,
  data_source text NOT NULL,
  inadmissibility_grounds text[],
  inadmissibility_grounds_source text,
  ingested_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_doc_type_idx ON documents (doc_type);
CREATE INDEX documents_outcome_idx ON documents (outcome);
CREATE INDEX documents_date_idx ON documents (date);
CREATE INDEX documents_articles_idx ON documents USING gin (articles);

CREATE TABLE paragraphs (
  id text PRIMARY KEY,
  doc_id text NOT NULL REFERENCES documents(item_id) ON DELETE CASCADE,
  position int NOT NULL,
  number int,
  section text NOT NULL,
  text text NOT NULL
);
CREATE INDEX paragraphs_doc_idx ON paragraphs (doc_id, position);

CREATE TABLE chunks (
  id text PRIMARY KEY,
  doc_id text NOT NULL REFERENCES documents(item_id) ON DELETE CASCADE,
  strategy text NOT NULL,
  position int NOT NULL,
  text text NOT NULL,
  paragraph_ids text[] NOT NULL,
  token_count int NOT NULL,
  embedding vector(384),
  embedder_model text NOT NULL
);
CREATE INDEX chunks_doc_strategy_idx ON chunks (doc_id, strategy, position);

-- BM25 over chunk text. `strategy` and `doc_id` are indexed too so the strategy filter is applied
-- inside the BM25 scan (a fast field), not after it.
CREATE INDEX chunks_bm25_idx ON chunks
  USING bm25 (id, text, strategy, doc_id)
  WITH (key_field = 'id');

CREATE INDEX chunks_embedding_hnsw_idx ON chunks
  USING hnsw (embedding vector_cosine_ops);

CREATE TABLE ingest_runs (
  run_id text PRIMARY KEY,
  started_at timestamptz NOT NULL,
  payload jsonb NOT NULL
);

CREATE TABLE cost_log (
  id text PRIMARY KEY,
  timestamp timestamptz NOT NULL,
  model text NOT NULL,
  purpose text NOT NULL,
  tokens_in int NOT NULL,
  tokens_out int NOT NULL,
  tokens_cached int NOT NULL,
  cost_usd numeric NOT NULL,
  latency_ms numeric NOT NULL,
  request_id text NOT NULL
);
CREATE INDEX cost_log_timestamp_idx ON cost_log (timestamp DESC);

CREATE TABLE eval_runs (
  run_id text PRIMARY KEY,
  created_at timestamptz NOT NULL,
  payload jsonb NOT NULL
);
