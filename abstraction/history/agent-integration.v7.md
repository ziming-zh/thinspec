---
id: agent-integration
title: Agent integration
kind: component
parent: core
version: 7
---

How ThinSpec plugs into the coding agent the person already uses: the agent reads it through tools, is counted and paused by hooks, and shows it in a pane. There is no separate app.

## Invariants

- ThinSpec never calls a model.
- The person talks to the agent as usual. Nothing is generated for them to open.
- The agent gets the graph and the rules that bind a task from tools, a skill and the start of each session. The rules include every invariant and ban above the task.
- An agent with no hooks reports its own work, and the same budgets apply.
- A fault in ThinSpec never breaks the session: it is logged and the work goes on.
- What is drawn only shows the state: every fact comes from `thinspec state --json`.
- The pane is a graph in layers: the core on top, the designs under it, under each design the components that carry it out, and under each node its work. A component shared by the designs sits beside them and is drawn apart from them. Only a surface that cannot draw a graph, such as a terminal, shows the same tree as text.
- The graph is read with no key. Open work is shown by name, with who is on it and how far into the budget. Finished work is a count. A task's id is only a handle, never the label.
- The pane opens once with `/abs`, stays there, and updates itself after each edit or test run, at the end of each turn, and every few seconds while this session is idle, so it follows the other sessions too.
- One line above the prompt shows who is working on what and how far into the budget: this session's task first, then the other sessions' tasks by name.
- When something needs the person, the pane shows buttons: Extend, Step back, Ban, or hand a planned task to a subagent.

## Bans
