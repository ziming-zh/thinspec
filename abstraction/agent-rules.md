---
id: agent-rules
title: Agent rules
kind: component
parent: agent-integration
version: 1
---

**Motivation.** An agent starts each session knowing nothing of the design it is about to work under.

**Challenge.** Rules the agent has to go and look for are rules it skips, and rules the person has to paste in are forgotten.

**Approach.** The rules reach the agent without anyone asking: the tree and the working rules at the start of each session, tools that answer what binds a given task, and a skill with the rules in full.

## Invariants

- The agent gets the tree and the rules that bind a task from tools, a skill and the start of each session. They include every invariant and ban above the task.
- The rules are the agent's to load, as a skill of its own name. The person's command, `/thinspec`, does not load them.

## Bans
