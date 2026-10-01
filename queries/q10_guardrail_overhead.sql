-- What the guardrail itself costs you in time: its processing latency, straight from the trace.
SELECT team,
       count(*)                                                     AS guarded_calls,
       round(avg(g_ms))                                             AS avg_guardrail_ms,
       quantile_cont(g_ms, 0.95)::INT                               AS p95_guardrail_ms,
       round(100 * avg(g_ms) / avg(latency_ms), 1)                  AS pct_of_total_latency
FROM (
  SELECT team, latency_ms,
         list_sum(json_extract(guardrail_trace,
           '$.inputAssessment.*.invocationMetrics.guardrailProcessingLatency')::BIGINT[]) AS g_ms
  FROM invocations
  WHERE guardrail_trace IS NOT NULL AND stop_reason <> 'guardrail_intervened'
)
GROUP BY team;
