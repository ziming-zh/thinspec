---
id: elicitation
title: Ask the person what only they know, don't guess
kind: design
parent: core
version: 6
order: 3
---

**Motivation.** Some of what the work needs is in the person's head and nowhere else: what a piece of work should take when the agent cannot tell, and what the design should have been once a check says it is wrong. Their attention is the bottleneck, so it is asked for there, and for nothing smaller.

**Challenge.** The agent's reflex is to keep going down: to guess what it does not know and to patch what does not fit, which only hides the problem again. What the design should have been is not in anything the agent can read, and whether the design is wrong is the person's to decide.

**Approach.** The person is asked at the moment it is needed. Where the agent cannot size a piece of work, it asks for their numbers and goes on with its own, marked as a guess, until they answer. Where a task runs far past its estimate, nothing more is patched: the task is paused and the person is asked to extend it, step back and revise the design, or ban the approach. What they answer is kept, so it is asked once: a revision keeps the old text and the reason, and a banned approach is not taken again. Everything else goes ahead without waiting. The other ways, letting the agent guess, retry or work around it, or asking the person to approve every change, were turned down. How a question reaches the person is Human oversight's.

## Invariants

- What only the person knows is asked for, not guessed. What the agent goes on with meanwhile is marked as its guess.
- A task far past its estimate is not patched further. It goes to a person, who extends it, steps back to revise the design above it, or bans the approach.
- The verdict on a paused task (extend, step back, ban) is a person's. Only their decision reopens or closes it.
- A design changes by revision: the reason is recorded and the old text is kept.
- A banned approach is not taken again under that design, by any agent.
- Nothing else waits for a person: every other change goes ahead, is recorded, and can be switched back.

## Bans
