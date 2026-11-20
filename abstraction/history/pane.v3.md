---
id: pane
title: Pane
kind: component
parent: agent-integration
version: 3
---

**Motivation.** The person has to see the spec, and where the work under it stands, without leaving the conversation and without a manual.

**Challenge.** The whole system does not fit in one picture, and a picture that needs a key, or lists everything, is not read. A person presses what they see: a box that looks like a design and does nothing when pressed is a broken box. And boxes with nothing joining them are a list, not a tree: what is under what is read off the lines.

**Approach.** One command opens a pane with the tree. Each view shows one level: its story in words, the nodes under it, and for a component its work. The tree is drawn with the app's own boxes and lines, so that it reads as a tree and a node's name is still a button: a press on it zooms in. Open work is named and finished work is counted, and what needs the person is a button.

## Invariants

- The person has one command, `/thinspec`. It opens the pane and nothing else.
- The tree is drawn in boxes the app can press, never as a picture, and the boxes are joined: a spine runs down from the node in view, a branch reaches each node under it, and a node's open work hangs under its box, each task in a box of its own. Components shared by the designs sit apart, their boxes dashed where the surface draws dashes. Every surface draws the same boxes and the same joins, in ink that shows.
- A node's name in its box is a button, and a press zooms into that node. Each view tells one level: at a design its components with their work counted, at a component all of its work by name, grouped by where it stands. The path above the tree leads back.
- The tree is read with no key. Open work is shown by name, with who is on it and how far into the budget. A task's id is only a handle, never the label.
- The pane stays open and follows the work of every session: after each edit or test run, at the end of each turn, and every few seconds. One line above the prompt says who is working on what.
- When something needs the person, the pane shows buttons: Extend, Step back, Ban, or hand a planned task to a subagent.

## Bans
