---
id: budget-monitor
title: Budget monitor
kind: component
parent: overrun-signal
version: 5
---

Counts the effort of every task against its estimate: work is delegated as tasks with a check and an estimate, the agent is told when the estimate is reached, and the task is paused when it goes far past it.

## Invariants

- A task cannot exist without a check.
- A task cannot start without a budget in trials, patches or minutes.
- When a task reaches its estimate, the agent is told once to look at why, and to tell the person if the cause is the design.
- When trials, patches or minutes go far past the estimate (twice it by default), the task is paused and goes to a person.
- Paused tasks in a row flag the node they are under, and the design above it. A task that finishes without being paused, or a revision, ends the run.

## Bans
