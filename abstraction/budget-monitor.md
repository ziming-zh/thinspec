---
id: budget-monitor
title: Budget monitor
kind: component
parent: proactive-check
version: 7
---

**Motivation.** The signal is only as good as the two numbers behind it: what the work was expected to take, and what it took.

**Challenge.** The agent that gives the estimate is the one doing the work, and some work cannot be sized before it starts. And a number that stopped the work the moment it was reached would be padded, or worked around.

**Approach.** Every task carries a check and a budget in what a person can judge. Reaching the budget stops nothing: the agent is told once to look at why. Far past it, the task is paused and goes to a person. An agent that cannot size the work says so, and the person can put their own numbers in.

## Invariants

- A task cannot exist without a check, or start without a budget: runs of the check, lines changed, or both.
- An agent that cannot size the work starts on its own numbers, marks them as a guess, and asks the person for theirs without waiting. A question left unanswered changes nothing: the guess stands.
- The person can replace a budget with their own numbers at any time before the task is paused. It is then theirs, and no longer a guess.
- When a task reaches its estimate, the agent is told once to look at why, and to tell the person if the cause is the design.
- When a budgeted measure goes far past its estimate (twice it by default), the task is paused and goes to a person.
- Paused tasks in a row flag the node they are under, and the design above it. A task that finishes without being paused, or a revision, ends the run.

## Bans
