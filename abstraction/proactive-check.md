---
id: proactive-check
title: Check in and ask as the work goes, don't wait for a failure
kind: design
parent: core
version: 10
order: 2
---

**Motivation.** A wrong design does not fail, and the person cannot find it by reading: there is too much to read, and their attention is the bottleneck. And what it should have been is in their head and nowhere else. So it has to be looked for while the work goes on, and the person asked at the moment something turns up.

**Challenge.** The one in a place to look is the agent, and it is the one that patches. Its reflex is to keep going down: to guess what it does not know and to patch what does not fit, which hides the problem again. A check it is left to remember is the first thing it skips, and a question it is left to raise is not raised.

**Approach.** Check in at fixed points, not when something breaks. After each round of work the agent reads it against the node it sits under, and what is owed is counted from the record: that is Spec verification's. Every task starts with an estimate of what it should take, and effort far past it is read as a sign about the design: that is the Budget monitor's. When a task closes, the checks that earlier work under the same design passed are run again, so a new version keeps what the old one proved. What a check-in turns up that only the person knows is asked of them then: their numbers where the agent cannot size the work, and their verdict where a task runs far past its estimate. Everything else goes ahead. How a question reaches them is Human oversight's. The other ways, waiting for a failure or for the person to notice, letting the agent guess, or asking approval for every change, were turned down.

## Invariants

- The spec is kept sound while the work goes on: every node follows from the node above it, no node contradicts a node above or under it, and each node still fits the work done under it.
- A budget is an estimate, not a limit, stated in what a person can judge: runs of the check and lines changed. Time is measured, never budgeted.
- Effort far past its estimate counts as evidence about the design above the task. The task is not patched further: it goes to a person, who extends it, steps back to revise the design, or bans the approach.
- What only the person knows is asked for when it is needed, not guessed. What the agent goes on with meanwhile is marked as its guess.
- A task closes only when every check that earlier work under its design passed still passes, or is dropped with the reason it no longer applies. A new version keeps what the old one proved; a difference is explained, never left unexamined.
- The verdict on a paused task is a person's. Nothing else waits for them: every other change goes ahead, is recorded, and can be switched back.
- A node changes by revision: the reason is recorded and the old text is kept. Its version counts decisions: it goes up when a rule is added, dropped or reversed or the person steps back, never for a rewording. A banned approach is not taken again under that design, by any agent.

## Bans
