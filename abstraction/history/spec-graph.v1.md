---
id: spec-graph
title: Spec store
kind: design
parent: core
version: 1
---

The spec is a small graph of Markdown files, one node per file, that a person can read whole.

## Invariants

- Only the header, the summary and the Invariants and Bans lists are parsed. The rest of a node file is left untouched.
- `thinspec check` reports any node and any spec over its line cap (30 and 150 by default).
- The invariants and bans of a node bind every node under it.
- A revision needs a reason, and copies the current text to `history/<id>.v<N>.md` before the version changes.

## Bans
