---
id: agent-integration
title: Inside the agent
kind: design
parent: core
version: 4
---

Where it lives: inside the coding agent the person already uses. The agent reads it, is gated by it and shows it. There is no separate app.

## Invariants

- ThinSpec never calls a model.
- The person talks to the agent as usual. Nothing is generated for them to open.
- The agent gets the graph and the rules that bind a task from tools, a skill and the start of each session. The rules include every invariant and ban above the task.
- An agent with no hooks reports its own work, and the same budgets apply.
- A fault in ThinSpec never breaks the session: it is logged and the work goes on.
- What is drawn only shows the state: every fact comes from `thinspec state --json`.
- The pane is a graph in three layers: the core abstraction on top, the designs under it, and under each design its tasks. Only a surface that cannot draw one, such as a terminal, shows the same tree as text.
- The pane opens once with `/abs`, stays there, and updates itself after each edit or test run, at the end of each turn, and every few seconds while this session is idle, so it follows the other sessions too.
- One line above the prompt shows who is working on what and how far into the budget: this session's task first, then the other sessions' tasks by name.
- When something needs the person, the pane shows buttons: Extend, Step back, Ban, or hand a planned task to a subagent.

## Bans
