---
id: budget-monitor
title: Tasks and budgets
kind: design
parent: core
version: 1
---

Work is delegated as tasks under a design. Effort against the estimate judges the design.

## Invariants

- A task cannot exist without a check.
- A task cannot start without a budget in trials, patches or minutes.
- The alarm is raised when the next unit of work would exceed the budget, so a task whose last allowed trial passes can still close as done.
- Only a decision by a person reopens or closes a task that is out of budget.
- Over-budget tasks in a row flag the design. A task that finishes within budget, or a revision, ends the run.

## Bans
