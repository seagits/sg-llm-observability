-- Sessions that hit the prompt-attack filter repeatedly in a short window.
SELECT session, team,
       count(*)                                   AS blocked_attacks,
       min(ts)                                    AS first_seen,
       max(ts)                                    AS last_seen,
       date_diff('minute', min(ts), max(ts))      AS minutes
FROM guardrail_events
WHERE finding = 'PROMPT_ATTACK' AND action = 'BLOCKED'
GROUP BY session, team
HAVING count(*) >= 5
ORDER BY blocked_attacks DESC;
