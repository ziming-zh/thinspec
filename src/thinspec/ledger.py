"""The ledger: an append-only JSON-lines log, and the task state replayed from it.

Nothing else stores task state. Every budget, patch, trial, alarm and decision
is one line in .thinspec/ledger.jsonl, so the history can be audited and
merged, and the current state is always recomputed from it.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

try:  # POSIX only; on other systems appends are simply unlocked
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

# What a budget is stated in: runs of the check, and lines of code changed. These are
# the two a person can judge. "patches" (file edits) and "minutes" are still counted,
# and budgets recorded in them still hold, but a new budget is not asked for in them.
BUDGETED = ("trials", "lines")
METRICS = BUDGETED + ("patches", "minutes")
OPEN = ("active", "blocked")
CLOSED = ("done", "abandoned", "stepped_back", "banned")


def iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def parse_iso(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


class Ledger:
    def __init__(self, state_dir: Path):
        self.dir = Path(state_dir)
        self.path = self.dir / "ledger.jsonl"
        self.lock_path = self.dir / ".lock"
        self.clock: Callable[[], float] = time.time  # replaceable, for demos and tests

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.dir.mkdir(parents=True, exist_ok=True)
        fh = open(str(self.lock_path), "a+")
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()

    def events(self) -> List[dict]:
        out: List[dict] = []
        try:
            with open(str(self.path), "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue  # a torn or hand-damaged line never breaks a session
                    if isinstance(ev, dict):
                        out.append(ev)
        except OSError:
            pass
        return out

    def _write(self, events: List[dict], ts: Optional[float]) -> List[dict]:
        stamped = []
        for ev in events:
            ev = dict(ev)
            ev.setdefault("ts", iso(self.clock() if ts is None else ts))
            stamped.append(ev)
        if stamped:
            with open(str(self.path), "a", encoding="utf-8") as fh:
                for ev in stamped:
                    fh.write(json.dumps(ev, sort_keys=True, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return stamped

    def append(self, ev: dict, ts: Optional[float] = None) -> dict:
        with self.locked():
            return self._write([ev], ts)[0]

    def append_with(self, fn: Callable[[List[dict]], List[dict]], ts: Optional[float] = None) -> List[dict]:
        """Read the log and append what `fn` returns, as one atomic step."""
        with self.locked():
            return self._write(fn(self.events()), ts)


@dataclass
class Task:
    id: str
    title: str = ""
    parent: str = ""
    check: str = ""
    check_cmd: Optional[str] = None
    status: str = "planned"
    budget: Dict[str, float] = field(default_factory=dict)
    set_by: Optional[str] = None      # "user" | "agent"
    confirmed: bool = False           # a human approved the agent's budget
    guess: bool = False               # the agent could not size the work; the person has not given their numbers
    seconds: float = 0.0
    trials: int = 0
    failed: int = 0
    patches: int = 0
    lines: int = 0
    files: set = field(default_factory=set)
    self_reported: bool = False
    alarms: List[dict] = field(default_factory=list)
    decisions: List[dict] = field(default_factory=list)
    created: Optional[str] = None
    started: Optional[str] = None
    ended: Optional[str] = None
    result: Optional[str] = None
    started_by: Optional[str] = None                        # the session that started it
    sessions: Dict[str, str] = field(default_factory=dict)  # session id -> ts of its latest work here
    edits: Dict[str, dict] = field(default_factory=dict)    # file -> {"session", "ts"} of its latest edit
    # Earlier checks under the same design, run again during this task: command -> its latest run
    # ({"passed", "ts"}), and those it closed without, each with the reason it no longer applies.
    check_runs: Dict[str, dict] = field(default_factory=dict)
    dropped: Dict[str, str] = field(default_factory=dict)
    # Metrics added to the check when the task started: {"text", "own"}, own when the agent added it
    # and the person has not reworded it. `metric_read` is set once the check was read for one.
    metrics: List[dict] = field(default_factory=list)
    metric_read: bool = False

    @property
    def is_open(self) -> bool:
        return self.status in OPEN

    @property
    def full_check(self) -> str:
        """The check as first written, with the metrics added to it since."""
        extra = ["%s%s" % (m["text"], " (the agent's own)" if m.get("own") else "") for m in self.metrics]
        return self.check + ("; also: " + "; ".join(extra) if extra else "")

    def actual(self, extra_seconds: float = 0.0) -> Dict[str, float]:
        return {
            "minutes": (self.seconds + extra_seconds) / 60.0,
            "trials": self.trials,
            "patches": self.patches,
            "lines": self.lines,  # every line an edit touched: reworking a line counts it again
        }

    def usage(self, extra_seconds: float = 0.0) -> List[dict]:
        """One row per budgeted metric: actual, budget and their ratio."""
        actual = self.actual(extra_seconds)
        rows = []
        for m in METRICS:
            b = self.budget.get(m) or 0
            if b > 0:
                rows.append({"metric": m, "actual": actual[m], "budget": b, "ratio": actual[m] / b})
        return rows

    def past(self, ratio: float = 1.0, extra_seconds: float = 0.0) -> List[str]:
        """Metrics at or past `ratio` times their estimate.

        A budget is an estimate: at 1.0 the estimate is reached and nothing stops.
        The configured alarm ratio is the line past which a task goes to a person.
        """
        return [r["metric"] for r in self.usage(extra_seconds) if r["actual"] >= r["budget"] * ratio]

    def peak_ratio(self, extra_seconds: float = 0.0) -> float:
        return max([r["ratio"] for r in self.usage(extra_seconds)] or [0.0])

    @property
    def hit_budget(self) -> bool:
        return bool(self.alarms)


@dataclass
class Session:
    """One agent session, as the record knows it: who it is and what it last worked on."""
    id: str
    agent: Optional[str] = None
    host: Optional[str] = None
    dir: Optional[str] = None     # the checkout it works in
    first: Optional[str] = None   # ts of its first event
    last: Optional[str] = None    # ts of its latest event
    task: Optional[str] = None    # the task of its latest work, open or not


# The events by which a session works on a task. A verdict or a result is not work on it.
WORK_EVENTS = ("task_started", "task_joined", "patch", "trial", "check_run", "time", "report")


@dataclass
class State:
    tasks: Dict[str, Task] = field(default_factory=dict)
    sessions: Dict[str, Session] = field(default_factory=dict)
    untracked_patches: int = 0
    untracked_lines: int = 0
    revised_at: Dict[str, str] = field(default_factory=dict)  # node id -> ts of last revision
    # Where in the record a node last changed, and where it was last read against the nodes
    # next to it: when it was added, revised, or recorded as still following.
    revised_seq: Dict[str, int] = field(default_factory=dict)
    read_seq: Dict[str, int] = field(default_factory=dict)
    # A round of work under a node ended: node id -> {"seq", "task", "after"} of the latest one.
    # `worked_seq` is where each task's latest work is, to tell a new round from one already raised.
    due: Dict[str, dict] = field(default_factory=dict)
    worked_seq: Dict[str, int] = field(default_factory=dict)
    # A node moved out from under this one: node id -> {"seq", "node"} of the latest one to leave.
    left: Dict[str, dict] = field(default_factory=dict)
    # What a person reads under a node in place of its tasks: node id -> section -> a few lines.
    digest: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)
    timeline: List[dict] = field(default_factory=list)        # design-level events

    def open_tasks(self) -> List[Task]:
        return [t for t in self.tasks.values() if t.is_open]

    def tasks_under(self, node_id: str) -> List[Task]:
        return [t for t in self.tasks.values() if t.parent == node_id]


def norm_cmd(cmd) -> str:
    """A command as it is compared: its words, with the spacing between them dropped."""
    return " ".join(str(cmd or "").split())


def _budget(raw) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for m in METRICS:
        try:
            v = float((raw or {}).get(m) or 0)
        except (TypeError, ValueError):
            v = 0
        if v > 0:
            out[m] = int(v) if float(v).is_integer() else v
    return out


# What a node's digest holds: what it can do now, where what is built departs from the node's
# story and why, what was tried and turned back, and what runs of experiments came to, for and
# against. Each a few lines a person reads in place of its tasks.
DIGEST_SECTIONS = ("features", "as_built", "reverts", "positive", "negative")
DIGEST_LINES = 5
DIGEST_CHARS = 160

TIMELINE_EVENTS = (
    "node_added", "node_revised", "node_verified", "node_moved", "node_renamed", "node_retired", "ban_added",
    "abstraction_edited", "alarm", "decision", "task_started", "task_done",
)


def replay(events: List[dict]) -> State:
    st = State()
    for seq, ev in enumerate(events):
        kind = ev.get("ev")
        tid = ev.get("task")
        task = st.tasks.get(tid) if tid else None
        if kind in TIMELINE_EVENTS:
            st.timeline.append(ev)
        sid = ev.get("session")
        if sid:
            ts = ev.get("ts") or ""
            sess = st.sessions.get(sid)
            if sess is None:
                sess = st.sessions[sid] = Session(id=sid, first=ts)
            sess.last = max(sess.last or "", ts)
            if kind == "session":
                for key in ("agent", "host", "dir"):
                    if ev.get(key):
                        setattr(sess, key, ev[key])
            elif task and kind in WORK_EVENTS:
                sess.task = tid
                task.sessions[sid] = ts
        if task and kind in ("patch", "trial", "report"):
            st.worked_seq[tid] = seq
        if kind == "task_planned":
            st.tasks[tid] = Task(
                id=tid, title=ev.get("title", ""), parent=ev.get("parent", ""),
                check=ev.get("check", ""), check_cmd=ev.get("check_cmd"),
                budget=_budget(ev.get("budget")), set_by=ev.get("set_by") if ev.get("budget") else None,
                created=ev.get("ts"),
            )
        elif kind == "task_started" and task:
            task.status = "active"
            task.started = ev.get("ts")
            task.started_by = sid or None
            if ev.get("budget"):
                task.budget = _budget(ev.get("budget"))
                task.set_by = ev.get("set_by")
                task.guess = bool(ev.get("guess"))
        elif kind == "budget_confirmed" and task:
            task.confirmed = True
            task.guess = False
        elif kind == "budget_set" and task:
            # The person's own numbers replace the budget whole: it is theirs now.
            task.budget = _budget(ev.get("budget"))
            task.set_by = ev.get("set_by") or "user"
            task.guess = False
        elif kind == "patch":
            if task:
                task.patches += 1
                task.lines += int(ev.get("lines") or 0)
                if ev.get("file"):
                    task.files.add(ev["file"])
                    task.edits[ev["file"]] = {"session": sid, "ts": ev.get("ts") or ""}
            else:
                st.untracked_patches += 1
                st.untracked_lines += int(ev.get("lines") or 0)
        elif kind == "trial" and task:
            task.trials += 1
            if ev.get("passed") is False:
                task.failed += 1
        elif kind == "time" and task:
            task.seconds += float(ev.get("seconds") or 0)
        elif kind == "report" and task:
            task.self_reported = True
            task.trials += int(ev.get("trials") or 0)
            task.patches += int(ev.get("patches") or 0)
            task.lines += int(ev.get("lines") or 0)
            task.seconds += float(ev.get("minutes") or 0) * 60.0
        elif kind == "alarm" and task:
            task.alarms.append(ev)
            if task.status == "active":
                task.status = "blocked"
        elif kind == "decision" and task:
            task.decisions.append(ev)
            choice = ev.get("choice")
            if choice == "extend":
                for m, v in _budget(ev.get("extend")).items():
                    task.budget[m] = (task.budget.get(m) or 0) + v
                if task.status == "blocked":
                    task.status = "active"
            elif choice in ("step_back", "ban", "abandon"):
                task.status = {"step_back": "stepped_back", "ban": "banned", "abandon": "abandoned"}[choice]
                task.ended = ev.get("ts")
        elif kind == "metric_added" and task and ev.get("text"):
            task.metric_read = True
            task.metrics.append({"text": str(ev["text"]), "own": ev.get("by") != "user"})
        elif kind == "metric_none" and task:
            task.metric_read = True
        elif kind == "metric_set" and task and isinstance(ev.get("index"), int) and 0 <= ev["index"] < len(task.metrics):
            # The person's word on a metric: reworded, it is theirs and no longer marked; dropped, it goes.
            if ev.get("drop"):
                task.metrics.pop(ev["index"])
            else:
                task.metrics[ev["index"]] = {"text": str(ev.get("text") or ""), "own": False}
        elif kind == "check_run" and task and ev.get("cmd"):
            task.check_runs[norm_cmd(ev["cmd"])] = {"passed": ev.get("passed"), "ts": ev.get("ts")}
        elif kind == "task_done" and task:
            task.status = "done"
            task.ended = ev.get("ts")
            task.result = ev.get("result")
            if isinstance(ev.get("dropped"), dict):
                task.dropped = {norm_cmd(k): str(v) for k, v in ev["dropped"].items()}
        elif kind == "node_revised" and ev.get("node"):
            if not ev.get("edit"):  # a rewording decides nothing: the node's health is as it was
                st.revised_at[ev["node"]] = ev.get("ts", "")
            st.revised_seq[ev["node"]] = st.read_seq[ev["node"]] = seq
        elif kind in ("node_added", "node_verified") and ev.get("node"):
            st.read_seq[ev["node"]] = seq
        elif kind == "node_moved" and ev.get("node"):
            # Its place changed, which is a change to it: the nodes now next to it are owed a
            # verification, and so is the node it left, which is no longer next to it.
            st.revised_seq[ev["node"]] = st.read_seq[ev["node"]] = seq
            if ev.get("from"):
                st.left[ev["from"]] = {"seq": seq, "node": ev["node"]}
        elif kind == "verify_due" and ev.get("node"):
            st.due[ev["node"]] = {"seq": seq, "task": tid, "after": ev.get("after") or "work"}
        elif kind == "node_renamed" and ev.get("from") and ev.get("to"):
            # The node is the same one under a new id: its tasks and its past follow it.
            old, new = ev["from"], ev["to"]
            for t in st.tasks.values():
                if t.parent == old:
                    t.parent = new
            for past in st.timeline:
                if past.get("node") == old:
                    past["node"] = new
            for seen in (st.revised_at, st.revised_seq, st.read_seq, st.due, st.left, st.digest):
                if old in seen:
                    seen[new] = seen.pop(old)
        elif kind == "node_digest" and ev.get("node"):
            # A section that is given replaces what was there: a digest is rewritten, not added to.
            kept = st.digest.setdefault(ev["node"], {})
            for section in DIGEST_SECTIONS:
                if isinstance(ev.get(section), list):
                    kept[section] = [str(line) for line in ev[section]]
        elif kind == "node_retired" and ev.get("node") and ev.get("into"):
            # The node is gone and its tasks were handed to another. Its past stays its own.
            for t in st.tasks.values():
                if t.parent == ev["node"]:
                    t.parent = ev["into"]
    return st
