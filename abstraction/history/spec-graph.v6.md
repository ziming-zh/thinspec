---
id: spec-graph
title: Spec graph
kind: component
parent: hold-the-spec
version: 6
---

**Motivation.** The spec is read by a person in one sitting, and by an agent before each task. Both have to find what binds them without being told where to look.

**Challenge.** Left alone, a spec grows the way code does: a node for every module, a list of rules in no order, names that need explaining. Then nobody reads it. And a change to one node leaves the nodes around it telling the old story, with nothing to show for it.

**Approach.** The spec is a tree of short files, and each node tells one level of the story and only that level: why it is needed, what makes it hard, how it is done. What is more concrete goes to a node under it, so reading down the tree is zooming in. A change to a node is carried to the node above it and the nodes under it, and on from any of those that changes, until the whole tree tells one story again.

## Invariants

- A node tells one level, in order: the motivation, the challenge, the approach (for the core, the insight). It states the few rules that hold at its level. A detail of how it is done belongs to a node under it.
- Under the core, a design is a decision that sets the direction: a choice with another way that was turned down. A component is a part of the system that carries designs out, and it sits under the node it serves. A code module or a file is neither: it is work, and it shows as tasks.
- A design is named by its decision, in a plain sentence. A component is named for what it is, as a noun phrase. Either is understood by someone who reads only the tree.
- A node is a short file a person can edit by hand. `thinspec check` reports a node or a spec over its line cap (30 and 150 by default).
- The invariants and bans of a node bind every node under it.
- A revision is not finished at the node revised. The node above it and the nodes under it are read again against the new text: each is revised, or recorded as still following, with the reason. `thinspec check` reports a node not yet read again.

## Bans
