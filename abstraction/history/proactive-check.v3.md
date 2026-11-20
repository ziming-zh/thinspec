---
id: proactive-check
title: Overrun signals a wrong design
kind: design
parent: core
version: 3
---

**Motivation.** A wrong design has to be noticed while it is still cheap to change.

**Challenge.** It does not announce itself. An agent given a task under a wrong design makes it work anyway, with patches, and every check passes.

**Approach.** What does show is the effort. Every task starts with an estimate, the work is counted from outside the agent, and effort far past the estimate is read as a signal about the design above the task. The other ways, trusting the checks that pass or capping the effort, were turned down. The counting and the pause are the Budget monitor's.

## Invariants

- Effort far past its estimate counts as evidence about the design above the task, not only about the code.
- A budget is an estimate, not a limit. Reaching it stops nothing.
- An estimate is stated in what a person can judge: how many runs of the check until the result is solid, and how much code changes. Time is measured, never budgeted.
- Work is counted outside the agent, which cannot change its own numbers.

## Bans
