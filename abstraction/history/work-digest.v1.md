---
id: work-digest
title: Work digest
kind: component
parent: hold-the-spec
version: 1
---

**Motivation.** Under a component the work piles up as tasks, and a list of tasks reads like a commit log: many small changes to code. The person decides from what the component can now do, what was tried and turned back, and what the runs came to.

**Challenge.** The further down the tree, the more of the work is delegated and the less of it the person wants to see. Nothing can sort it for them mechanically: what matters is a judgment, and a list that only grows is not read.

**Approach.** Each node carries a digest in place of its task list: what it has now, what was turned back, and the results of runs, for and against. The agent that did the work writes it, in the person's terms, a line each. A section holds only a few lines, so adding to a full one means merging or dropping. The tasks stay in the record, for the agents.

## Invariants

- A digest has three parts: what the node has now, what was tried and turned back, and what runs of experiments came to, for and against. An ordinary check that passes is not a result.
- A line says one thing a person can decide from, in their terms: no task id, no file, no count of tests.
- A section holds five lines at most. The agent rewrites it whole: it merges and drops, and never only appends.
- The further down the tree a node is, the more its digest stands in for its work. A design shows only how much is under it.

## Bans
