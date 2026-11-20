---
id: pane
title: Pane
kind: component
parent: agent-integration
version: 1
---

**Motivation.** The person has to see the spec, and where the work under it stands, without leaving the conversation and without a manual.

**Challenge.** The whole system does not fit in one picture, and a picture that needs a key, or lists everything, is not read.

**Approach.** One command opens a pane with the tree. Each view shows one level: its story in words, the nodes under it, and for a component its work. A press on a name zooms in, open work is named and finished work is counted, and what needs the person is a button.

## Invariants

- The person has one command, `/thinspec`. It opens the pane and nothing else.
- The pane is a graph in layers: the core, the designs under it, the components under the node they serve, and under each node its work. Components shared by the designs sit apart. A terminal, which draws no graph, shows the same tree as text.
- A press on a node's name zooms into it, and each view tells one level: at a design its components with their work counted, at a component all of its work by name, grouped by where it stands. The path above the graph leads back.
- The graph is read with no key. Open work is shown by name, with who is on it and how far into the budget. A task's id is only a handle, never the label.
- The pane stays open and follows the work of every session: after each edit or test run, at the end of each turn, and every few seconds. One line above the prompt says who is working on what.
- When something needs the person, the pane shows buttons: Extend, Step back, Ban, or hand a planned task to a subagent.

## Bans
