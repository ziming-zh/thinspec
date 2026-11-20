---
id: core
title: ThinSpec
kind: core
parent:
version: 8
---

**Motivation.** Coding agents made code cheap, and they made a wrong abstraction quiet. A person building on a wrong abstraction feels it and pushes back. An agent writes whatever it takes to get by. The person can no longer read what is written, and still answers for whether the system is right.

**Challenge.** A wrong abstraction is now a silent failure. An agent given a task under it makes the task work anyway, patching around it until every check passes. Nothing fails and nothing is reported, and the checks cannot catch it, because the patches were written to pass them.

**Insight.** Treat a wrong abstraction as a silent failure: it will not report itself, so go and look for it. Keep the abstraction written down and thin, so there is something to check against. Check in as the work goes on, and ask the person then for what only they know: read each round of work against the abstraction, watch a sign the agent cannot patch away, and put to the person what the work should take and what to change when the sign appears. And give each piece of work a precise objective, measured from outside the agent: most patching gets through because what is checked is coarse.

## Invariants

- A person can tell whether the work is on track from the spec and the results, without reading code.
- Checks that pass are never taken as evidence that the abstraction is right, or that the goal behind a task was met. A wrong one is looked for while the work goes on.
- What only the person knows is asked of them when it is needed. The system does not wait for them to notice.

## Bans
