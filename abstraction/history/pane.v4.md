---
id: pane
title: Pane
kind: component
parent: agent-integration
version: 4
---

**Motivation.** The person has to see the spec, and where the work under it stands, without leaving the conversation and without a manual.

**Challenge.** The whole system does not fit in one picture, and a picture that needs a key, or lists everything, is not read. Whatever is added to it is one more thing to read past. And the app gives a press only on its own buttons, never on a picture, while a tree built out of those buttons reads worse than the picture it replaces.

**Approach.** One command opens a pane with the tree. Each view shows one level: the tree as a picture, under it the names of the next level to press, then its story in words. The picture is kept clean: open work is named, finished work is counted, and nothing is drawn that is not there yet. What the person can do is a button, and nothing else is listed.

## Invariants

- The person has one command, `/thinspec`. It opens the pane and nothing else.
- Where the app draws pictures the tree is one picture: the node in view across the top, a spine down from it, a branch to each node under it, and a node's open work hanging under its box. Components shared by the designs sit apart, dashed. A terminal, which draws no picture, draws the same tree in boxes joined by line glyphs.
- A picture takes no press, so under it the nodes of the next level are buttons by name, in a row that says what they are, and a press zooms into that node. In a terminal the name in a node's box is the button. Each view tells one level: at a design its components with their work counted, at a component all of its work by name, grouped by where it stands. The path above the tree leads back.
- The tree is read with no key. Open work is shown by name, with who is on it and how far into the budget. A task's id is only a handle, never the label.
- The pane stays open and follows the work of every session: after each edit or test run, at the end of each turn, and every few seconds. One line above the prompt says who is working on what.
- What the person can do is a button that starts their sentence, and nothing is thought up for them ahead of time: Extend, Step back and Ban on a task far past its estimate; at a node zoomed into, hand a planned task to a subagent; under a design, propose a component. Under the whole tree only what waits for their call is listed.

## Bans
