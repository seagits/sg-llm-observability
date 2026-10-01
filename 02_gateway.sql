-- Load the REAL calls that went through the local LiteLLM gateway (litellm_poc/llm_logger.py).
--   duckdb llm.duckdb < 02_gateway.sql
-- Same idea as 01_build.sql, different source: one NDJSON line per call, written by the gateway.
-- Cost is already on the line (LiteLLM's response_cost, from the shadow prices in config.yml).

CREATE OR REPLACE TABLE gw_calls AS
SELECT
  timezone('UTC', ts)                  AS ts,   -- keep UTC, not the laptop's zone
  CAST(timezone('UTC', ts) AS DATE)    AS dt,
  request_id,
  model,
  upstream_model,
  status,                              -- success | blocked | error
  stop_reason,                         -- stop | length | guardrail_intervened | error
  coalesce(input_tokens, 0)            AS input_tokens,
  coalesce(output_tokens, 0)           AS output_tokens,
  coalesce(cost_usd, 0)                AS cost_usd,
  latency_ms,
  guardrail_ms,
  team, feature, env, trace_id, session,
  guardrail_findings
FROM read_json('data/litellm/dt=*/*.ndjson',
  format = 'newline_delimited',
  columns = {
    ts: 'TIMESTAMPTZ', request_id: 'VARCHAR', model: 'VARCHAR', upstream_model: 'VARCHAR',
    status: 'VARCHAR', stop_reason: 'VARCHAR', input_tokens: 'BIGINT', output_tokens: 'BIGINT',
    cost_usd: 'DOUBLE', latency_ms: 'DOUBLE', guardrail_ms: 'DOUBLE',
    team: 'VARCHAR', feature: 'VARCHAR', env: 'VARCHAR', trace_id: 'VARCHAR', session: 'VARCHAR',
    guardrail_findings: 'STRUCT(policy VARCHAR, finding VARCHAR, action VARCHAR)[]'
  });

-- One row per guardrail finding (blocked attacks + anonymized PII).
CREATE OR REPLACE TABLE gw_guardrail_events AS
SELECT request_id, ts, team, feature, session, f.policy, f.finding, f.action
FROM (SELECT *, unnest(guardrail_findings) AS f FROM gw_calls);

SELECT status, count(*) AS calls, round(sum(cost_usd), 4) AS usd FROM gw_calls GROUP BY status ORDER BY calls DESC;
