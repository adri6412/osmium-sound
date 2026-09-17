-- Step 3 of 3 — deletes the tables that hold data about people.
--
--   npx wrangler d1 execute osmium-downloads --remote --file=website/analytics/03_drop_legacy.sql
--
-- Run it only after steps 1 and 2 have run and the numbers on the dashboard
-- look right: this cannot be undone, and that is the point. These rows are
-- not kept "just in case" — page_views and site_visits hold IP addresses in
-- clear, and a site_sessions row holds enough about one visit (country,
-- region, city, browser, operating system, screen width, language, network)
-- to point at one person even without an address.
--
-- site_salts stays: the beacon still needs today's salt and still deletes
-- yesterday's.
--
-- Two tables are NOT touched here because this file cannot reach them safely:
--   download_sessions  written by the osmium-iso-tracker worker, still one
--                      row per IP per file per half hour. It has to stop being
--                      written before it can be dropped, in that repo.
--   the dashboard's own legacy views (src/legacy.js) read page_views,
--                      site_visits and download_sessions: they break the
--                      moment this runs, so remove them first.

DROP TABLE IF EXISTS site_events;
DROP TABLE IF EXISTS site_sessions;
DROP TABLE IF EXISTS page_views;
DROP TABLE IF EXISTS site_visits;
