---
id: core
title: ThinSpec
kind: core
parent:
version: 4
---

**Motivation.** Coding agents made code cheap. A person can no longer read what is written, and still answers for whether the system is right.

**Challenge.** An agent given a task under a wrong design makes it work anyway: it patches around the design until every check passes. Nothing fails, so nobody learns that the design was wrong.

**Insight.** Let the person hold a thin spec above the code, and read the agent's effort as the signal. Work that runs far past its estimate means the spec above it is wrong, and the answer is to step back, not to patch.

## Invariants

- A person can tell whether the work is on track from the spec and the results, without reading code.

## Bans
