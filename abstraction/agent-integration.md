---
id: agent-integration
title: Agent integration
kind: component
parent: core
version: 11
---

**Motivation.** The person already works inside a coding agent. A second tool to open and keep in step with it would not be opened.

**Challenge.** Agents differ: one runs hooks and draws panes, another only calls tools. The logic cannot live inside any one of them.

**Approach.** ThinSpec is one command and two folders in the repo, and each agent only plugs into it, at three points: the agent is given the rules, its work is counted, and it shows the person the picture. Those are its three parts: Agent rules, Work counter, Pane.

## Invariants

- ThinSpec never calls a model, and nothing is generated for the person to open: they talk to the agent as usual.
- All logic and all state live in the `thinspec` command and two folders of the repo, `abstraction/` and `.thinspec/`. An agent holds none of it.
- The command has no runtime dependencies and runs on Python 3.9.
- What an agent shows only shows the state: every fact comes from `thinspec state --json`.

## Bans
