---
id: objective-review
title: Objective review
kind: component
parent: independent-metrics
version: 1
---

**Motivation.** A task's check is its objective: it is all the agent is held to. If the check can pass without the goal being met, the agent will find that way, and the result will read as done.

**Challenge.** The gaps in a check are easiest to see before any work is done, and nobody looks then: the person wrote the check in a line, and the agent's attention is on the work. A review the agent is left to remember is skipped, and one that only produces a list changes nothing.

**Approach.** When a task starts, the agent reads its check for room to hack: each way it could pass without the goal behind it. For every gap it says how it is closed. The person may tighten the check in their own words; until they do, the agent tightens it itself and that part is marked as its guess. What was found and how it was closed is kept with the task, and a task not yet reviewed is listed until it is.

## Invariants

- A task's check is read for room to hack when the task starts, before work under it is counted as progress.
- Each gap found is recorded with how it is closed: by the person's words, or by the agent's, marked as a guess. Finding none is recorded too.
- The person is asked to specify without the work waiting: the agent's tightening stands until they answer, and theirs replaces it.
- What is owed is counted from the record: a task started and not reviewed is listed in the overview and by `thinspec check`.
- A tightened check replaces the task's check; the earlier wording is kept.

## Bans
