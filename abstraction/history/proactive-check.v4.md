---
id: proactive-check
title: Overrun signals a wrong design
kind: design
parent: core
version: 4
---

**Motivation.** Looking for a wrong design needs a sign of it, and one that shows while the design is still cheap to change.

**Challenge.** Whatever the agent produces, it can make come out right. The checks pass because the patches were written to pass them, and its account of its own progress is its own. The sign has to be one it cannot patch away.

**Approach.** What it cannot hide is the effort. Every task starts with an estimate of what it should take: the agent's own, or the person's when the agent cannot tell or when they give one. The work is counted from outside the agent, and effort far past the estimate is read as a signal about the design above the task. The other ways, trusting the checks that pass or capping the effort, were turned down. The counting and the pause are the Budget monitor's.

## Invariants

- Effort far past its estimate counts as evidence about the design above the task, not only about the code.
- A budget is an estimate, not a limit. Reaching it stops nothing.
- An estimate is stated in what a person can judge: how many runs of the check until the result is solid, and how much code changes. Time is measured, never budgeted.
- Work is counted outside the agent, which cannot change its own numbers. Where an agent gives no place to count from, what it reports is marked as its own.

## Bans
