---
id: budget-monitor
title: Budget monitor
kind: component
parent: overrun-signal
version: 6
---

Counts the effort of every task against its estimate: work is delegated as tasks with a check and an estimate, the agent is told when the estimate is reached, and the task is paused when it goes far past it.

## Invariants

- A task cannot exist without a check.
- A task cannot start without a budget: runs of the check, lines changed, or both.
- An agent that cannot size the work starts on its own numbers, marks them as a guess, and asks the person for theirs without waiting. A question left unanswered changes nothing: the guess stands.
- The person can replace a budget with their own numbers at any time before the task is paused. It is then theirs, and no longer a guess.
- When a task reaches its estimate, the agent is told once to look at why, and to tell the person if the cause is the design.
- When a budgeted measure goes far past its estimate (twice it by default), the task is paused and goes to a person.
- Paused tasks in a row flag the node they are under, and the design above it. A task that finishes without being paused, or a revision, ends the run.

## Bans
