---
id: core
title: ThinSpec
kind: core
parent:
version: 3
---

The whole system: a thin spec above agent-written code. People maintain a short spec, not the code. Work that runs far past its estimate is treated as a signal about the spec, and it goes to a person.

## Invariants

- A person can tell whether the work is on track from the spec and the results, without reading code.
- All logic and all state live in the `thinspec` command and two folders of the repo: `abstraction/` and `.thinspec/`.
- The command has no runtime dependencies and runs on Python 3.9.

## Bans
