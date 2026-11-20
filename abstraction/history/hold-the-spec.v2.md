---
id: hold-the-spec
title: People hold the spec, not the code
kind: design
parent: core
version: 2
---

**Motivation.** The person answers for the system, and agents write it faster than anyone can read.

**Challenge.** Reviewing the code does not keep up, and a long design document is not read either. Whatever the person holds has to stay small while the code grows.

**Approach.** The person holds a thin spec and nothing else: the core, a few designs under it, and the components that carry them out, each a short text. The other way, having people review what agents write, was turned down. The spec is kept by the Spec graph.

## Invariants

- The spec is small enough for one person to read whole, and it stays that small while the code and the tasks grow.
- Everything a person maintains is in the spec: the designs, their invariants and their bans. The code under it belongs to the agents.

## Bans
