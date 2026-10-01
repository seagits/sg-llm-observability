-- Daily spend per team. PIVOT turns teams into columns without naming them.
PIVOT (SELECT dt, team, cost_usd FROM costed)
ON team USING round(sum(cost_usd), 2)
ORDER BY dt;
