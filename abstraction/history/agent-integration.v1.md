---
id: agent-integration
title: Views
kind: design
parent: core
version: 1
---

What the person sees inside Claude Code: a pane beside the conversation and one line above the prompt.

## Invariants

- A view only draws. Every fact comes from `thinspec state --json`.
- The person talks to the agent as usual. Nothing is generated for them to open.
- The pane opens once with `/abs`, stays there, and updates itself after each edit or test run and at the end of each turn.
- One line above the prompt shows who is working on what and how far into the budget.
- When something needs the person, the pane shows buttons: Extend, Step back, Ban, or hand a planned task to a subagent.
- A button writes nothing. It starts a sentence in the prompt box and the person finishes it.

## Bans
