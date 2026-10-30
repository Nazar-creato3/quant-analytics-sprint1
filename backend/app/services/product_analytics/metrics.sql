-- postgres: CREATE MATERIALIZED VIEW founder_activation AS activation
-- postgres: CREATE MATERIALIZED VIEW founder_retention AS retention
-- postgres: CREATE MATERIALIZED VIEW founder_hours AS hours
-- postgres: CREATE MATERIALIZED VIEW founder_profile AS profile
-- postgres: CREATE MATERIALIZED VIEW founder_funnel AS funnel
-- postgres: CREATE MATERIALIZED VIEW founder_errors AS errors

-- name: activation
WITH connects AS (
  SELECT subject_pseudo, MIN(recorded_at) AS connected_at
  FROM events
  WHERE name = 'account_connect_success'
  GROUP BY subject_pseudo
),
activated AS (
  SELECT DISTINCT c.subject_pseudo AS subject_pseudo
  FROM connects AS c
  JOIN events AS e
    ON e.subject_pseudo = c.subject_pseudo
   AND e.name = 'first_report_shown'
   AND e.recorded_at >= c.connected_at
   AND e.recorded_at <= datetime(c.connected_at, '+24 hours')
)
SELECT
  (SELECT COUNT(*) FROM connects) AS connects,
  (SELECT COUNT(*) FROM activated) AS activated

-- name: retention
WITH regs AS (
  SELECT subject_pseudo, strftime('%Y-W%W', MIN(recorded_at)) AS cohort
  FROM events
  WHERE name = 'registration'
  GROUP BY subject_pseudo
)
SELECT
  cohort,
  COUNT(*) AS users,
  SUM(
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM events AS e
        WHERE e.subject_pseudo = regs.subject_pseudo
          AND e.name = 'user_return'
          AND strftime('%Y-W%W', e.recorded_at) > regs.cohort
      ) THEN 1
      ELSE 0
    END
  ) AS returned
FROM regs
GROUP BY cohort
ORDER BY cohort

-- name: hours
WITH regs AS (
  SELECT subject_pseudo, MIN(recorded_at) AS registered_at
  FROM events
  WHERE name = 'registration'
  GROUP BY subject_pseudo
),
reports AS (
  SELECT subject_pseudo, MIN(recorded_at) AS shown_at
  FROM events
  WHERE name = 'first_report_shown'
  GROUP BY subject_pseudo
)
SELECT CAST(
  ROUND((julianday(reports.shown_at) - julianday(regs.registered_at)) * 24) AS INTEGER
) AS hours
FROM regs
JOIN reports ON reports.subject_pseudo = regs.subject_pseudo
WHERE reports.shown_at >= regs.registered_at
ORDER BY hours

-- name: profile
SELECT
  (
    SELECT COUNT(DISTINCT subject_pseudo)
    FROM events
    WHERE name = 'registration'
  ) AS registered,
  (
    SELECT COUNT(DISTINCT subject_pseudo)
    FROM events
    WHERE name = 'profile_questionnaire_completed'
  ) AS completed

-- name: funnel
SELECT name, COUNT(*) AS n
FROM events
WHERE name IN (
  'maneuver_proposed',
  'maneuver_viewed',
  'maneuver_edited',
  'maneuver_approved',
  'maneuver_rejected',
  'maneuver_executed'
)
GROUP BY name

-- name: errors
SELECT venue, COUNT(*) AS n
FROM events
WHERE name = 'account_connect_error' AND venue != ''
GROUP BY venue
ORDER BY venue
