---
id: human-oversight
title: The person decides
kind: design
parent: core
version: 2
---

Who may change what: the spec, the budgets and the verdict on a design belong to a person, in their own words. The agent proposes, and the record shows what happened.

## Invariants

- A design decision (extend, step back, ban, revise) is recorded only after a person made it.
- Only a decision by a person reopens or closes a paused task.
- Every agent edit to the spec, every budget an agent sets and every decision it records goes to the person for approval.
- A button writes nothing. It starts a sentence in the prompt box and the person finishes it.
- The record of tasks, budgets and decisions is append-only, and an agent cannot write to it.

## Bans
