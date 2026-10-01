-- Build the analytics database from raw Bedrock invocation logs.
--   duckdb llm.duckdb < 01_build.sql
-- Against real S3, change RAW to 's3://YOUR-LOG-BUCKET/AWSLogs/...' and run 00_s3.sql first.

SET VARIABLE raw = 'data/raw/AWSLogs/*/BedrockModelInvocationLogs/*/*/*/*/*/*.json.gz';

-- 1. Raw view. Explicit columns: we name only what we need, so prompts (input.inputBodyJson)
--    are never read, and the response body stays as JSON instead of an inferred 200-field struct.
CREATE OR REPLACE VIEW raw AS
SELECT *
FROM read_json(getvariable('raw'),
  format = 'newline_delimited',
  columns = {
    timestamp:       'TIMESTAMP',
    accountId:       'VARCHAR',
    region:          'VARCHAR',
    requestId:       'VARCHAR',
    operation:       'VARCHAR',
    modelId:         'VARCHAR',
    identity:        'STRUCT(arn VARCHAR)',
    requestMetadata: 'MAP(VARCHAR, VARCHAR)',
    input:           'STRUCT(inputTokenCount BIGINT)',
    output:          'STRUCT(outputTokenCount BIGINT, outputBodyJson JSON)'
  });

-- 2. One flat row per model call.
CREATE OR REPLACE TABLE invocations AS
SELECT
  timestamp                                   AS ts,
  CAST(timestamp AS DATE)                     AS dt,
  requestId                                   AS request_id,
  accountId                                   AS account_id,
  region,
  operation,
  modelId                                     AS model_id,
  split_part(identity.arn, '/', 2)            AS role,
  split_part(identity.arn, '/', 3)            AS session,
  requestMetadata['team']                     AS team,
  requestMetadata['feature']                  AS feature,
  requestMetadata['env']                      AS env,
  requestMetadata['trace_id']                 AS trace_id,
  input.inputTokenCount                       AS input_tokens,
  output.outputTokenCount                     AS output_tokens,
  coalesce((b->'usage'->>'cacheReadInputTokens')::BIGINT, 0)  AS cache_read_tokens,
  coalesce((b->'usage'->>'cacheWriteInputTokens')::BIGINT, 0) AS cache_write_tokens,
  (b->'metrics'->>'latencyMs')::BIGINT        AS latency_ms,
  b->>'stopReason'                            AS stop_reason,
  b->'trace'->'guardrail'                     AS guardrail_trace
FROM (SELECT *, output.outputBodyJson AS b FROM raw);

-- 3. Prices live in a table, with a start date, so a price change never rewrites history.
--    EXAMPLE RATES in USD per 1M tokens. Load your own from your AWS price sheet.
CREATE OR REPLACE TABLE prices (model_id VARCHAR, valid_from DATE,
                                input DOUBLE, output DOUBLE, cache_read DOUBLE, cache_write DOUBLE);
INSERT INTO prices VALUES
  ('anthropic.claude-sonnet-4-20250514-v1:0',  DATE '2026-01-01', 3.00, 15.00, 0.30,  3.75),
  ('anthropic.claude-haiku-4-5-20251001-v1:0', DATE '2026-01-01', 1.00,  5.00, 0.10,  1.25),
  ('amazon.nova-lite-v1:0',                    DATE '2026-01-01', 0.06,  0.24, 0.015, 0.06);

-- 4. Cost per call. ASOF JOIN picks the price row in force on the day of the call.
CREATE OR REPLACE VIEW costed AS
SELECT i.*,
  ( i.input_tokens       * p.input
  + i.output_tokens      * p.output
  + i.cache_read_tokens  * p.cache_read
  + i.cache_write_tokens * p.cache_write ) / 1e6 AS cost_usd,
  -- what the cached tokens would have cost at the normal input rate
  ( i.cache_read_tokens * (p.input - p.cache_read)
  - i.cache_write_tokens * (p.cache_write - p.input) ) / 1e6 AS cache_saved_usd
FROM invocations i
ASOF JOIN prices p ON i.model_id = p.model_id AND i.dt >= p.valid_from;

-- 5. One row per guardrail finding. The trace is keyed by guardrail id, so '$.*' walks every
--    guardrail applied; outputAssessments holds a list per guardrail, hence '.*[*]'.
CREATE OR REPLACE TABLE guardrail_events AS
WITH assessed AS (
  SELECT request_id, ts, dt, team, feature, session, 'input' AS side,
         unnest(json_extract(guardrail_trace, '$.inputAssessment.*')) AS a
  FROM invocations WHERE guardrail_trace IS NOT NULL
  UNION ALL
  SELECT request_id, ts, dt, team, feature, session, 'output',
         unnest(json_extract(guardrail_trace, '$.outputAssessments.*[*]'))
  FROM invocations WHERE guardrail_trace IS NOT NULL
),
findings AS (
  SELECT * EXCLUDE (a), 'content_filter' AS policy, unnest(json_extract(a, '$.contentPolicy.filters[*]')) AS f FROM assessed
  UNION ALL
  SELECT * EXCLUDE (a), 'denied_topic',             unnest(json_extract(a, '$.topicPolicy.topics[*]'))    FROM assessed
  UNION ALL
  SELECT * EXCLUDE (a), 'pii',                      unnest(json_extract(a, '$.sensitiveInformationPolicy.piiEntities[*]')) FROM assessed
  UNION ALL
  SELECT * EXCLUDE (a), 'word_filter',              unnest(json_extract(a, '$.wordPolicy.customWords[*]')) FROM assessed
)
SELECT * EXCLUDE (f),
       coalesce(f->>'name', f->>'type') AS finding,
       f->>'action'                     AS action,
       f->>'confidence'                 AS confidence
FROM findings
WHERE (f->>'detected')::BOOLEAN;

-- 6. Curated Parquet, one folder per day. This is what dashboards and ad-hoc queries read.
COPY (SELECT * FROM costed) TO 'data/curated/invocations'
  (FORMAT parquet, PARTITION_BY (dt), COMPRESSION zstd, OVERWRITE_OR_IGNORE);
COPY guardrail_events TO 'data/curated/guardrail_events.parquet' (FORMAT parquet, COMPRESSION zstd);

SELECT count(*) AS calls, count(DISTINCT team) AS teams, min(dt) AS first_day, max(dt) AS last_day,
       round(sum(cost_usd), 2) AS total_usd
FROM costed;
