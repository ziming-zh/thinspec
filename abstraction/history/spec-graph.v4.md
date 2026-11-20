---
id: spec-graph
title: Spec graph
kind: component
parent: hold-the-spec
version: 4
---

The spec as files: a tree of nodes under one core, each a short file a person can edit by hand.

## Invariants

- Under the core there are two kinds of node. A design is a decision that sets the direction: a choice with an alternative that was turned down. A component is a part of the system that carries designs out.
- A design is named by its decision, in a plain sentence. A component is named for what it is, as a noun phrase. Either is understood by someone who reads only the tree.
- A component sits under the design it serves, or under the core when it serves several. A code module or a file is not a node: it is work, and it shows as tasks.
- A node is a short file a person can edit by hand: a summary, invariants, bans. `thinspec check` reports a node or a spec over its line cap (30 and 150 by default).
- The invariants and bans of a node bind every node under it.

## Bans
