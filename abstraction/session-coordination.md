---
id: session-coordination
title: Session coordination
kind: component
parent: core
version: 4
---

**Motivation.** Work goes on in several sessions at once: other windows, other agents, other machines.

**Challenge.** Each session sees only itself. Two of them can take the same work, count against each other's budget or undo each other's edits, and the person cannot see who is doing what.

**Approach.** Every session signs what it records, so the one record says who is on which task. Each agent is told what the others are doing, and the person's picture shows them all. Knowing stops nothing: it is there so that nothing is undone unseen.

## Invariants

- The record says which session started each task and which sessions worked on it. A session appears there by working, known by its agent, its machine and its checkout, with nothing to set up.
- The picture shows every session with open work: its task, the design above it, how far into the budget, and whether it is working, waiting for the person or quiet.
- An agent is told what the other sessions are doing: at the start of a session, in the overview, when it starts a task, and once when it edits a file that another session's open task has edited.
- A session's work is never counted against a task another session holds. To work on that task it joins it, by name.
- None of this stops a session, and the agent it runs in changes nothing: sessions may share a design, a task or a file, and Claude Code, Codex and others appear side by side.
- Each checkout appends only to its own log, so the logs of other worktrees and machines merge without conflict. The record is their merge.

## Bans
