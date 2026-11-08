# Demo usage counters

The public demo records aggregate page and feature opens in its own Cloudflare D1 database. The product UI stays unchanged.

## Read the counts

The Site owner's **Settings → Database** viewer exposes binding `DB`, table `daily_metrics`. The Sites connector can also read this table privately. There is no public analytics endpoint. Rows contain only UTC date, event name and count.

| Event | Meaning |
| --- | --- |
| landing | English or French landing opened |
| workspace | New Pronote workspace opened |
| teacher | Teacher appreciation view opened |
| parent | Family view opened |
| practice | Devin exercise preview opened |
| outing | School trip view opened |
| video | YouTube demo link clicked |
| guide | Testing guide opened |

Each event is counted at most once per document load. Reloading or opening a new tab can count again. These are **opens, not unique people**. Do not add landing and workspace counts and call that total visitors. Counts start at this deployment; there is no historical backfill.

## What is stored

Only `{day, event, count}` is persisted. The tracker does not set cookies, use localStorage, fingerprint visitors, record pupil data, or store IPs, user agents, referrers or full URLs. Infrastructure may maintain its own service logs. Do Not Track and Global Privacy Control suppress tracking. Playwright/WebDriver visits are excluded by default. Automated traffic and repeat visits can still affect counts; this is not an audited audience measurement.

`POST /metrics/event` accepts one allowlisted event, validates same origin, limits payload size, and atomically increments the daily aggregate. It cannot modify school data. If metrics are unavailable, the demonstration continues. Tests use intercepted requests; one explicit production verification open is recorded separately in the delivery notes.

## Deployment

`.openai/hosting.json` declares D1 binding `DB`. The schema-only migration in `drizzle/` creates `daily_metrics`. Sites applies migrations during deployment. Keep existing migrations immutable; add a new migration for later changes.
