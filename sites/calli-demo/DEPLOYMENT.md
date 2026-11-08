# Calli public exploration

Live: https://calli-demo.leisurelychestnut.chatgpt.site · [Testing guide](https://calli-demo.leisurelychestnut.chatgpt.site/guide).

The existing public deployment was updated to Sites version 9 on 8 November 2026 at 13:01 UTC (source `4eaec76dc73dab30fe7341aed772dad866c73872`). This public release omits hosting identity and generated output, and updates the video link to the final YouTube upload. It includes the research-informed Devin exercise, simplified family assessment view, aggregate usage counters and local KaTeX formula rendering.

```sh
cd sites/calli-demo
npm run check
npm run serve
```

The self-contained Worker is `dist/server/index.js`. School-data routes remain read-only; provider runs, microphone and native PRONOTE writes are disabled. Only the bounded `POST /metrics/event` increments a daily usage aggregate. There is no public statistics reader. [Counting method and private access](docs-analytics.md).

To deploy this export to a distinct Site, use that Site’s own `.openai/hosting.json` and declare `"d1": "DB"`. Sites applies the schema-only migration in `drizzle/`. Without D1 the demo still works but visits are not persisted. Keep the existing hosted Site identity when updating it; do not create a duplicate.

Verification: 44 automated tests; browser checks for one event per view per document, no cookies, Do Not Track, family source grade and collapsed planning; production D1 contains the expected table and one recorded technical test event.

Version 9 consolidates the public mode explanation under “À propos de cet espace”, removes redundant demo labels, and links the final narrated YouTube film. No execution or permission boundary changed.
