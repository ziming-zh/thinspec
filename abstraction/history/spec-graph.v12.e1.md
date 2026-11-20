---
id: spec-graph
title: Spec graph
kind: component
parent: hold-the-spec
version: 12
---

**Motivation.** The spec is read by a person in one sitting, and by an agent before each task. Both have to find what binds them without being told where to look.

**Challenge.** Left alone, a spec grows the way code does: a node for every module, a list of rules in no order, names that need explaining. Then nobody reads it.

**Approach.** The spec is a tree of short files, and each node tells one level of the story and only that level: why it is needed, what makes it hard, how it is done. What is more concrete goes to a node under it, so reading down the tree is zooming in.

## Invariants

- A node tells one level, in order: the motivation, the challenge, the approach (for the core, the insight). It states the few rules that hold at its level. A part of it gets a node of its own only when it differs from its siblings in what can be decided about it: a rule of its own, results of its own, or a choice the person would make about it alone. Where parts would differ only in how they are coded, the node is a leaf and the rest is tasks.
- Under the core, a design is a decision that sets the direction: a choice with another way that was turned down. A component is a part of the system that carries designs out, and it sits under the node it serves. A code module or a file is neither: it is work, and it shows as tasks.
- A design is named by its decision, in a plain sentence. A component is named for what it is, as a noun phrase. Either is understood by someone who reads only the tree.
- A node is a short file a person can edit by hand: its story, its rules and its bans. It holds only what is there: nothing is listed ahead of time, and a component is added once the person has said which. For a system that is already written the tree is taken from its paper's high-level structure, and where the code departs from it the node says how it is built and why. `thinspec check` reports a node over 30 lines, and a view, a node with the nodes under it, over 150.
- The invariants and bans of a node bind every node under it.
- The nodes under one node are listed in the order they are to be read: designs before components, and within each the order the person gives.

## Bans
