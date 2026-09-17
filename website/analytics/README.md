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
| `site_salts` | day | the random salt of the day, deleted the day after (unchanged) |

Written by [`functions/api/o.js`](../functions/api/o.js) (the browser beacon)
and [`functions/_middleware.js`](../functions/_middleware.js) (the `.apk` and
`.jar` the site serves itself, plus what was filtered out). The counter
helpers are in [`functions/_lib/counters.js`](../functions/_lib/counters.js),
the sketch in [`functions/_lib/hll.js`](../functions/_lib/hll.js), the daily
hash in [`functions/_lib/visitor.js`](../functions/_lib/visitor.js).

Days are **UTC**, because the visitor hash is salted per UTC day: a stored day
that spanned two salts would count the same person twice inside it.

Reading the sketches needs the same `hll.js`: `merge()` the rows in the period,
then `count()`. Unique visitors for a day are the union of that day's rows
across paths; for a month, the union of its days. SQL cannot do this — the
dashboard has to.

Tests: `node tests/test-site-analytics.mjs` from the repository root.

## The deploy is in three parts and they are not independent

Publishing this site before the dashboard is ready leaves the dashboard
querying tables that no longer receive rows; running `03_drop_legacy.sql`
before that leaves it querying tables that no longer exist.

1. **osmium-iso-tracker first.** Update the queries below and deploy the
   worker. Until step 3 it can keep reading the old tables, so it can be
   deployed while both exist.
2. **This site.** Push to `main`, which publishes it; from that moment the new
   tables receive the counts and the old ones stop growing.
3. **The database**, in order: `01_aggregates.sql`, then
   `02_backfill_sketches.mjs` (see the runbook in its header), then
   `03_drop_legacy.sql` — that last one deletes the stored IP addresses and
   cannot be undone.

## What has to change in osmium-iso-tracker

`src/traffic.js` does **not** change: it is byte-for-byte the copy of
`website/functions/_lib/traffic.js` and neither was touched. Copy
`website/functions/_lib/hll.js` into that repo instead — the worker needs it to
read the sketches.

### `src/api.js`, `siteStats()` — every query in it reads a dropped table

| line | query | what it becomes |
| --- | --- | --- |
| 131 | `MIN(started) FROM site_sessions` | `MIN(day) FROM site_daily` (a date string, not a timestamp: `since` changes type) |
| 77–90 | `SESSION_DIMS`, 12 dimensions | `site_breakdown`, 5 dimensions. `campaign`, `entry`, `exit`, `region`, `city`, `device` and `lang` are gone |
| 94–119 | `siteWhere()`, filter by dimension, by page, by goal | a dimension filter cannot restrict a count that was never joined to a visit. Either drop the filters or keep them only as a breakdown selection |
| 121–126 | `SESSION_METRICS` | `visitors` = `count(merge(…visitors_hll))`, `pageviews` = `SUM(views)`. `visits`, `bounces` and `engaged_ms` no longer exist |
| 145–154 | `kpi`, `series`, `kpiPrev`, `seriesPrev` | group `site_daily` by day; merge the sketches per bucket in JS |
| 156–162 | `dim_*` | `SELECT value, SUM(count) FROM site_breakdown WHERE dim = ? AND day BETWEEN ? AND ? GROUP BY value` — the number is page views, not visitors |
| 164–169 | `pages` | `site_daily` by path; `time_ms` and `scroll` are gone |
| 171–175 | `goals` | `downloads_daily`; outbound clicks are no longer collected |
| 177–179 | `live` (visitors in the last 5 minutes) | gone: nothing carries a `last_seen` any more |
| 182–184 | `qReasons` | `SELECT reason, SUM(count) FROM site_drops WHERE day BETWEEN ? AND ? GROUP BY reason` |
| 185–188 | `qNetworks` | `SELECT asn, MIN(as_org), SUM(count) FROM site_drops … GROUP BY asn` |
| 189–194 | `qSignals` | gone: `engaged_ms`, `max_scroll`, `interacted` and `http_proto` are not collected |
| 195–200 | `qServer` (over `page_views`) | `site_drops` is now the whole server-side picture; there is no `human_ips` |
| 92 | `REASONS` | add `probe` (server-side probe paths, folded into `is_bot` before), remove `burst` (it needed a session to count pages in) |
| 202–247 | the JSON that comes out | `kpi`, `series`, `dims`, `quality` all change shape; `dashboard.html` reads them |

### `src/api.js`, `downloadStats()`

| line | query | what it becomes |
| --- | --- | --- |
| 304–305 | `fromSite` over `site_events` | `SELECT SUM(hits) FROM downloads_daily WHERE file LIKE 'file.osmiumsound.it/%'` |
| 311–312 | `fromSitePrev` | the same, previous period |
| 318–323 | `filesFromSite` | `downloads_daily` grouped by `file` |

The rest of `downloadStats()` reads `download_sessions`, which this migration
does not touch.

### `src/legacy.js` and `src/index.js`

`legacy.js` reads `page_views`, `site_visits` and `download_sessions` from end
to end. After step 3 the first two are gone, so `/stats/legacy`,
`/stats/legacy/site`, `/stats.json` and `/stats/site.json` (routed at
`index.js:69–72`) return errors. Remove those four routes and the file, or cut
it down to the downloads half.

### Still holding IP addresses after all this

`src/index.js:144–172` (`logDownload`) writes `download_sessions` with the IP
address and the user-agent in clear, one row per file per address per half
hour, with no retention. Every file on file.osmiumsound.it goes through it.
Nothing in this repository can change that, and the site's privacy notice does
not claim otherwise — it is the obvious next piece of the same work.
