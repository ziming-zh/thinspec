---
id: spec-graph
title: Spec graph
kind: design
parent: core
version: 3
---

The part people hold: the system's design as a tree of its components under one core, small enough for one person to read whole.

## Invariants

- A node is a component of the system's design, one that would survive a rewrite of the code. A code module or a file is work under a node, not a node.
- A node is named for what it is: a noun phrase that someone who reads only the tree understands. A slogan, a sentence or a phrase about an idea is not a name.
- The design layer grows only with a new component, so it stays narrow while the code and the tasks grow.
- A node is a short file a person can edit by hand: a summary, invariants, bans. `thinspec check` reports a node or a spec over its line cap (30 and 150 by default).
- The invariants and bans of a node bind every node under it.
- A design changes by revision: the reason is recorded and the old text is kept.

## Bans
