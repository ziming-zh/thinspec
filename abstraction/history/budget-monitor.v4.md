---
id: budget-monitor
title: Budget monitor
kind: design
parent: core
version: 4
---

Counts the effort of every task against its estimate, which is how a wrong design is noticed: work is delegated as tasks with a check and an estimate, and effort far past the estimate judges the design above the task.

## Invariants

- A task cannot exist without a check.
- A task cannot start without a budget in trials, patches or minutes.
- A budget is an estimate, not a limit. Reaching it stops nothing.
- When a task reaches its estimate, the agent is told once to look at why, and to tell the person if the cause is the design.
- When trials, patches or minutes go far past the estimate (twice it by default), the task is paused and goes to a person.
- Paused tasks in a row flag the design. A task that finishes without being paused, or a revision, ends the run.
- Work is counted outside the agent, which cannot change its own numbers.

## Bans
