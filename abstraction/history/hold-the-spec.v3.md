---
id: hold-the-spec
title: People hold the spec, not the code
kind: design
parent: core
version: 3
---

**Motivation.** A failure that reports nothing can only be looked for against something stated. So the abstraction has to be written down, and held by the person who answers for the system.

**Challenge.** Reviewing the code does not keep up, and a long design document is not read either. Whatever the person holds has to stay small while the code grows. And it has to stay sound: a spec that contradicts itself gives nothing to check against.

**Approach.** The person holds a thin spec and nothing else: the core, a few designs under it, and the components that carry them out, each a short text that follows from the one above it. The other way, having people review what agents write, was turned down. The spec is kept by the Spec graph.

## Invariants

- The spec is small enough for one person to read whole, and it stays that small while the code and the tasks grow.
- Everything a person maintains is in the spec: the designs, their invariants and their bans. The code under it belongs to the agents.
- The spec is sound: every node follows from the node above it, and no node contradicts a node above or under it.

## Bans
