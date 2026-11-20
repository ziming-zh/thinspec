---
id: agents
title: Agent interface
kind: design
parent: core
version: 1
---

What the agent reads and calls: MCP tools, a skill, and context at session start.

## Invariants

- Every operation an agent needs is an MCP tool. The server is hand-written JSON-RPC with no SDK.
- `context` returns the invariants and bans of a node and of every node above it.
- An agent with no hooks reports its own work through `task_report`, and the same budgets apply.

## Bans
