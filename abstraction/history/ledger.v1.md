---
id: ledger
title: Ledger
kind: design
parent: core
version: 1
---

Everything that happens to a task is one line in an append-only log.

## Invariants

- `.thinspec/ledger.jsonl` is the only store of task state. Current state is always recomputed by replaying it.
- Lines are only appended. A damaged line is skipped and never breaks a session.
- An agent cannot write under `.thinspec/`.

## Bans
