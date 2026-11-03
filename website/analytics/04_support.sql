-- The support-form table. Written by website/functions/api/support.js when a
-- visitor sends a report from the #support form on the home page.
--
--   npx wrangler d1 execute osmium-downloads --remote --file=website/analytics/04_support.sql
--
-- The function also runs this CREATE lazily on every request, so the table
-- exists after the first submission even without running this file. Keep this
-- statement in step with the SCHEMA constant in support.js.
--
-- No IP address or user-agent is stored, matching the aggregate-only analytics
-- in 01_aggregates.sql. The .zip attachment itself lives in R2
-- (bucket osmium-support, key r2_key), not in D1.

CREATE TABLE IF NOT EXISTS support_requests (
  id         TEXT PRIMARY KEY,      -- short reference shown to the visitor, e.g. SR-XXXX-YYYY
  created_at INTEGER NOT NULL,      -- epoch ms
  model      TEXT NOT NULL,         -- the PC the device runs on (required)
  problem    TEXT NOT NULL,         -- the description (required)
  email      TEXT NOT NULL DEFAULT '',   -- reply address (optional)
  r2_key     TEXT NOT NULL DEFAULT '',   -- support/<id>.zip in R2, or '' if none
  size       INTEGER NOT NULL DEFAULT 0, -- attachment size in bytes
  notified   INTEGER NOT NULL DEFAULT 0  -- 1 if the email notice was sent
);

-- Browse the newest reports:
--   npx wrangler d1 execute osmium-downloads --remote \
--     --command "SELECT id, datetime(created_at/1000,'unixepoch') AS when_utc, model, email, r2_key FROM support_requests ORDER BY created_at DESC LIMIT 20"
-- Fetch an attachment:
--   npx wrangler r2 object get osmium-support/support/<id>.zip --file <id>.zip
