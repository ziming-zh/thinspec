---
id: core
title: A thin spec above agent-written code
kind: core
parent:
version: 1
---

People maintain a short spec, not the code. Work that runs past its estimate is treated as a signal about the spec, and it goes to a person.

## Invariants

- ThinSpec never calls a model. It lives inside the coding agent the person already uses.
- All logic and all state live in the `thinspec` command and two folders of the repo: `abstraction/` and `.thinspec/`.
- A design decision (extend, step back, ban, revise) is recorded only after a person made it.
- The command has no runtime dependencies and runs on Python 3.9.

## Bans
