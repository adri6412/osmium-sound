-- Step 1 of 3 — the aggregate-only analytics tables, and the history folded
-- into them. See README.md in this folder for the order and for what has to
-- change in the osmium-iso-tracker repo BEFORE any of this runs.
--
--   npx wrangler d1 execute osmium-downloads --remote --file=website/analytics/01_aggregates.sql
--
-- The CREATE statements can be re-run; the backfills cannot. They add to what
-- is already in the tables, so running this file twice doubles the history.
-- Run it once, then check the counts before going on to step 2.

-- ---------------------------------------------------------------- tables

-- Page views and unique visitors per UTC day. The sketch is a HyperLogLog
-- (website/functions/_lib/hll.js): unique visitors for a month are the union
-- of the daily sketches, so nothing raw has to be kept to answer that later.
-- Unique visitors for one day are the union of that day's rows across paths.
CREATE TABLE IF NOT EXISTS site_daily (
  day TEXT NOT NULL,
  path TEXT NOT NULL,
  views INTEGER NOT NULL DEFAULT 0,
  visitors_hll BLOB,
  PRIMARY KEY (day, path)
);

-- The same, for files. kind keeps the two halves of a download apart:
--   'served' the file actually went out — the .apk / .jar this site serves,
--            and everything on file.osmiumsound.it (written by the worker in
--            the osmium-iso-tracker repo, into this same table);
--   'click'  somebody pressed a download button on the site (the beacon).
-- Without it a click and the download it starts would be two downloads.
CREATE TABLE IF NOT EXISTS downloads_daily (
  day TEXT NOT NULL,
  file TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'served',
  hits INTEGER NOT NULL DEFAULT 0,
  downloaders_hll BLOB,
  PRIMARY KEY (day, file, kind)
);

-- Counts per page view, one row per value: dim is country, browser, os,
-- source or channel. The dl_ dimensions (dl_country, dl_browser, dl_os,
-- dl_network) are counted per download instead, and are named apart so the
-- two can never be added together by mistake. Held apart from each other and
-- from the visit they came from, these values single nobody out.
CREATE TABLE IF NOT EXISTS site_breakdown (
  day TEXT NOT NULL,
  dim TEXT NOT NULL,
  value TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, dim, value)
);

-- What was filtered out, and by which network. An ASN is an organisation, not
-- a person: this is what makes a whole ISP excluded by mistake visible,
-- without keeping any of the requests. asn 0 means unknown.
CREATE TABLE IF NOT EXISTS site_drops (
  day TEXT NOT NULL,
  reason TEXT NOT NULL,
  asn INTEGER NOT NULL DEFAULT 0,
  as_org TEXT,
  count INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, reason, asn)
);

-- ---------------------------------------------------------------- history
--
-- Two eras, never both for the same day, or every number would double:
--   from the first day the beacon wrote  -> site_sessions / site_events
--   before it                            -> page_views (the raw server log)
-- Days are UTC, like the salt the visitor hashes were made with.

-- Page views, beacon era. One row per pageview event, visits that counted only.
INSERT INTO site_daily (day, path, views)
SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, e.path AS path, COUNT(*) AS views
FROM site_events e JOIN site_sessions s ON s.id = e.session_id
WHERE e.name = 'pageview' AND s.reason IS NULL AND e.path IS NOT NULL
GROUP BY 1, 2
ON CONFLICT(day, path) DO UPDATE SET views = site_daily.views + excluded.views;

-- Page views before the beacon. One log row is one page per address per half
-- hour, which is the closest thing to a page view the log holds; the path is
-- normalised the way the beacon normalises it, near enough to match.
INSERT INTO site_daily (day, path, views)
SELECT day, CASE WHEN p IN ('', '/') THEN '/' ELSE rtrim(p, '/') END AS path, COUNT(*) AS views
FROM (
  SELECT strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') AS day,
         replace(replace(path, '/index.html', '/'), '.html', '') AS p
  FROM page_views
  WHERE is_bot = 0 AND is_dc = 0
    AND strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') <
        (SELECT COALESCE(MIN(strftime('%Y-%m-%d', ts / 1000, 'unixepoch')), '9999-12-31') FROM site_events)
)
WHERE p IS NOT NULL
GROUP BY 1, 2
ON CONFLICT(day, path) DO UPDATE SET views = site_daily.views + excluded.views;

-- Download clicks, beacon era.
INSERT INTO downloads_daily (day, file, kind, hits)
SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, e.target AS file,
       'click' AS kind, COUNT(*) AS hits
FROM site_events e JOIN site_sessions s ON s.id = e.session_id
WHERE e.name = 'download' AND s.reason IS NULL AND e.target IS NOT NULL
GROUP BY 1, 2, 3
ON CONFLICT(day, file, kind) DO UPDATE SET hits = downloads_daily.hits + excluded.hits;

-- Files the site served itself before the beacon: the F-Droid repository.
-- Judged by network only, as the middleware now does — the F-Droid client and
-- curl are people fetching a file, a hosting network is not.
INSERT INTO downloads_daily (day, file, kind, hits)
SELECT strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') AS day,
       'osmiumsound.it' || path AS file, 'served' AS kind, COUNT(*) AS hits
