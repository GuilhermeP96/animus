# Animus 0.9.5.3

- The Windows Knowledge workspace now opens in the dark Markdown reading view.
- Vault notes are grouped by their canonical folder hierarchy, with explicit
  controls to expand or collapse the tree.
- A bounded graphical vault projection is derived from canonical wikilinks;
  search narrows the projection without creating or rewriting notes.
- The desktop loads up to 2,000 notes for navigation while preserving bounded
  link extraction and rendering limits.
- Dark custom navigation removes the remaining native light tab surfaces.

The canonical vault, note identities, database, queue, credentials and peer
configuration are preserved. The graph is a projection of links already present
in Markdown; notes without wikilinks remain isolated nodes and no relationship is
invented.

Release assets include the Python wheel, Windows desktop ZIP, source-only
recovery ZIP and external `SHA256SUMS`. Verify all assets against the official
release before installation. The Windows installer additionally verifies the
internal desktop manifest and `Animus.exe` SHA-256.

The final desktop bytes were exercised on the existing Windows peer, including
default reading, the 1,903-note hierarchy, expand/collapse and Mermaid graph
rendering. This is not a clean-machine qualification and no Authenticode
signature is claimed.
