# Local browser dependencies

These pinned distribution files are served locally; the demo needs no CDN at runtime.

| Library | Version | Source | License file |
| --- | --- | --- | --- |
| ECharts | 5.6.0 | https://www.npmjs.com/package/echarts/v/5.6.0 | echarts.LICENSE |
| Marked | 18.1.3 | https://www.npmjs.com/package/marked/v/18.1.3 | marked.LICENSE |
| DOMPurify | 3.4.17 | https://www.npmjs.com/package/dompurify/v/3.4.17 | purify.LICENSE |

Markdown output is sanitized with a tag/attribute allowlist before insertion. Chart options are built from validated report data; model text is never executed as JavaScript.
