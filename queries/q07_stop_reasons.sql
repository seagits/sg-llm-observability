-- How answers ended. max_tokens means the user got a cut-off answer and you paid for it.
SELECT team,
       count(*)                                                                AS calls,
       round(100 * count(*) FILTER (stop_reason = 'end_turn') / count(*), 1)  AS pct_complete,
       round(100 * count(*) FILTER (stop_reason = 'max_tokens') / count(*), 1) AS pct_truncated,
       round(100 * count(*) FILTER (stop_reason = 'guardrail_intervened') / count(*), 2) AS pct_blocked,
       round(coalesce(sum(cost_usd) FILTER (stop_reason = 'max_tokens'), 0), 2) AS usd_on_truncated
FROM costed
GROUP BY team
ORDER BY pct_truncated DESC;
