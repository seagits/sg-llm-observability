-- Latency percentiles per model, plus speed normalised by answer length.
SELECT split_part(model_id, '.', 2)                              AS model,
       count(*)                                                  AS calls,
       quantile_cont(latency_ms, 0.50)::INT                      AS p50_ms,
       quantile_cont(latency_ms, 0.95)::INT                      AS p95_ms,
       quantile_cont(latency_ms, 0.99)::INT                      AS p99_ms,
       round(median(latency_ms / nullif(output_tokens, 0)), 1)   AS ms_per_output_token
FROM costed
WHERE stop_reason <> 'guardrail_intervened'
GROUP BY ALL
ORDER BY p95_ms DESC;
