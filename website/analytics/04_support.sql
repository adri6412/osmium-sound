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
-- in 01_aggregates.sql. The attachments themselves live in R2 (bucket
-- osmium-support, one object per file under the support/<id>/ prefix; the keys
-- are in the files column), not in D1.

CREATE TABLE IF NOT EXISTS support_requests (
  id         TEXT PRIMARY KEY,      -- short reference shown to the visitor, e.g. SR-XXXX-YYYY
  created_at INTEGER NOT NULL,      -- epoch ms
  model      TEXT NOT NULL,         -- the PC the device runs on (required)
  problem    TEXT NOT NULL,         -- the description (required)
  email      TEXT NOT NULL DEFAULT '',   -- reply address (required by the form)
  r2_key     TEXT NOT NULL DEFAULT '',   -- R2 folder prefix support/<id>/, or '' if no files
  size       INTEGER NOT NULL DEFAULT 0, -- total size of all attachments, in bytes
  notified   INTEGER NOT NULL DEFAULT 0, -- 1 if the email notice was sent
  files      TEXT NOT NULL DEFAULT '[]'  -- JSON array of {name, key, size}, one per attachment
);

-- The function adds the files column to an older table with:
--   ALTER TABLE support_requests ADD COLUMN files TEXT NOT NULL DEFAULT '[]';

-- Browse the newest reports:
--   npx wrangler d1 execute osmium-downloads --remote \
--     --command "SELECT id, datetime(created_at/1000,'unixepoch') AS when_utc, model, email, files FROM support_requests ORDER BY created_at DESC LIMIT 20"
-- Fetch an attachment (take <key> from the files column, e.g. support/<id>/1-shot.png):
--   npx wrangler r2 object get osmium-support/<key> --file <name>
