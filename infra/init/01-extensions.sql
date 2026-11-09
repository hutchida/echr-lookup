-- Runs once, the first time the database volume is created.
-- pg_search depends on vector, so vector must come first.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;
