---
id: spec-graph
title: Spec graph
kind: component
parent: hold-the-spec
version: 13
---

**Motivation.** The spec is read by a person in one sitting, and by an agent before each task. Both have to find what binds them without being told where to look.

**Challenge.** Left alone, a spec grows the way code does: a node for every module, a list of rules in no order, names that need explaining. Then nobody reads it.

**Approach.** The spec is a tree of short files, and each node tells one level of the story and only that level: why it is needed, what makes it hard, how it is done. What is more concrete goes to a node under it, so reading down the tree is zooming in.

## Invariants

- A node tells one level, in order: the motivation, the challenge, the approach (for the core, the insight). It states the few rules that hold at its level. A part of it gets a node of its own only for a decision of its own: a choice about it alone, with another way on record, that changes what the system delivers. A part with only a rule of its own gives its node an invariant, not a child, and a setting of the node is not a part. Where parts would differ only in how they are coded, the node is a leaf and the rest is tasks.
- Under the core, a design is a decision that sets the direction: a choice with another way that was turned down. A component is a part of the system that carries designs out, and it sits under the node it serves. A code module or a file is neither: it is work, and it shows as tasks.
- A design is named by its decision, in a plain sentence. A component is named for what it is, as a noun phrase. Either is understood by someone who reads only the tree.
- A node is a short file a person can edit by hand: its story, its rules and its bans. It holds only what is there: nothing is listed ahead of time, and a component is added once the person has said which. `thinspec check` reports a node over 30 lines, and a view, a node with the nodes under it, over 150. For a system that is already written the tree is taken from its paper's high-level structure, and a difference in the code goes as high as what it changes, whichever side it came from: to the design it contradicts when it changes what the system claims, to a node of its own when it is a part with a decision of its own, to an invariant when it adds a guarantee, else to a line in the digest, with the reason.
- The invariants and bans of a node bind every node under it.
- The nodes under one node are listed in the order they are to be read: designs before components, and within each the order the person gives.

## Bans
