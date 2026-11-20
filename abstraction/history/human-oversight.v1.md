---
id: human-oversight
title: Claude Code gate
kind: design
parent: core
version: 1
---

Settings hooks count the work of the agent and pause it when a task goes far past its estimate.

## Invariants

- A hook always exits 0 and prints at most one decision. Errors go to `.thinspec/hook-errors.log`.
- Edits and check runs are counted by hooks, outside the agent.
- Every agent edit under `abstraction/` goes through a permission prompt.
- A budget an agent sets, and a decision it records, go through a permission prompt.

## Bans
