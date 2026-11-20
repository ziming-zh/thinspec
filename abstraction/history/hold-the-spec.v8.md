---
id: hold-the-spec
title: People hold the spec, not the code
kind: design
parent: core
version: 8
order: 1
---

**Motivation.** A person's context is far smaller than an agent's: an agent writes more in an hour than a person can read in a week. So the person is the bottleneck of the project, and they are also the one who decides where it goes.

**Challenge.** Whatever takes their attention takes it from something else. Reading code spends it on the part that decides the least, and a long design document is not read at all. What they hold has to stay small while the code grows, and sound, or there is nothing to check the work against.

**Approach.** Spend the person's attention only where it decides the most: on a thin spec that fixes the direction. The core, a few designs under it and the components that carry them out, each a short text that follows from the one above it. Everything under the spec is the agents'. The other way, having people review what agents write, was turned down.

## Invariants

- The spec is small enough for one person to read whole, and it stays that small while the code and the tasks grow.
- Everything a person maintains is in the spec: the designs, their invariants and their bans. The code under it belongs to the agents.

## Bans
