---
id: proactive-check
title: Check the design as the work goes, don't wait for a failure
kind: design
parent: core
version: 7
order: 2
---

**Motivation.** A wrong design does not fail, and the person cannot find it by reading: there is too much to read, and their attention is the bottleneck. So it has to be looked for, without their reading, while the work goes on and the design is still cheap to change.

**Challenge.** The one in a place to look is the agent, and it is the one that patches. Whatever it produces, it can make come out right: the checks pass because the patches were written to pass them, and its account of its own progress is its own. And a check it is left to remember is the first thing it skips.

**Approach.** Two checks, of two kinds. The agent reads each round of work against the node it sits under, and what is owed is counted from the record, so that the reading is not skipped: that is Spec verification's. And every task starts with an estimate of what it should take, the agent's own, or the person's when the agent cannot tell or when they give one. The effort is counted from outside the agent, and far past the estimate it is read as a signal about the design above the task: the one sign the agent cannot patch away. The counting and the pause are the Budget monitor's. The other ways, trusting the checks that pass, waiting for the person to notice, or capping the effort, were turned down.

## Invariants

- The spec is kept sound while the work goes on: every node follows from the node above it, no node contradicts a node above or under it, and each node still fits the work done under it.
- Effort far past its estimate counts as evidence about the design above the task, not only about the code.
- A budget is an estimate, not a limit. Reaching it stops nothing.
- An estimate is stated in what a person can judge: how many runs of the check until the result is solid, and how much code changes. Time is measured, never budgeted.
- Work is counted outside the agent, which cannot change its own numbers. Where an agent gives no place to count from, what it reports is marked as its own.

## Bans