FROM page_views
WHERE is_dc = 0 AND (path LIKE '%.apk' OR path LIKE '%.jar')
  AND strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') <
      (SELECT COALESCE(MIN(strftime('%Y-%m-%d', ts / 1000, 'unixepoch')), '9999-12-31') FROM site_events)
GROUP BY 1, 2, 3
ON CONFLICT(day, file, kind) DO UPDATE SET hits = downloads_daily.hits + excluded.hits;

-- Breakdowns, beacon era. Counted per page view, which is how they are counted
-- from now on: the old rows counted them once per visit, so the shape of the
-- history changes even though the ranking does not.
INSERT INTO site_breakdown (day, dim, value, count)
SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, 'country' AS dim,
       COALESCE(s.country, 'XX') AS value, COUNT(*) AS count
FROM site_events e JOIN site_sessions s ON s.id = e.session_id
WHERE e.name = 'pageview' AND s.reason IS NULL
GROUP BY 1, 2, 3
ON CONFLICT(day, dim, value) DO UPDATE SET count = site_breakdown.count + excluded.count;

INSERT INTO site_breakdown (day, dim, value, count)
SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, 'browser' AS dim,
       s.browser AS value, COUNT(*) AS count
FROM site_events e JOIN site_sessions s ON s.id = e.session_id
WHERE e.name = 'pageview' AND s.reason IS NULL AND s.browser IS NOT NULL
GROUP BY 1, 2, 3
ON CONFLICT(day, dim, value) DO UPDATE SET count = site_breakdown.count + excluded.count;

INSERT INTO site_breakdown (day, dim, value, count)
SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, 'os' AS dim,
       s.os AS value, COUNT(*) AS count
FROM site_events e JOIN site_sessions s ON s.id = e.session_id
WHERE e.name = 'pageview' AND s.reason IS NULL AND s.os IS NOT NULL
GROUP BY 1, 2, 3
ON CONFLICT(day, dim, value) DO UPDATE SET count = site_breakdown.count + excluded.count;

INSERT INTO site_breakdown (day, dim, value, count)
SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, 'source' AS dim,
       COALESCE(s.source, 'Diretto') AS value, COUNT(*) AS count
FROM site_events e JOIN site_sessions s ON s.id = e.session_id
WHERE e.name = 'pageview' AND s.reason IS NULL
GROUP BY 1, 2, 3
ON CONFLICT(day, dim, value) DO UPDATE SET count = site_breakdown.count + excluded.count;

INSERT INTO site_breakdown (day, dim, value, count)
SELECT strftime('%Y-%m-%d', e.ts / 1000, 'unixepoch') AS day, 'channel' AS dim,
       COALESCE(s.channel, 'Diretto') AS value, COUNT(*) AS count
FROM site_events e JOIN site_sessions s ON s.id = e.session_id
WHERE e.name = 'pageview' AND s.reason IS NULL
GROUP BY 1, 2, 3
ON CONFLICT(day, dim, value) DO UPDATE SET count = site_breakdown.count + excluded.count;

-- Before the beacon the log only knew the country.
INSERT INTO site_breakdown (day, dim, value, count)
SELECT strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') AS day, 'country' AS dim,
       COALESCE(country, 'XX') AS value, COUNT(*) AS count
FROM page_views
WHERE is_bot = 0 AND is_dc = 0
  AND strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') <
      (SELECT COALESCE(MIN(strftime('%Y-%m-%d', ts / 1000, 'unixepoch')), '9999-12-31') FROM site_events)
GROUP BY 1, 2, 3
ON CONFLICT(day, dim, value) DO UPDATE SET count = site_breakdown.count + excluded.count;

-- What was filtered out, beacon era: one count per filtered visit.
INSERT INTO site_drops (day, reason, asn, as_org, count)
SELECT strftime('%Y-%m-%d', started / 1000, 'unixepoch') AS day, reason AS reason,
       COALESCE(asn, 0) AS asn, MIN(as_org) AS as_org, COUNT(*) AS count
FROM site_sessions
WHERE reason IS NOT NULL
GROUP BY 1, 2, 3
ON CONFLICT(day, reason, asn) DO UPDATE SET count = site_drops.count + excluded.count,
  as_org = COALESCE(site_drops.as_org, excluded.as_org);

-- Before the beacon: the log kept two flags, not a reason. A request from a
-- hosting network is counted as such, the rest of what it dropped as ua_bot,
-- which is what that flag meant. The F-Droid files are downloads, not drops.
INSERT INTO site_drops (day, reason, asn, as_org, count)
SELECT strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') AS day,
       CASE WHEN is_dc = 1 THEN 'datacenter' ELSE 'ua_bot' END AS reason,
       COALESCE(asn, 0) AS asn, MIN(as_org) AS as_org, COUNT(*) AS count
FROM page_views
WHERE (is_bot = 1 OR is_dc = 1) AND path NOT LIKE '%.apk' AND path NOT LIKE '%.jar'
  AND strftime('%Y-%m-%d', first_seen / 1000, 'unixepoch') <
      (SELECT COALESCE(MIN(strftime('%Y-%m-%d', ts / 1000, 'unixepoch')), '9999-12-31') FROM site_events)
GROUP BY 1, 2, 3
ON CONFLICT(day, reason, asn) DO UPDATE SET count = site_drops.count + excluded.count,
  as_org = COALESCE(site_drops.as_org, excluded.as_org);
