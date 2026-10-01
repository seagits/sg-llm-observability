-- What the guardrail caught, by policy and team.
SELECT policy, finding, action, team, count(*) AS events, count(DISTINCT session) AS sessions
FROM guardrail_events
GROUP BY ALL
ORDER BY events DESC
LIMIT 12;
