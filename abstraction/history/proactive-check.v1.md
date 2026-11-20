---
id: proactive-check
title: Overrun signals a wrong design
kind: design
parent: core
version: 1
---

How a wrong design is noticed. An agent given a task under a wrong design makes it work anyway, with patches, and every check passes. So effort far past its estimate is read as a signal about the design above the task. The other choices were to trust passing checks, or to cap the effort.

## Invariants

- Effort far past its estimate counts as evidence about the design above the task, not only about the code.
- A budget is an estimate, not a limit. Reaching it stops nothing.
- Work is counted outside the agent, which cannot change its own numbers.

## Bans
