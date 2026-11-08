# Mathematical notation in reports

The New Pronote report overview and detailed analysis render mathematics with locally bundled **KaTeX 0.19.1**. The browser loads JavaScript, CSS and WOFF2 fonts from the same origin; no CDN, math service or provider call is needed.

Explicit LaTeX delimiters `\(...\)`, `\[...\]` and `$$...$$` are supported. Single dollar signs are deliberately left as text to avoid turning monetary amounts into mathematics. Existing short equations such as `BC² = AB² + AC²` or `BC = 5 cm` receive mathematical typography without changing the saved report. Grades like `3/6` stay ordinary text.

The renderer only touches report text nodes. Existing escaping stays in place; links, code, buttons and activity logs are ignored. KaTeX runs with `trust: false`, bounded expansion/size and no shared macros. Invalid notation falls back to its original text. A second rendering pass is idempotent. Long display formulas scroll within the report rather than expanding the mobile page.

Tests cover equation preservation, delimiters, currency and grades, invalid markup fallback, blocked links, no external requests, and a mobile viewport. The actual saved H report renders three expressions in the tested visible sections. This is display formatting, not a correction of source mathematics or pedagogical content.

Official references: [KaTeX rendering](https://katex.org/docs/autorender.html), [options](https://katex.org/docs/options.html). The MIT license is included in `mvp/static/vendor/katex/LICENSE.txt`.
