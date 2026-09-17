-- One more table: how many appliances are on right now.
--
--   npx wrangler d1 execute osmium-downloads --remote --file=website/analytics/04_appliances_live.sql
--
-- Apply it BEFORE publishing the site code that writes here, like the others.
--
-- The daily counters have no clock in them — a day is the smallest thing they
-- know — so "now" needs its own place. One sketch per quarter of an hour;
-- every write deletes the slots older than an hour, so this table never grows
-- past a handful of rows and holds nothing by tonight.
--
-- An appliance asks for the update manifest every fifteen minutes, so merging
-- the last two slots catches every box that is on, and a box switched off
-- drops out of the number within half an hour.
CREATE TABLE IF NOT EXISTS appliances_live (
  slot TEXT PRIMARY KEY,
  boxes_hll BLOB
);
