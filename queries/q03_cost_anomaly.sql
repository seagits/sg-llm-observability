-- Flag any team-day that costs more than 3x that team's median over the previous 7 days.
WITH daily AS (
  SELECT team, dt, sum(cost_usd) AS usd FROM costed GROUP BY ALL
), scored AS (
  SELECT *, median(usd) OVER (PARTITION BY team ORDER BY dt
                              ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING) AS typical
  FROM daily
)
SELECT team, dt, round(usd, 2) AS usd, round(typical, 2) AS typical_usd,
       round(usd / typical, 1) AS times_typical
FROM scored
WHERE usd > 3 * typical
ORDER BY times_typical DESC;
