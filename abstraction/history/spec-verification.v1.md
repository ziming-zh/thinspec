---
id: spec-verification
title: Spec verification
kind: component
parent: hold-the-spec
version: 1
---

**Motivation.** The person holds only the spec, so the spec has to stay true: to the work done under it, and to itself. A node nobody has checked since the work moved on is a guess.

**Challenge.** Nothing fails when a node stops fitting. The agent goes on to the next change, and a change to one node leaves the nodes around it telling the old story. A check left to the agent's memory is the first thing it skips.

**Approach.** What happens drives the checking, and what is owed is kept in the record, outside the agent. A round of work under a node puts that node up to be verified against it. A change to a node puts the node above it and the nodes under it up to be verified against the new text. Verifying a node ends in one of four ways: it still fits, the evidence overturns it, something new was learned, or it belongs a level up. The last three change a node, and that change is carried on the same way, until nothing is owed.

## Invariants

- A node is owed a verification when a round of work under it ends: a task closes with a result, or an agent's turn ends having changed code or run the check under it.
- A node is owed a verification when the node above it or a node under it changes. A revision is not finished at the node revised.
- A verification ends in a record: the node is revised, moved up a level, or recorded as still fitting, with the reason.
- What is owed is counted from the record, not remembered by the agent. `thinspec check` and the overview list every node owed a verification until it is made.
- ThinSpec says which node is owed a verification and against what. Whether the node still fits is read by the agent or the person.

## Bans
