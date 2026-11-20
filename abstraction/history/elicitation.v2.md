---
id: elicitation
title: Step back, don't patch
kind: design
parent: core
version: 2
---

**Motivation.** Once the signal fires, something above the task has to change. More patches would only hide the problem again.

**Challenge.** The agent's reflex is to keep going down, and whether a design is wrong is not the agent's to decide.

**Approach.** The task is paused and the question goes up to a person, who extends it, steps back to revise the design, or bans the approach. A revision keeps the old text and the reason, and a banned approach is not taken again. Everything else goes ahead without waiting. The other way, letting the agent retry or work around it, was turned down. How the verdict reaches the person is Human oversight's.

## Invariants

- A task far past its estimate is not patched further. It goes to a person, who extends it, steps back to revise the design above it, or bans the approach.
- The verdict on a paused task (extend, step back, ban) is a person's. Only their decision reopens or closes it.
- A design changes by revision: the reason is recorded and the old text is kept.
- A banned approach is not taken again under that design, by any agent.
- Nothing else waits for a person: every other change goes ahead, is recorded, and can be switched back.

## Bans
