# Calli public exploration

Live: https://calli-demo.leisurelychestnut.chatgpt.site · [Testing guide](https://calli-demo.leisurelychestnut.chatgpt.site/guide).

The existing public deployment was updated to Sites version 11 on 8 November 2026 at 13:09 UTC (source `c9d8f66acd28d4a90070f2b806735c11d3f8e7f8`). This public release omits hosting identity and generated output, and updates the video link to the final YouTube upload. It includes the research-informed Devin exercise, simplified family assessment view, aggregate usage counters and local KaTeX formula rendering.

```sh
cd sites/calli-demo
npm run check
npm run serve
```

The self-contained Worker is `dist/server/index.js`. School-data routes remain read-only; provider runs, microphone and native PRONOTE writes are disabled. Only the bounded `POST /metrics/event` increments a daily usage aggregate. There is no public statistics reader. [Counting method and private access](docs-analytics.md).

To deploy this export to a distinct Site, use that Site’s own `.openai/hosting.json` and declare `"d1": "DB"`. Sites applies the schema-only migration in `drizzle/`. Without D1 the demo still works but visits are not persisted. Keep the existing hosted Site identity when updating it; do not create a duplicate.

Verification: 44 automated tests; browser checks for one event per view per document, no cookies, Do Not Track, family source grade and collapsed planning; production D1 contains the expected table and one recorded technical test event.

Version 11 consolidates the public mode explanation under “À propos de cet espace”, removes redundant demo labels, and links the final narrated YouTube film. No execution or permission boundary changed.

The captured workspace script URL is versioned so returning browsers receive the updated copy as well. Production browser verification confirmed the workspace loads and displays “Espace de travail”.


Version 12 adds the school-pilot interest form and anonymous map in both languages, published at 13:29 UTC on 8 November 2026 (source `59df1a7d8e6c1296fc5838fc192f179fd4406ce0`). A schema-only migration creates the private `pilot_interest` table. POST `/pilot/interest` collects explicit interest, not product accounts; native actions remain disabled. [Operational details](docs-pilot.md). 49 tests pass, including real SQLite.
