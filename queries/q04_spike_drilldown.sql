-- What caused it? Same day, same team, grouped by who called and with which model.
SELECT session,
       split_part(model_id, '.', 2)     AS model,
       count(*)                         AS calls,
       round(avg(input_tokens))         AS avg_input_tokens,
       min(ts)::TIME                    AS first_call,
       max(ts)::TIME                    AS last_call,
       round(sum(cost_usd), 2)          AS usd
FROM costed
WHERE team = 'batch-summarizer' AND dt = DATE '2026-09-24'
GROUP BY ALL
ORDER BY usd DESC
LIMIT 5;
