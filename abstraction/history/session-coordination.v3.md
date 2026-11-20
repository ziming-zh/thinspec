---
id: session-coordination
title: Session coordination
kind: component
parent: core
version: 3
---

Keeps work in parallel one system: every session, in any agent and on any machine, writes to one record, and each of them sees the same picture of who is doing what.

## Invariants

- A session appears in the record by working. It is known by its agent, its machine and its checkout, with nothing to set up.
- The record says which session started each task and which sessions worked on it.
- The picture shows every session with open work: its task, the design above it, how far into the budget, and whether it is working, waiting for the person or quiet.
- An agent is told what the other sessions are doing: at the start of a session, in the overview, and when it starts a task.
- A session's work is never counted against a task another session holds. To work on that task it joins it, by name.
- A session is told once when it edits a file that another session's open task has edited.
- Knowing about each other stops nothing: sessions may share a design, a task or a file.
- The agent a session runs in changes nothing in the record: Claude Code, Codex and others appear side by side.
- Each checkout appends only to its own log, so the logs of other worktrees and machines merge without conflict. The record is their merge.

## Bans
