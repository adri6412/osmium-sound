# Site analytics: counters only

The site keeps two numbers, unique visitors and downloads, and keeps nothing
about the people behind them. The IP address and the user-agent are read inside
the request — to tell a person from a scanner, and to make that day's visitor
hash — and are gone when the request ends. What reaches D1:

| table | key | what it holds |
| --- | --- | --- |
| `site_daily` | day, path | views, and unique visitors as a HyperLogLog sketch. The `*` row of a day holds that day's sketch merged across pages, with its counter left at 0 |
| `downloads_daily` | day, file, kind | hits, and unique downloaders as a sketch. `kind` is `served` (the file went out) or `click` (a download button was pressed) |
| `site_breakdown` | day, dim, value | one count per page view (`country`, `browser`, `os`, `source`, `channel`) or per download (`dl_country`, `dl_browser`, `dl_os`, `dl_network`) |
| `site_drops` | day, reason, asn | how much was filtered out, by reason and network |
| `appliances_live` | slot | one sketch per quarter of an hour: how many appliances are on now. Slots older than an hour are deleted on every write |
| `site_salts` | day | the random salt of the day, deleted the day after; plus one per week (`week-YYYY-MM-DD`) used only for the appliance count |

Written by [`functions/api/o.js`](../functions/api/o.js) (the browser beacon)
and [`functions/_middleware.js`](../functions/_middleware.js) (the `.apk` and
`.jar` the site serves itself, plus what was filtered out). The counter
helpers are in [`functions/_lib/counters.js`](../functions/_lib/counters.js),
the sketch in [`functions/_lib/hll.js`](../functions/_lib/hll.js), the daily
hash in [`functions/_lib/visitor.js`](../functions/_lib/visitor.js).

Days are **UTC**, because the visitor hash is salted per UTC day: a stored day
that spanned two salts would count the same person twice inside it.

Appliances are salted per **week** instead (`weeklySalt` in `_lib/visitor.js`).
An appliance asks for the update manifest every fifteen minutes, so with a
daily salt the same box would be a new box every morning. Merging the days of
one week gives how many boxes; merging across weeks gives the sum of the
weeks, not distinct boxes — which is why the dashboard answers a week at a
time, with the per-day numbers beside it.

Reading the sketches needs the same `hll.js`: `merge()` the rows in the period,
then `count()`. Unique visitors for a day are the union of that day's rows
across paths; for a month, the union of its days. SQL cannot do this — the
dashboard has to.

Tests: `node tests/test-site-analytics.mjs` from the repository root.

## The deploy is one sequence, and the order matters

Two repositories write these tables and one reads them, so nothing here works
half-done. The other side of it is in `osmium-iso-tracker`, already written:
the worker counts downloads without keeping addresses, and every dashboard
query reads the aggregate tables.

1. **Create the tables and fold in the history.** `01_aggregates.sql`, then
   `02_backfill_sketches.mjs` (the runbook is in its header). Nothing reads or
   writes the new tables yet, so this is the safe part. If the old log has rows
   from before the current hosting lists, run `migration_is_dc.sql` in the
   tracker repo first: the backfill trusts `is_dc` to tell a download from a
   machine.
2. **Deploy the worker**, `npx wrangler deploy` in `osmium-iso-tracker`. From
   here the dashboard reads the new tables — which already hold the history —
   and `download_sessions` stops growing.
3. **Publish the site**: push `main`, which deploys Cloudflare Pages. From here
   the site writes the new tables. Between 2 and 3 it still writes the old
   ones; nothing reads them, so it does not matter.
4. **Delete the old tables, right away.** `03_drop_legacy.sql` here and
   `drop_download_sessions.sql` there, after `migration_downloads.sql` has
   folded the download history in. Do not leave this for next week: the privacy
   notice published at step 3 says no address is kept, and step 4 is what makes
   that true.

Step 4 cannot be undone, and that is the point.

## What changed in osmium-iso-tracker

Done, in commit `af1821f` of that repository, not deployed:

- `src/index.js` counts a download instead of logging it. A download is now a
  GET with no `Range` or a `Range` from byte zero, because there is no row per
  address left to fold a resumed download back into; and only the network
  decides whether it counts, because curl, wget, a download manager and the
  F-Droid client are all "programs" to the user-agent rules.
- `src/hll.js`, `src/visitor.js` and `src/counters.js` are copies of the files
  in `_lib/`, byte for byte, like `traffic.js` already was. Change one, copy it
  across, `cmp` the two.
- `src/api.js` is rewritten end to end: both dashboards read counters and
  merge sketches. `src/legacy.js` and the four `/stats/legacy` routes are gone
  with the tables they read, and so are the schema files of those tables —
  the tables that replace them are created from here, where one definition
  serves both writers.
- `src/dashboard.html` drops what a counter cannot answer: visits, bounce
  rate, time on page, entry and exit pages, the live visitor count, the
  per-visit filters and the list of user-agents that downloaded.
- `test-stats.mjs` runs both dashboard queries against a throwaway database.

### Still holding IP addresses after all this

Nothing, once step 4 has run. Cloudflare keeps edge logs of its own, with its
own purposes and periods, and GitHub sees the downloads it serves: both are
named in the privacy notice, because neither is ours to switch off.
