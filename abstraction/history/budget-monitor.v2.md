---
id: budget-monitor
title: Tasks and budgets
kind: design
parent: core
version: 2
---

Work is delegated as tasks under a design. A budget is the estimate of what a task should cost, and effort far past it judges the design.

## Invariants

- A task cannot exist without a check.
- A task cannot start without a budget in trials, patches or minutes.
- A budget is an estimate, not a limit. Reaching it stops nothing.
- When a task reaches its estimate, the agent is told once to look at why, and to tell the person if the cause is the design.
- When trials, patches or minutes go far past the estimate (twice it by default), the task is paused and goes to a person.
- Only a decision by a person reopens or closes a paused task.
- Paused tasks in a row flag the design. A task that finishes without being paused, or a revision, ends the run.

## Bans
