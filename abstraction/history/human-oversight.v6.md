---
id: human-oversight
title: Human oversight
kind: component
parent: step-back
version: 6
---

**Motivation.** The verdict is the person's, and so is the right to undo. Both have to be real: the agent must not be able to decide for them, or to rewrite what happened.

**Challenge.** Asking for approval at every step stops the work and trains the person to click without reading. Never asking leaves them out of their own system.

**Approach.** Only the verdict on a paused task waits for the person, and it is taken in their own words: a button only starts the sentence. Every other change goes ahead, is recorded where the agent cannot write, and is reported at the end of the turn. A change to the spec can be switched back.

## Invariants

- An agent's change to the spec or to a budget does not wait for approval. It is recorded, and the agent tells the person at the end of the turn what changed and why.
- Every change to the spec can be switched back: the old text of a revised node is kept.
- A session whose person chose not to be asked (bypass permissions) is never asked.
- A button writes nothing. It starts a sentence in the prompt box and the person finishes it.
- The record of tasks, budgets and decisions is append-only, and an agent cannot write to it.

## Bans
