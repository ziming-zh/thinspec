---
id: work-counter
title: Work counter
kind: component
parent: agent-integration
version: 1
---

**Motivation.** An estimate means something only if the effort is measured, and measured honestly.

**Challenge.** The one doing the work would be counting its own work, and not every agent has a place to count from.

**Approach.** Where the agent has hooks, they count from outside it: each edit and each run of the check goes to the task the session holds. Where it has none, the agent reports its own numbers, and the same budgets apply. Counting is never allowed to get in the way of the work.

## Invariants

- An agent with no hooks reports its own work, and the same budgets apply.
- A fault in ThinSpec never breaks the session: it is logged and the work goes on.

## Bans
