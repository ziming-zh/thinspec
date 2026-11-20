#!/usr/bin/env python3
"""Build a demo repo that replays the design history of a memory-optimisation system.

    python examples/build_demo.py /tmp/thinspec-demo
    thinspec --root /tmp/thinspec-demo view --open

The story follows a real pattern: a first core abstraction (patch user code)
that worked for one case, broke on the next, and was replaced by a
storage-level one; then two instrumentation approaches that were banned
before a third held. The names come from that project; every number in the
ledger is illustrative.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from thinspec.core import Repo  # noqa: E402
from thinspec.install import init  # noqa: E402
from thinspec.ledger import parse_iso  # noqa: E402

CORE_V1 = """---
id: core
title: Local code patch via program analysis
kind: core
parent:
version: 1
---

Find each memory inefficiency in user code and patch it where it occurs.

## Invariants

- Every fix is a local edit at the code site that causes the waste.

## Bans
"""

CORE_V2 = """---
id: core
title: Storage level: approximate the access pattern
kind: core
parent:
version: 2
---

Reason about memory per storage over a whole step, where a global view exists.

## Invariants

- Runtime stages: capture trace, then probe, then apply only if the probe passes.

## Bans
"""


class Clock:
    def __init__(self, start: str):
        self.t = parse_iso(start)

    def __call__(self) -> float:
        return self.t

    def step(self, minutes: float) -> None:
        self.t += minutes * 60


def work(repo: Repo, clock: Clock, task: str, patches: int, trials: int, minutes: float,
         lines: int = 14, files=("src/hooks.py",), passes: bool = False) -> None:
    """Spread patches, trials and time over a stretch of work on one task."""
    steps = max(patches, trials, 1)
    for i in range(steps):
        clock.step(minutes / steps)
        if i < patches:
            repo.record_patch(task, "demo", files[i % len(files)], lines)
        if i >= steps - trials:
            last = i == steps - 1
            repo.record_trial(task, "demo", "pytest tests/", True if (last and passes) else False)
    repo.record_time(task, "demo", minutes * 60)


def build(root: Path) -> Repo:
    root.mkdir(parents=True, exist_ok=True)
    init(root, claude=False)
    repo = Repo(root)
    clock = Clock("2026-04-06T15:00:00Z")
    repo.ledger.clock = clock
    core = repo.abs_dir / "core.md"
    core.write_text(CORE_V1, encoding="utf-8")

    # --- v1: patch the code -------------------------------------------------
    t = repo.start_task(parent="core", title="Lifetime: insert a del at the last use",
                        check="peak memory drops on workload A", budget={"minutes": 120, "trials": 5, "patches": 30},
                        set_by="user").id
    work(repo, clock, t, patches=19, trials=3, minutes=85, files=("src/liveness.py", "src/patch.py"), passes=True)
    repo.done_task(t, "Peak memory down 18% on workload A.")

    clock.step(60 * 20)
    t = repo.start_task(parent="core", title="Offload: patch the call site to move tensors out",
                        check="peak memory drops on workload B", budget={"minutes": 120, "trials": 5, "patches": 30},
                        set_by="user").id
    work(repo, clock, t, patches=27, trials=10, minutes=110, files=("src/offload.py", "src/patch.py"))
    repo.raise_alarm(t)
    clock.step(45)
    repo.decide(t, "step_back",
                note="Offload needs a global view of when memory is used. A local code patch cannot see it.")
    core.write_text(CORE_V2, encoding="utf-8")

    # --- v2: storage level --------------------------------------------------
    clock.step(60 * 24 * 2)
    repo.add_node("detect", "Detect", "core", "Find the storages worth acting on.",
                  ["A candidate storage lies on a memory peak."])
    repo.add_node("instrument", "Instrument", "core", "Where we hook into each step.",
                  ["One unique hook point per step."])
    repo.add_node("offload", "Offload", "core", "Move a storage out and back around the peak.",
                  ["The transfer ends before the peak: end <= t_peak - t_xfer."])

    clock.step(60 * 3)
    t = repo.start_task(parent="detect", title="Shadow replay to find storages on the peak",
                        check="replay reproduces the peak within 2% on workloads A and B",
                        budget={"minutes": 150, "trials": 6, "patches": 40}, set_by="agent").id
    repo.ledger.append({"ev": "budget_confirmed", "task": t})
    work(repo, clock, t, patches=31, trials=4, minutes=118, files=("src/replay.py", "src/trace.py"), passes=True)
    repo.done_task(t, "Replay reproduces the peak within 1.3% on A and 1.8% on B.")

    clock.step(60 * 18)
    t = repo.start_task(parent="instrument", title="Match hook points by stable node names",
                        check="hooks match on a second workload", budget={"minutes": 90, "trials": 4, "patches": 30},
                        set_by="agent").id
    repo.ledger.append({"ev": "budget_confirmed", "task": t})
    work(repo, clock, t, patches=22, trials=8, minutes=74)
    repo.raise_alarm(t)
    clock.step(30)
    repo.decide(t, "ban", ban_text="Stable node names across steps",
                note="names shift with the model, for example when a ViT is added")

    clock.step(60 * 5)
    t = repo.start_task(parent="instrument", title="Steady-state interception at every node",
                        check="overhead under 1% on workload A", budget={"minutes": 90, "trials": 4, "patches": 40},
                        set_by="agent").id
    repo.ledger.append({"ev": "budget_confirmed", "task": t})
    work(repo, clock, t, patches=40, trials=8, minutes=81)
    repo.raise_alarm(t)
    clock.step(20)
    repo.decide(t, "ban", ban_text="Steady-state interception at every node",
                note="steady overhead above 5%, too high for production")

    clock.step(60 * 20)
    t = repo.start_task(parent="instrument", title="Register autograd hooks during forward",
                        check="same coverage as the first version, per-op overhead under 0.5%",
                        budget={"minutes": 60, "trials": 4, "patches": 25}, set_by="agent").id
    repo.ledger.append({"ev": "budget_confirmed", "task": t})
    work(repo, clock, t, patches=18, trials=3, minutes=41, passes=True)
    repo.done_task(t, "Same coverage as the first version. Per-op overhead is constant and under 0.5%.")

    clock.step(60 * 26)
    t = repo.start_task(parent="offload", title="Probe transfer time per storage",
                        check="measured t_xfer within 10% of predicted on workload B",
                        budget={"minutes": 60, "trials": 4, "patches": 20}, set_by="agent").id
    repo.ledger.append({"ev": "budget_confirmed", "task": t})
    work(repo, clock, t, patches=16, trials=8, minutes=57, files=("src/probe.py",))
    repo.raise_alarm(t)

    clock.step(15)
    t = repo.start_task(parent="offload", title="UVM probing for transfer-safe windows",
                        check="no page fault inside a chosen window on workloads A and B",
                        budget={"minutes": 120, "trials": 5, "patches": 30}, set_by="user").id
    work(repo, clock, t, patches=11, trials=4, minutes=52, files=("src/uvm.py", "src/probe.py"))

    repo.plan_task("offload", "Schedule the offload to end before the peak",
                   check="end <= t_peak - t_xfer holds on every step of workloads A and B",
                   budget={"minutes": 90, "trials": 4, "patches": 25}, set_by="user")
    for _ in range(3):
        clock.step(2)
        repo.record_patch(None, "demo", "README.md", 4)
    return repo


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "thinspec-demo")
    if (out / ".thinspec" / "ledger.jsonl").exists() and (out / ".thinspec" / "ledger.jsonl").stat().st_size:
        sys.exit("%s already holds a ledger; pick an empty folder." % out)
    repo = build(out)
    print(repo.overview_text())
    print("\nDemo repo written to %s\nSee it with: thinspec --root %s view --open" % (out, out))
