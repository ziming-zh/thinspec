---
id: independent-metrics
title: Give each task a precise objective and measure it from outside the agent
kind: design
parent: core
version: 1
order: 3
---

**Motivation.** Low-level work is handed to an agent whole: a task, such as a round of automatic research, goes out with a goal and comes back with a result. The result is judged by what was measured, so the agent works toward the measure.

**Challenge.** Most reward hacking happens because what is checked is coarse or loose: the agent meets the check without meeting the goal, and nothing fails. Its own account of the result is no check. And the person cannot foresee every gap in an objective at the moment they write it.

**Approach.** A task is dispatched with its objective stated finely and precisely: what is measured, on what, and what would not count. What is measured is observed from outside the agent, which cannot change its own numbers. And before the work starts the objective is read for room to hack: where it could be met without the goal. Room that is found is closed first: the person is asked to specify, or the agent fills it in and marks that as its own. The other way, a loose goal and trust in a check that passes, was turned down.

## Invariants

- A task is dispatched with a precise objective: what is measured, on what, and what would not count as meeting it.
- What is measured is observed outside the agent, which cannot change its own numbers. Where an agent gives no place to observe from, what it reports is marked as its own.
- Before a task starts, its objective is read for room to hack. Room found is closed before the work goes on: the person specifies, or the agent fills it in and marks it as its guess.
- A check that passes is evidence about the objective as stated, never about the goal behind it.

## Bans
