---
id: objective-review
title: Objective review
kind: component
parent: independent-metrics
version: 2
---

**Motivation.** A task's check is its objective: it is all the agent is held to. When the check leaves out a metric that the goal depends on, the agent can meet the check without the goal, and the result reads as done.

**Challenge.** A missing metric is easiest to see before any work is done, and nobody looks then. But looking too hard is its own failure: any check has corner cases, and a hunt for every one of them turns each task into a defence, costs the person questions, and buys almost nothing.

**Approach.** When a task starts, the agent asks one question of its check: is a metric missing? It adds one only when, in its judgment, that clearly lowers the chance of reward hacking. Corner cases are left alone, and finding nothing to add is the usual answer. A metric the agent adds is marked as its own, and the person can reword or drop it. What was added is kept with the task.

## Invariants

- A task's check is read once, when the task starts, for a missing metric. It is not searched for every way it could be gamed.
- A metric is added only when it clearly lowers the chance of reward hacking. A corner case is not a reason to add one, and adding none is recorded as the answer.
- A metric the agent adds is marked as its own. The work does not wait: the person can reword it or drop it at any time.
- The check as first written is kept.

## Bans
