-- Follow one agent run end to end: every model call that shared a trace_id.
SELECT row_number() OVER (ORDER BY ts)                  AS step,
       ts::TIME                                         AS at,
       feature,
       split_part(model_id, '.', 2)                     AS model,
       input_tokens                                     AS in_tok,
       output_tokens                                    AS out_tok,
       latency_ms,
       stop_reason,
       round(cost_usd, 4)                               AS usd,
       round(sum(cost_usd) OVER (ORDER BY ts), 4)       AS running_usd
FROM costed
WHERE trace_id = 'tr-5f1c9a2e'
ORDER BY ts;
