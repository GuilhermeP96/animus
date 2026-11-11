# Animus 0.9.5

- Windows Knowledge opens the configured canonical Obsidian vault directly:
  search, read, edit Markdown and curate title, project, status and sensitivity.
- SHA-256 revision checks, file locks, backups and audit preserve concurrent
  edits; verification requires explicit human acknowledgement.
- Offline Markdown rendering supports GFM tables, task lists, footnotes,
  callouts, highlighted code, math and Mermaid diagrams.
- Diagrams and images support zoom, drag to pan, fit, original size, keyboard
  controls and an expanded view. Tables support scrolling, expansion and CSV
  copy; diagrams support source copy and SVG export.
- Wikilinks and images resolve within the canonical vault. Active HTML and
  automatic external resources are blocked. No separate editable vault is made.
- Obsidian notes retain full Markdown through indexing and synchronization.
  Existing canonical files restore formatting during collection; missing source
  formatting is never invented. Note identities and configuration are preserved.

Upgrade the hub before peers so older indexing does not simplify Markdown.
Back up the existing database, configuration and vault before upgrading. Retain
the same data directory, identity and credentials. Windows advanced reading
requires Microsoft Edge WebView2 Runtime; the SDK and renderer libraries ship
locally with pinned hashes and third-party licenses. Debian remains headless.

Release assets include the Python wheel, Windows desktop ZIP, source-only
recovery ZIP and SHA256SUMS. Verify the official release hashes before use.
