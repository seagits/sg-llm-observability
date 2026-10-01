-- Who spends what, on which model, and what one call costs.
SELECT team,
       split_part(model_id, '.', 2)                       AS model,
       count(*)                                           AS calls,
       round(sum(cost_usd), 2)                            AS usd,
       round(100 * sum(cost_usd) / sum(sum(cost_usd)) OVER (), 1) AS pct_of_bill,
       round(1000 * avg(cost_usd), 2)                     AS usd_per_1k_calls
FROM costed
GROUP BY ALL
ORDER BY usd DESC;
