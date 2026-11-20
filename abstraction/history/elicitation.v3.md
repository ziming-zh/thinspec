---
id: elicitation
title: Step back, don't patch
kind: design
parent: core
version: 3
---

**Motivation.** Once the signal fires, something above the task has to change. More patches would only hide the problem again.

**Challenge.** The agent's reflex is to keep going down. And what the design should have been is not in anything the agent can read: the person knows it, and whether the design is wrong is theirs to decide.

**Approach.** The task is paused and the person is asked: extend it, step back and revise the design, or ban the approach. What they answer is kept, so it is asked once: a revision keeps the old text and the reason, and a banned approach is not taken again. Everything else goes ahead without waiting. The other way, letting the agent retry or work around it, was turned down. How the question reaches the person is Human oversight's.

## Invariants

- A task far past its estimate is not patched further. It goes to a person, who extends it, steps back to revise the design above it, or bans the approach.
- The verdict on a paused task (extend, step back, ban) is a person's. Only their decision reopens or closes it.
- A design changes by revision: the reason is recorded and the old text is kept.
- A banned approach is not taken again under that design, by any agent.
- Nothing else waits for a person: every other change goes ahead, is recorded, and can be switched back.

## Bans
