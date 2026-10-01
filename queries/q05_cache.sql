-- Prompt caching: how much of the input was served from cache, and what it saved.
SELECT team,
       round(100 * sum(cache_read_tokens)
             / sum(input_tokens + cache_read_tokens + cache_write_tokens), 1) AS pct_input_from_cache,
       round(sum(cost_usd), 2)        AS usd,
       round(sum(cache_saved_usd), 2) AS saved_by_cache_usd
FROM costed
GROUP BY team
ORDER BY usd DESC;
