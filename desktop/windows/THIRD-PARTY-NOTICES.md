# Desktop preview dependencies

The offline preview redistributes the following pinned upstream components.
Archive integrity and per-file SHA-256 values are in `preview-deps.lock.json`.
Upstream license texts accompany the files in `preview/vendor/licenses` and
`licenses/WebView2-LICENSE.txt` in the desktop distribution.

| Component | Version | Upstream license |
| --- | --- | --- |
| markdown-it | 15.0.3 | MIT |
| markdown-it-footnote | 4.0.0 | MIT |
| markdown-it-task-lists | 2.1.1 | ISC |
| Mermaid | 12.3.0 | MIT |
| DOMPurify | 3.4.17 | MPL-2.0 OR Apache-2.0 |
| highlight.js CDN assets | 11.12.0 | BSD-3-Clause |
| KaTeX | 0.19.1 | MIT |
| Microsoft WebView2 SDK | 1.0.4314.35 | Microsoft WebView2 SDK license |

The Microsoft Edge WebView2 Runtime is a separate installed runtime. The desktop
uses its Evergreen installation and does not include a private browser/runtime.
No application credential, configuration, note or operator address is part of
these dependencies or the compiled application.
