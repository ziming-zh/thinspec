---
id: human-oversight
title: The person decides
kind: design
parent: core
version: 3
---

Who may change what. The agent does not wait for a person to go on: it changes, records and reports, and the person can switch a change back. Only the verdict on a paused task waits for them.

## Invariants

- An agent's change to the spec or to a budget does not wait for approval. It is recorded, and the agent tells the person at the end of the turn what changed and why.
- Every change to the spec can be switched back: the old text of a revised node is kept.
- A session whose person chose not to be asked (bypass permissions) is never asked.
- The verdict on a paused task (extend, step back, ban) is a person's. Only their decision reopens or closes it.
- A button writes nothing. It starts a sentence in the prompt box and the person finishes it.
- The record of tasks, budgets and decisions is append-only, and an agent cannot write to it.

## Bans
