---
id: spec-graph
title: Thin spec
kind: design
parent: core
version: 2
---

What people hold: a spec small enough for one person to read whole, drawn as a graph of designs under one core abstraction.

## Invariants

- A node is an idea that would survive a rewrite of the code. A module is work under a design, not a design.
- The design layer grows only with a new idea, so it stays narrow while the code and the tasks grow.
- A node is a short file a person can edit by hand: a summary, invariants, bans. `thinspec check` reports a node or a spec over its line cap (30 and 150 by default).
- The invariants and bans of a node bind every node under it.
- A design changes by revision: the reason is recorded and the old text is kept.

## Bans
