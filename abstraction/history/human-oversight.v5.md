---
id: human-oversight
title: Human oversight
kind: component
parent: step-back
version: 5
---

How a decision reaches the person, and what does not wait for them: the agent changes, records and reports, the person can switch a change back, and a verdict is taken in the person's own words.

## Invariants

- An agent's change to the spec or to a budget does not wait for approval. It is recorded, and the agent tells the person at the end of the turn what changed and why.
- Every change to the spec can be switched back: the old text of a revised node is kept.
- A session whose person chose not to be asked (bypass permissions) is never asked.
- A button writes nothing. It starts a sentence in the prompt box and the person finishes it.
- The record of tasks, budgets and decisions is append-only, and an agent cannot write to it.

## Bans
