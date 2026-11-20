---
id: elicitation
title: Step back, don't patch
kind: design
parent: core
version: 1
---

What happens once the signal fires: the work stops going down and the question goes up, to a person and to the design. The other choice was to let the agent retry or work around it.

## Invariants

- A task far past its estimate is not patched further. It goes to a person, who extends it, steps back to revise the design above it, or bans the approach.
- The verdict on a paused task (extend, step back, ban) is a person's. Only their decision reopens or closes it.
- A design changes by revision: the reason is recorded and the old text is kept.
- A banned approach is not taken again under that design, by any agent.
- Nothing else waits for a person: every other change goes ahead, is recorded, and can be switched back.

## Bans
