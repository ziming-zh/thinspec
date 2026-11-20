"""Repo: the operations shared by the CLI, the MCP server, the hooks and the viewer."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import ThinSpecError, store
from .config import STATE_DIR, find_root, load_config
from .ledger import (DIGEST_CHARS, DIGEST_LINES, DIGEST_SECTIONS, METRICS, OPEN, Ledger, Session, State, Task, _budget,
                     iso, norm_cmd, parse_iso, replay)

UNITS = {"minutes": "min", "trials": "trials", "patches": "patches", "lines": "lines"}
# How a budget is asked for, wherever a person or an agent has to give one.
BUDGET_ASK = "trials (how many runs of the check until the result is solid) and/or lines (how many lines of code change)"

# Where a session's id comes from when the agent puts it in the environment of what it runs.
SESSION_ENV = ("THINSPEC_SESSION", "CLAUDE_CODE_SESSION_ID")
SESSION_WORDS = {"working": "working", "waiting": "waiting for its person", "quiet": "quiet"}


def session_from_env() -> Optional[str]:
    for name in SESSION_ENV:
        if os.environ.get(name):
            return os.environ[name]
    return None


def agent_from_env() -> Optional[str]:
    """The agent that goes with `session_from_env`: named outright, or Claude Code by its own variable."""
    if os.environ.get("THINSPEC_AGENT"):
        return os.environ["THINSPEC_AGENT"]
    if not os.environ.get("THINSPEC_SESSION") and os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "claude-code"
    return None


def this_host() -> str:
    try:
        return socket.gethostname().split(".")[0] or "unknown"
    except OSError:
        return "unknown"


def session_name(sess: Session) -> str:
    """A short name a person can tell sessions apart by: the agent and the start of the id."""
    return "%s %s" % (sess.agent or "session", re.sub(r"[^A-Za-z0-9]", "", sess.id)[:4] or "?")


def kind_mark(node: store.Node) -> str:
    """What follows a component's name where the tree is text: it carries designs out, it is not one."""
    return " (component)" if node.kind == "component" else ""


def fmt_when(ts: float) -> str:
    """A moment in local time: the clock time if it is today, the date as well if not."""
    then = time.localtime(ts)
    same_day = time.strftime("%Y%j", then) == time.strftime("%Y%j")
    return time.strftime("%H:%M" if same_day else "%b %d %H:%M", then)


def fmt_num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else "%.1f" % v


def fmt_budget(budget: Dict[str, float]) -> str:
    parts = ["%s %s" % (fmt_num(budget[m]), UNITS[m]) for m in METRICS if budget.get(m)]
    return ", ".join(parts) or "no budget"


def fmt_usage(task: Task, extra_seconds: float = 0.0) -> str:
    rows = task.usage(extra_seconds)
    if not rows:
        return "no budget"
    return " · ".join(
        "%s/%s %s" % (fmt_num(round(r["actual"], 1)), fmt_num(r["budget"]), UNITS[r["metric"]]) for r in rows
    )


def abstraction_line(size: Dict) -> str:
    """The size of the spec in one line: the largest view against the cap, which is what is capped."""
    if size.get("view"):
        return "Abstraction: %d nodes; largest view '%s', %d/%d lines" % (
            size["nodes"], size["view"], size["view_lines"], size["cap"])
    return "Abstraction: %d nodes, %d/%d lines" % (size["nodes"], size["lines"], size["cap"])


class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.cfg = load_config(self.root)
        self.dir = self.root / STATE_DIR
        self.abs_dir = self.root / self.cfg["abstraction_dir"]
        self.ledger = Ledger(self.dir)
        # The session acting through this Repo, and its agent. It signs what is recorded.
        self.actor: Optional[str] = None
        self.actor_agent: Optional[str] = None
        self._actor_noted = False

    @classmethod
    def find(cls, start=None) -> Optional["Repo"]:
        root = find_root(start or os.getcwd())
        return cls(root) if root else None

    def _sign(self) -> Optional[str]:
        """The acting session's id, once the record knows who that session is."""
        if self.actor and not self._actor_noted:
            self._actor_noted = True
            self.note_session(self.actor, self.actor_agent)
        return self.actor

    def _log(self, ev: dict) -> dict:
        """Append one event, signed by the acting session if there is one."""
        if self._sign() and not ev.get("session"):
            ev = dict(ev, session=self.actor)
        return self.ledger.append(ev)

    # ---- sessions ------------------------------------------------------

    def session_file(self, sid: str) -> Path:
        """The scratch file of a session in this checkout. It is not part of the record."""
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sid or "unknown")[:80]
        return self.dir / "sessions" / ("%s.json" % safe)

    def note_session(self, sid: str, agent: Optional[str] = None) -> None:
        """Put a session in the record, once: its agent, its machine and its checkout."""
        if not sid:
            return

        def build(events):
            if any(e.get("ev") == "session" and e.get("session") == sid for e in events):
                return []
            return [{"ev": "session", "session": sid, "agent": agent or "agent",
                     "host": this_host(), "dir": self.root.name}]

        self.ledger.append_with(build)

    def sessions(self, state: Optional[State] = None, now: Optional[float] = None,
                 me: Optional[str] = None) -> List[dict]:
        """Every session with open work or recent activity: who it is, its task, what it is doing.

        Who worked on what comes from the record. Whether a session is in the middle of a
        turn or waiting for its person is known only for sessions in this checkout, from
        their scratch files. A session elsewhere is working if the record heard from it
        lately, and quiet if not.
        """
        state = self.state() if state is None else state
        now = self.ledger.clock() if now is None else now
        me = self.actor if me is None else me
        quiet_after = float(self.cfg["quiet_after_minutes"]) * 60.0
        rows = []
        for s in state.sessions.values():
            if s.id == "unknown":
                continue  # work the agent did not sign with a session id: nobody to show
            try:
                last = parse_iso(s.last or "")
            except ValueError:
                last = 0.0
            turn = None
            try:
                scratch = json.loads(self.session_file(s.id).read_text(encoding="utf-8"))
                last = max(last, float(scratch.get("last_ts") or 0))
                turn = scratch.get("last_kind")
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            task = state.tasks.get(s.task or "")
            if task is not None and not task.is_open:
                task = None
            if now - last > quiet_after:
                doing = "quiet"
            elif turn in ("stop", "ask"):
                doing = "waiting"
            else:
                doing = "working"
            if task is None and doing == "quiet":
                continue  # nothing open and nothing recent: it is not in the picture
            rows.append({
                "id": s.id, "name": session_name(s), "agent": s.agent, "host": s.host, "dir": s.dir,
                "here": s.host in (None, this_host()), "me": s.id == me,
                "task": task.id if task else None, "state": doing, "last": iso(last), "last_ts": last,
            })
        order = {"working": 0, "waiting": 1, "quiet": 2}
        rows.sort(key=lambda r: (not r["me"], order[r["state"]], -r["last_ts"]))
        return rows

    def holders(self, task_id: str, but: Optional[str] = None, state: Optional[State] = None,
                now: Optional[float] = None) -> List[dict]:
        """The sessions that hold a task: their latest work is on it, and they are not quiet."""
        return [r for r in self.sessions(state, now)
                if r["task"] == task_id and r["state"] != "quiet" and r["id"] != but]

    def session_text(self, row: dict, state: State) -> str:
        """One session in a line: who, where, on which task, how far in, and what it is doing."""
        who = row["name"] + (" (this session)" if row["me"] else "")
        if not row["here"]:
            who += " on %s" % row["host"]
        task = state.tasks.get(row["task"] or "")
        if task is None:
            work = "no task declared"
        else:
            work = "%s \"%s\" under %s, %s%s" % (task.id, task.title, task.parent, fmt_usage(task),
                                                " (paused, waits for a decision)" if task.status == "blocked" else "")
        doing = SESSION_WORDS[row["state"]]
        if row["state"] != "working":
            doing += " since %s" % fmt_when(row["last_ts"])
        return "%s: %s. %s" % (who, work, doing[0].upper() + doing[1:])

    def others_text(self, me: Optional[str], state: Optional[State] = None, now: Optional[float] = None) -> str:
        """What the sessions other than `me` are working on, for an agent about to start work."""
        state = self.state() if state is None else state
        rows = [r for r in self.sessions(state, now, me) if not r["me"] and r["task"]]
        return "\n".join("  " + self.session_text(r, state) for r in rows)

    # ---- reading -------------------------------------------------------

    def nodes(self) -> Dict[str, store.Node]:
        return store.load_nodes(self.abs_dir)

    def state(self) -> State:
        return replay(self.ledger.events())

    def node(self, node_id: str) -> store.Node:
        nodes = self.nodes()
        if node_id not in nodes:
            raise ThinSpecError(
                "No node '%s' in %s/. Nodes: %s."
                % (node_id, self.cfg["abstraction_dir"], ", ".join(nodes) or "(none)")
            )
        return nodes[node_id]

    def task(self, task_id: str) -> Task:
        st = self.state()
        if task_id not in st.tasks:
            raise ThinSpecError("No task '%s'." % task_id)
        return st.tasks[task_id]

    def size(self) -> Dict[str, int]:
        nodes = self.nodes()
        largest = (store.views(nodes) or [{"node": None, "lines": sum(n.lines for n in nodes.values())}])[0]
        return {
            "nodes": len(nodes),
            "lines": sum(n.lines for n in nodes.values()),   # the whole spec: for reading, no longer capped
            "cap": self.cfg.get("max_lines_view") or self.cfg.get("max_lines_total"),
            "view": largest["node"],                          # the largest view, and its lines against the cap
            "view_lines": largest["lines"],
        }

    # ---- tasks ---------------------------------------------------------

    def plan_task(self, parent: str, title: str, check: str, check_cmd: Optional[str] = None,
                  budget: Optional[dict] = None, set_by: str = "user") -> str:
        """Record a leaf task under a design. With a check it is ready to delegate."""
        self.node(parent)
        title = " ".join((title or "").split())
        check = " ".join((check or "").split())
        if not title:
            raise ThinSpecError("A task needs a title.")
        if not check:
            raise ThinSpecError(
                "A task needs a check: the command or measurable criterion that shows it is done. "
                "Without one it cannot be delegated."
            )
        made: List[str] = []
        self._sign()

        def build(events):
            tid = "T%d" % (sum(1 for e in events if e.get("ev") == "task_planned") + 1)
            made.append(tid)
            ev = {"ev": "task_planned", "task": tid, "parent": parent, "title": title, "check": check}
            if check_cmd:
                ev["check_cmd"] = " ".join(check_cmd.split())
            if _budget(budget):
                ev["budget"] = _budget(budget)
                ev["set_by"] = set_by
            if self.actor:
                ev["session"] = self.actor
            return [ev]

        self.ledger.append_with(build)
        return made[0]

    def start_task(self, task_id: Optional[str] = None, parent: Optional[str] = None,
                   title: Optional[str] = None, check: Optional[str] = None,
                   check_cmd: Optional[str] = None, budget: Optional[dict] = None,
                   set_by: str = "agent", guess: bool = False) -> Task:
        """Start a planned task, or plan and start a new one. A budget is mandatory.

        Naming a task that is already open joins it: the acting session works on it
        from here on, next to whoever started it, and its budget stays as it is.
        """
        if task_id and self.actor and self.task(task_id).status in OPEN:
            self._log({"ev": "task_joined", "task": task_id})
            return self.task(task_id)
        if not task_id:
            if not parent:
                raise ThinSpecError("Name the planned task to start, or give parent, title and check for a new one.")
            if not _budget(budget):
                raise ThinSpecError("A task needs a budget before it starts: %s." % BUDGET_ASK)
            task_id = self.plan_task(parent, title or "", check or "", check_cmd)
        task = self.task(task_id)
        if task.status != "planned":
            raise ThinSpecError("Task %s is already %s." % (task_id, task.status))
        new_budget = _budget(budget)
        if not new_budget and not task.budget:
            raise ThinSpecError("Task %s has no budget yet. Give %s." % (task_id, BUDGET_ASK))
        ev = {"ev": "task_started", "task": task_id}
        if new_budget:
            ev["budget"] = new_budget
            ev["set_by"] = set_by
            if guess and set_by == "agent":
                ev["guess"] = True  # the agent could not size this; the person has been asked for their numbers
        self._log(ev)
        return self.task(task_id)

    def set_budget(self, task_id: str, budget: Optional[dict], by: str = "user", note: str = "") -> Task:
        """Replace a task's budget with the person's own numbers. It is theirs from then on, not a guess."""
        task = self.task(task_id)
        new = _budget(budget)
        if not new:
            raise ThinSpecError("Give the budget: %s." % BUDGET_ASK)
        if task.status not in ("planned", "active"):
            raise ThinSpecError(
                "Task %s is %s. A budget is set while a task is planned or active; a paused task is "
                "extended by a decision." % (task_id, task.status)
            )
        self._log({"ev": "budget_set", "task": task_id, "budget": new, "set_by": by, "note": note})
        return self.task(task_id)

    def record_patch(self, task_id: Optional[str], session: Optional[str], file: str, lines: int) -> None:
        self._log({"ev": "patch", "task": task_id, "session": session or self.actor, "file": file, "lines": lines})

    def check_part(self, task: Optional[Task], cmd: str) -> str:
        """The part of a shell line that ran the check, which is all the record keeps of it.

        A line can hold anything else that was typed with the check (a heredoc, a cd, a pipe), and none of
        that is work on the task. The task's own check command, when it has one, is what ran; otherwise the
        piece that matches a trial pattern; otherwise the first line, cut short."""
        whole = norm_cmd(cmd)
        if task is not None and task.check_cmd and norm_cmd(task.check_cmd) in whole:
            return norm_cmd(task.check_cmd)
        for piece in re.split(r"&&|\|\||;|\n|\|", cmd or ""):
            piece = norm_cmd(piece)
            for pattern in self.cfg.get("trial_patterns") or []:
                try:
                    if re.search(pattern, piece):
                        return piece[:200]
                except re.error:
                    continue
        return norm_cmd((cmd or "").split("\n", 1)[0])[:200]

    def record_trial(self, task_id: str, session: Optional[str], cmd: str, passed: Optional[bool]) -> None:
        cmd = self.check_part(self.state().tasks.get(task_id), cmd)
        self._log({"ev": "trial", "task": task_id, "session": session or self.actor, "cmd": cmd, "passed": passed})

    def record_time(self, task_id: str, session: Optional[str], seconds: float) -> None:
        if seconds > 0:
            self._log({"ev": "time", "task": task_id, "session": session or self.actor,
                       "seconds": round(seconds, 1)})

    def report(self, task_id: str, trials: int = 0, patches: int = 0, minutes: float = 0,
               note: str = "", lines: int = 0) -> Task:
        """Self-reported work, for agents that have no hooks counting for them."""
        task = self.task(task_id)
        if not task.is_open:
            raise ThinSpecError("Task %s is %s; only an open task takes reports." % (task_id, task.status))
        if min(trials, patches, minutes, lines) < 0:
            raise ThinSpecError("Reported amounts cannot be negative.")
        self._log(
            {"ev": "report", "task": task_id, "trials": trials, "patches": patches, "lines": lines,
             "minutes": minutes, "note": note}
        )
        task = self.task(task_id)
        line = float(self.cfg["alarm_ratio"])
        if any(r["actual"] > r["budget"] * line for r in task.usage()):
            self.raise_alarm(task_id)
            task = self.task(task_id)
        return task

    def raise_alarm(self, task_id: str, extra_seconds: float = 0.0) -> bool:
        """Pause an active task that went far past its estimate, for a person to decide.

        Returns False if it was not active. The event's "exhausted" field names
        the metrics that are past the alarm line.
        """
        raised: List[bool] = []

        def build(events):
            task = replay(events).tasks.get(task_id)
            if task is None or task.status != "active":
                return []
            raised.append(True)
            return [{
                "ev": "alarm", "task": task_id, "node": task.parent,
                "exhausted": task.past(float(self.cfg["alarm_ratio"]), extra_seconds),
                "usage": [
                    {"metric": r["metric"], "actual": round(r["actual"], 1), "budget": r["budget"]}
                    for r in task.usage(extra_seconds)
                ],
            }]

        self.ledger.append_with(build)
        return bool(raised)

    # ---- objective review: a task's check is read once for a missing metric ----

    def add_metric(self, task_id: str, text: str = "", none: bool = False, note: str = "", by: str = "agent") -> Task:
        """Add a metric to a task's check, or record that none was missing. The check as first written stays.

        A metric the agent adds is marked as its own; nothing waits on the person for it."""
        task = self.task(task_id)
        if not task.is_open and task.status != "planned":
            raise ThinSpecError("Task %s is %s; a metric is added to an open task." % (task_id, task.status))
        text = " ".join((text or "").split())
        if none:
            if text:
                raise ThinSpecError("Either add a metric or record that none is missing, not both.")
            self._log({"ev": "metric_none", "task": task_id, "note": " ".join((note or "").split()), "by": by})
        else:
            if not text:
                raise ThinSpecError("Say the metric: what is measured, on what, and what would not count.")
            self._log({"ev": "metric_added", "task": task_id, "text": text, "note": " ".join((note or "").split()),
                       "by": by})
        return self.task(task_id)

    def set_metric(self, task_id: str, number: int, text: Optional[str] = None, drop: bool = False) -> Task:
        """The person's word on an added metric (numbered from 1): reword it, which makes it theirs, or drop it."""
        task = self.task(task_id)
        if not 1 <= number <= len(task.metrics):
            raise ThinSpecError("Task %s has %d added metrics; give a number from 1." % (task_id, len(task.metrics)))
        ev = {"ev": "metric_set", "task": task_id, "index": number - 1, "by": "user"}
        if drop:
            ev["drop"] = True
        else:
            text = " ".join((text or "").split())
            if not text:
                raise ThinSpecError("Give the metric's new wording, or drop it.")
            ev["text"] = text
        self._log(ev)
        return self.task(task_id)

    # ---- what earlier work proved: its checks are run again before a task closes ----

    def kept_checks(self, task: Task, state: Optional[State] = None) -> List[dict]:
        """The checks earlier work under the task's design passed: each command once, with the task that
        passed it last. A new version keeps what the old one proved, so they are run again before the task
        closes. The task's own check, and checks that are only a criterion with no command, are not here."""
        state = self.state() if state is None else state
        own = norm_cmd(task.check_cmd)
        out: Dict[str, dict] = {}
        for t in state.tasks.values():
            if t.id == task.id or t.parent != task.parent or t.status != "done" or not t.check_cmd:
                continue
            cmd = norm_cmd(t.check_cmd)
            if cmd and cmd != own:
                out[cmd] = {"cmd": cmd, "task": t.id, "title": t.title}
        return list(out.values())

    def owed_checks(self, task: Task, state: Optional[State] = None, dropped=()) -> List[dict]:
        """The kept checks this task has not passed again: never run since it started, or failed last."""
        dropped = {norm_cmd(c) for c in dropped} | set(task.dropped)
        return [k for k in self.kept_checks(task, state)
                if k["cmd"] not in dropped and (task.check_runs.get(k["cmd"]) or {}).get("passed", False) is False]

    def kept_check_matching(self, task: Task, cmd: str, state: Optional[State] = None) -> Optional[str]:
        """The kept check a shell command runs, if it runs one."""
        ran = norm_cmd(cmd)
        for k in self.kept_checks(task, state):
            if k["cmd"] in ran:
                return k["cmd"]
        return None

    def record_check_run(self, task_id: str, session: Optional[str], cmd: str, passed: Optional[bool]) -> None:
        """One run of a check earlier work passed. It is not a trial: it does not count against the budget."""
        self._log({"ev": "check_run", "task": task_id, "session": session or self.actor, "cmd": norm_cmd(cmd)[:300],
                   "passed": passed})

    def run_check(self, task_id: str, cmd: str, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
        """Run a command in the repo and record it, for agents whose runs no hook sees. ThinSpec itself
        observes the exit code, so the run is not the agent's own word."""
        task = self.task(task_id)
        if not task.is_open:
            raise ThinSpecError("Task %s is %s; checks are run for an open task." % (task_id, task.status))
        proc = subprocess.run(cmd, shell=True, cwd=str(self.root), capture_output=True, text=True, timeout=timeout)
        passed = proc.returncode == 0
        kept = self.kept_check_matching(task, cmd)
        if kept:
            self.record_check_run(task_id, None, kept, passed)
        elif task.check_cmd and norm_cmd(task.check_cmd) in norm_cmd(cmd):
            self.record_trial(task_id, None, cmd, passed)
        else:
            raise ThinSpecError("`%s` is neither the check of %s nor a check earlier work under '%s' passed."
                                % (norm_cmd(cmd), task_id, task.parent))
        return proc

    def owed_text(self, task: Task, owed: List[dict]) -> str:
        return (
            "Earlier work under '%s' passed these checks, and a new version keeps what the old one proved. "
            "Run each again before closing %s (the hooks record the run; an agent without hooks runs it through "
            "`thinspec run %s -- <command>`):\n%s\nIf one no longer applies, because the old behaviour it checked "
            "was meant to go, close with it dropped and the reason (task_done's `dropped`)."
            % (task.parent, task.id, task.id,
               "\n".join("  `%s` (passed by %s \"%s\")" % (k["cmd"], k["task"], k["title"]) for k in owed))
        )

    def done_task(self, task_id: str, result: str = "", dropped: Optional[Dict[str, str]] = None) -> Task:
        task = self.task(task_id)
        if not task.is_open:
            raise ThinSpecError("Task %s is %s; only an open task can be closed as done." % (task_id, task.status))
        state = self.state()
        kept = {k["cmd"] for k in self.kept_checks(task, state)}
        drop = {}
        for cmd, why in (dropped or {}).items():
            cmd, why = norm_cmd(cmd), " ".join(str(why or "").split())
            if cmd not in kept:
                raise ThinSpecError("`%s` is not a check earlier work under '%s' passed, so there is nothing to drop."
                                    % (cmd, task.parent))
            if not why:
                raise ThinSpecError("Dropping `%s` needs the reason it no longer applies." % cmd)
            drop[cmd] = why
        owed = self.owed_checks(task, state, drop)
        if owed:
            raise ThinSpecError("%s cannot close yet. %s" % (task_id, self.owed_text(task, owed)))
        ev = {"ev": "task_done", "task": task_id, "result": result}
        if drop:
            ev["dropped"] = drop
        self._log(ev)
        self.round_ended(task_id, "result")
        return self.task(task_id)

    def digest_prompt(self, node_id: str) -> str:
        """What an agent is told about a node's digest when a task under it closes."""
        return ("The person reads the digest of '%s', not its tasks. If this work changed what the node can do, "
                "turned a direction back, or was a run of an experiment with a result, rewrite the section it "
                "touches with node_digest: features, as_built (where what is built departs from the node's story, "
                "and why), reverts, positive, negative. One short line each, in the "
                "person's terms, with no task id, file or count of tests; %d lines a section at most, so merge "
                "and drop. A check that passed is not a result. If nothing a person would decide from changed, "
                "leave it. Then read the node's approach against its digest: until work has shown it the approach "
                "is a plan, and what was turned back leaves the approach (node_revise), so the two never disagree."
                % (node_id, DIGEST_LINES))

    def decide(self, task_id: str, choice: str, note: str = "", extend: Optional[dict] = None,
               ban_text: Optional[str] = None, by: str = "user") -> Task:
        """Record the human's call on a task: extend, step back, ban, or abandon."""
        choice = choice.replace("-", "_")
        task = self.task(task_id)
        if not task.is_open:
            raise ThinSpecError("Task %s is %s; decisions apply to open tasks." % (task_id, task.status))
        ev = {"ev": "decision", "task": task_id, "node": task.parent, "choice": choice, "by": by, "note": note}
        if choice == "extend":
            more = _budget(extend)
            if not more:
                raise ThinSpecError("To extend, say how much more: trials (runs of the check) and/or lines.")
            ev["extend"] = more
            self._log(ev)
        elif choice == "step_back":
            self._log(ev)
            self.revise(task.parent, note or "Stepped back from %s: %s" % (task_id, task.title), task=task_id,
                        decision=True)  # a step back is the person changing the decision
        elif choice == "ban":
            self._log(ev)
            self.add_ban(task.parent, ban_text or task.title, reason=note, task=task_id)
        elif choice == "abandon":
            self._log(ev)
        else:
            raise ThinSpecError("Unknown choice '%s'. Use extend, step_back, ban or abandon." % choice)
        return self.task(task_id)

    # ---- abstraction ---------------------------------------------------

    def add_node(self, node_id: str, title: str, parent: Optional[str], summary: str = "",
                 invariants: Optional[List[str]] = None, kind: Optional[str] = None) -> Path:
        """Add a design (a decision) or, with kind "component", a part of the system that carries designs out."""
        path = store.create_node(self.abs_dir, node_id, title, parent, summary, invariants, kind)
        self._log({"ev": "node_added", "node": node_id, "parent": parent, "title": title,
                   "kind": self.node(node_id).kind})
        return path

    def add_ban(self, node_id: str, text: str, reason: str = "", task: Optional[str] = None) -> None:
        node = self.node(node_id)
        text = " ".join((text or "").split())
        if not text:
            raise ThinSpecError("Say what is banned.")
        line = "%s — %s" % (text, " ".join(reason.split())) if reason.strip() else text
        store.add_ban(node, line)
        self._log({"ev": "ban_added", "node": node_id, "text": text, "reason": reason, "task": task})

    def digest(self, node_id: str, **sections) -> Dict[str, List[str]]:
        """Rewrite sections of a node's digest: the few lines a person reads in place of its tasks.

        A section given replaces what was there. Each holds at most DIGEST_LINES short lines, so
        that adding to a full one means merging or dropping: the cap is what keeps it a digest.
        """
        node = self.node(node_id)
        given: Dict[str, List[str]] = {}
        for name, lines in sections.items():
            if lines is None:
                continue
            if name not in DIGEST_SECTIONS:
                raise ThinSpecError("A digest has these sections: %s." % ", ".join(DIGEST_SECTIONS))
            lines = [" ".join(str(line).split()) for line in lines]
            lines = [line for line in lines if line]
            if len(lines) > DIGEST_LINES:
                raise ThinSpecError(
                    "A digest holds at most %d lines of %s, and %d were given. Merge lines that say one thing, "
                    "and drop what a person no longer needs to decide anything." % (DIGEST_LINES, name, len(lines)))
            long = [line for line in lines if len(line) > DIGEST_CHARS]
            if long:
                raise ThinSpecError("A digest line is one short sentence (%d characters at most): \"%s...\""
                                    % (DIGEST_CHARS, long[0][:60]))
            given[name] = lines
        if not given:
            raise ThinSpecError("Give at least one section to rewrite: %s." % ", ".join(DIGEST_SECTIONS))
        self._log(dict({"ev": "node_digest", "node": node.id}, **given))
        return self.state().digest.get(node.id, {})

    def revise(self, node_id: str, reason: str, task: Optional[str] = None, decision: bool = False) -> int:
        """Keep the node's current text, with the reason, before it is rewritten. Returns its version.

        A version is a decision: the number goes up only when `decision` is set, which is when a
        rule of the node is added, dropped or reversed, or the person stepped back. Anything else
        is a rewording (a clearer sentence, a new name, text moved): the text is kept all the
        same, the nodes next to it are owed a verification all the same, and the number stays.
        """
        node = self.node(node_id)
        if not reason.strip():
            raise ThinSpecError("A revision needs a reason: what did you learn that the old design missed?")
        if decision:
            old, new, _ = store.archive_and_bump(self.abs_dir, node)
            self._log({"ev": "node_revised", "node": node_id, "from": old, "to": new, "reason": reason, "task": task})
            return new
        k, _ = store.archive_edit(self.abs_dir, node)
        self._log({"ev": "node_revised", "node": node_id, "from": node.version, "to": node.version, "edit": k,
                   "reason": reason, "task": task})
        return node.version

    # ---- verification: what happens puts nodes up to be checked ----------

    def round_ended(self, task_id: str, after: str, session: Optional[str] = None) -> Optional[str]:
        """A round of work under a node ended: the node is owed a verification against it.

        `after` is "result" when the task closed with one, "work" when a turn ended having
        changed code or run the check. Returns the node, or None when nothing new is owed:
        the node was verified after the task's latest work, or that work was raised already.
        """
        state = self.state()
        task = state.tasks.get(task_id)
        if task is None or task.parent not in self.nodes():
            return None
        if after != "result":
            worked = state.worked_seq.get(task_id, -1)
            seen = max(state.read_seq.get(task.parent, -1), (state.due.get(task.parent) or {}).get("seq", -1))
            if worked <= seen:
                return None
        self._log({"ev": "verify_due", "node": task.parent, "task": task_id, "after": after,
                   "session": session or self.actor})
        return task.parent

    def next_to(self, node_id: str, nodes: Optional[Dict[str, store.Node]] = None) -> List[str]:
        """The node above a node and the nodes under it: the ones a change to it reaches first."""
        nodes = self.nodes() if nodes is None else nodes
        above = nodes[node_id].parent
        return ([above] if above in nodes else []) + [c.id for c in store.children(nodes, node_id)]

    def verify(self, node_id: str, note: str) -> None:
        """Record that a node was read again after a node next to it changed, and still follows."""
        node = self.node(node_id)
        note = " ".join((note or "").split())
        if not note:
            raise ThinSpecError("Say why '%s' still follows from the nodes next to it as they now read." % node_id)
        self._log({"ev": "node_verified", "node": node.id, "version": node.version, "note": note})

    def to_verify(self, nodes: Optional[Dict[str, store.Node]] = None,
                  state: Optional[State] = None) -> List[dict]:
        """Nodes owed a verification, each with what it is owed against.

        `since`: nodes next to it that were revised after it was last read. `round`: a round of
        work under it that ended after it was last read. Revising a node counts as reading it,
        so a change that is carried on clears one debt and opens the next ones. The spec is
        sound again when this list is empty.
        """
        nodes = self.nodes() if nodes is None else nodes
        state = self.state() if state is None else state
        out: List[dict] = []
        for node, _depth in store.walk(nodes):
            read = state.read_seq.get(node.id, -1)
            since = [m for m in self.next_to(node.id, nodes) if state.revised_seq.get(m, -1) > read]
            row = {"node": node.id, "since": [{"node": m, "version": nodes[m].version} for m in since]}
            due = state.due.get(node.id)
            if due and due["seq"] > read:
                row["round"] = {"task": due["task"], "after": due["after"]}
            gone = state.left.get(node.id)
            if gone and gone["seq"] > read:
                row["left"] = gone["node"]           # a node moved out from under it
            if len(row) > 2 or since:
                out.append(row)
        return out

    def verify_prompt(self, node_id: str, round_: dict) -> str:
        """What an agent is told when a round of work puts a node up to be verified."""
        return (
            "A round of work under '%s' ended: verify the node against %s. Read the node and the rules above it, "
            "and settle which of four holds. It still fits: record why with node_verify. The evidence overturns "
            "it, or something new was learned: revise it with node_revise. It, or a rule in it, holds more "
            "generally than this node: move it up a level (a rule by revising both nodes, the whole node with "
            "node_move). A node you change is carried on to the node above it and the nodes under it."
            % (node_id, self.round_text(round_))
        )

    @staticmethod
    def round_text(round_: dict) -> str:
        return "%s's result" % round_["task"] if round_["after"] == "result" else "the work on %s" % round_["task"]

    def to_verify_text(self, owed: Optional[List[dict]] = None) -> List[str]:
        """One sentence per node owed a verification, saying against what and what to do about it."""
        owed = self.to_verify() if owed is None else owed
        out = []
        for row in owed:
            why = []
            if row["since"]:
                names = ["'%s' (now v%d)" % (s["node"], s["version"]) for s in row["since"]]
                changed = names[0] if len(names) == 1 else "%s and %s" % (", ".join(names[:-1]), names[-1])
                why.append("has not been read again since %s changed" % changed)
            if row.get("round"):
                why.append("has not been checked against %s" % self.round_text(row["round"]))
            if row.get("left"):
                why.append("has not been read again since '%s' moved out from under it" % row["left"])
            out.append("Node '%s' %s. Revise it if it no longer fits, or record why it still does: "
                       "thinspec verify %s --note \"...\"." % (row["node"], " and ".join(why), row["node"]))
        return out

    def rename_node(self, node_id: str, new_id: str) -> Path:
        """Give a node a new id. Its tasks, the nodes under it and its kept versions follow."""
        path = store.rename_node(self.abs_dir, self.node(node_id), new_id)
        self._log({"ev": "node_renamed", "from": node_id, "to": new_id})
        return path

    def move_node(self, node_id: str, under: str, reason: str) -> str:
        """Put a node under another one, as when it holds more generally than where it sat.

        Returns the node it left. The move is a change to the node: the node it left, the one
        it now sits under and the nodes under it are owed a verification.
        """
        node = self.node(node_id)
        reason = " ".join((reason or "").split())
        if not reason:
            raise ThinSpecError("Moving a node needs a reason: what showed that '%s' belongs elsewhere?" % node_id)
        left = node.parent
        store.move_node(self.abs_dir, node, under)
        self._log({"ev": "node_moved", "node": node_id, "from": left, "to": under, "reason": reason})
        return left or ""

    def retire_node(self, node_id: str, reason: str, into: Optional[str] = None) -> Path:
        """Take a node out of the graph. Its text is kept, and its tasks move to `into`."""
        node = self.node(node_id)
        reason = " ".join((reason or "").split())
        if not reason:
            raise ThinSpecError("Retiring a node needs a reason: where did its idea go?")
        if into is not None and (into == node_id or into not in self.nodes()):
            raise ThinSpecError("The tasks of '%s' cannot move to '%s': name another node that exists."
                                % (node_id, into))
        tasks = self.state().tasks_under(node_id)
        if tasks and into is None:
            raise ThinSpecError(
                "Node '%s' has tasks under it (%s). Say which node they move to: --into <node>."
                % (node_id, ", ".join(t.id for t in tasks))
            )
        archived = store.retire_node(self.abs_dir, node)
        self._log({"ev": "node_retired", "node": node_id, "into": into,
                            "version": node.version, "reason": reason})
        return archived

    def restore(self, node_id: str, to: Optional[int] = None, reason: str = ""):
        """Switch a node back to an earlier version's text. Returns (the version restored, the new version).

        It is one more revision in the node's history, never a rewrite of it: the
        text being dropped is archived, and the version number goes up.
        """
        node = self.node(node_id)
        left, restored, new = store.restore(self.abs_dir, node, to)
        why = " ".join((reason or "").split())
        self._log({
            "ev": "node_revised", "node": node_id, "from": left, "to": new, "restored": restored,
            "reason": "Switched back to v%d%s" % (restored, ": %s" % why if why else ""), "task": None,
        })
        return restored, new

    # ---- health --------------------------------------------------------

    def health(self, nodes: Optional[Dict[str, store.Node]] = None,
               state: Optional[State] = None) -> Dict[str, dict]:
        """Per design: is the work under it going as estimated, or is it time to step back?"""
        nodes = self.nodes() if nodes is None else nodes
        state = self.state() if state is None else state
        need = int(self.cfg["stepback_alarms"])
        out: Dict[str, dict] = {}
        for n in nodes.values():
            tasks = state.tasks_under(n.id)
            since = state.revised_at.get(n.id)
            cur = [t for t in tasks if not since or (t.started or t.created or "") >= since]
            hit = [t for t in cur if t.hit_budget]
            waiting = [t for t in cur if t.status == "blocked"]
            near = [t for t in cur if t.status == "active" and t.peak_ratio() >= 1.0]
            started = sorted((t for t in cur if t.status != "planned"), key=lambda t: t.started or "")
            # How many of the most recent tasks were paused, far past their estimate,
            # in a row. A task that finished without a pause ends the run: the design
            # is working again.
            streak = 0
            for t in reversed(started):
                if t.hit_budget:
                    streak += 1
                elif t.status == "done":
                    break
            if streak >= need:
                level = "step_back"
                reason = "the last %d tasks under it went far past their estimates" % streak
            elif streak:
                last = [t for t in started if t.hit_budget][-1]
                level, reason = "watch", "%s went far past its estimate" % last.id
            elif near:
                level, reason = "watch", "%s is past its estimate" % near[0].id
            elif hit:
                level = "ok"
                reason = "%d of %d tasks went far past their estimates since v%d, but the latest finished without a pause" % (
                    len(hit), len(started), n.version)
            elif started:
                level, reason = "ok", "work is within budget"
            else:
                level, reason = "idle", "no work yet under this version"
            out[n.id] = {
                "level": level, "reason": reason,
                "tasks": len(tasks), "current": len(cur), "hit": len(hit),
                "needs_decision": [t.id for t in waiting],
                "done": sum(1 for t in tasks if t.status == "done"),
            }
        # Trouble in several designs is a signal about the design above them.
        depth = {n.id: len(store.chain(nodes, n.id)) for n in nodes.values()}
        for n in sorted(nodes.values(), key=lambda x: -depth[x.id]):
            flagged = [c.id for c in store.children(nodes, n.id) if out[c.id]["level"] == "step_back"]
            if len(flagged) >= need and out[n.id]["level"] != "step_back":
                out[n.id].update(level="step_back",
                                 reason="%d nodes under it are flagged: %s" % (len(flagged), ", ".join(flagged)))
            elif flagged and out[n.id]["level"] in ("ok", "idle"):
                out[n.id].update(level="watch", reason="'%s' under it is flagged" % flagged[0])
            elif out[n.id]["level"] == "idle":
                # A node with no work of its own, such as a design whose work is done by its
                # components, is as well as what is under it.
                kids = [c.id for c in store.children(nodes, n.id)]
                watched = [c for c in kids if out[c]["level"] == "watch"]
                if watched:
                    out[n.id].update(level="watch",
                                     reason="'%s' under it: %s" % (watched[0], out[watched[0]]["reason"]))
                elif any(out[c]["level"] == "ok" for c in kids):
                    out[n.id].update(level="ok", reason="the work under it is within budget")
        return out

    # ---- text for agents and terminals ---------------------------------

    def overview_text(self, me: Optional[str] = None, now: Optional[float] = None, brief: bool = False) -> str:
        """The graph, the open work and the sessions at work. `brief` leaves the invariants out, for
        where room is short: the bans, the open work and the sessions are what cannot be dropped."""
        nodes, state = self.nodes(), self.state()
        health = self.health(nodes, state)
        size = self.size()
        lines = [
            "ThinSpec · %s" % self.root.name,
            abstraction_line(size),
            "",
        ]

        def walk(node: store.Node, depth: int) -> None:
            pad = "  " * depth
            h = health[node.id]
            flag = "" if h["level"] in ("ok", "idle") else "  [%s: %s]" % (h["level"].replace("_", " "), h["reason"])
            lines.append("%s%s  \"%s\"%s  v%d%s" % (pad, node.id, node.title, kind_mark(node), node.version, flag))
            for inv in ([] if brief else node.invariants):
                lines.append("%s  invariant: %s" % (pad, inv))
            for ban in node.bans:
                lines.append("%s  banned: %s" % (pad, ban))
            for child in store.children(nodes, node.id):
                walk(child, depth + 1)

        for root in store.roots(nodes):
            walk(root, 0)
        if not nodes:
            lines.append("(no nodes yet)")
        elif brief:
            lines.append("(The invariants are left out here to keep this short. The overview tool lists every "
                         "one, and task_start returns those that bind a task.)")

        owed = self.to_verify(nodes, state)
        if owed:
            lines += ["", "To verify. Read each node against what it is owed, then revise it (the evidence overturns "
                          "it, or something new was learned), move what belongs higher up a level, or record "
                          "with node_verify why it still fits:"]
            for row in owed:
                why = ["since %s" % ", ".join("%s v%d" % (s["node"], s["version"]) for s in row["since"])
                       ] if row["since"] else []
                if row.get("round"):
                    why.append("against %s" % self.round_text(row["round"]))
                if row.get("left"):
                    why.append("since %s moved out from under it" % row["left"])
                lines.append("  %s  %s" % (row["node"], ", ".join(why)))
        waiting = [t for t in state.tasks.values() if t.status == "blocked"]
        active = [t for t in state.tasks.values() if t.status == "active"]
        planned = [t for t in state.tasks.values() if t.status == "planned"]
        if waiting:
            lines += ["", "Paused, waiting for a human decision (far past the estimate):"]
            lines += ["  %s  under %s  \"%s\"  %s" % (t.id, t.parent, t.title, fmt_usage(t)) for t in waiting]
        if active:
            lines += ["", "Active tasks:"]
            lines += ["  %s  under %s  \"%s\"  %s%s" % (t.id, t.parent, t.title, fmt_usage(t),
                                                      "  (the estimate is the agent's guess)" if t.guess else "")
                      for t in active]
        if planned:
            lines += ["", "Planned, ready to delegate:"]
            lines += [
                "  %s  under %s  \"%s\"  check: %s  (%s)" % (t.id, t.parent, t.title, t.check, fmt_budget(t.budget))
                for t in planned
            ]
        sessions = self.sessions(state, now, me)
        if sessions:
            lines += ["", "Sessions, working in parallel in this project:"]
            lines += ["  " + self.session_text(r, state) for r in sessions]
        if state.untracked_patches:
            lines += ["", "Untracked edits (no task declared): %d" % state.untracked_patches]
        return "\n".join(lines)

    def tree_text(self) -> str:
        """The graph at a glance, for a person at a terminal: one line per design."""
        nodes, state = self.nodes(), self.state()
        health = self.health(nodes, state)
        size = self.size()
        marks = {"planned": "○", "active": "●", "blocked": "⏸", "done": "✓",
                 "banned": "✗", "stepped_back": "↩", "abandoned": "–"}
        words = {"ok": "on budget", "watch": "watch", "step_back": "step back", "idle": "no work yet"}
        rows = []  # (label, version, state, marks)

        def walk(node: store.Node, prefix: str, tail: str) -> None:
            tasks = "".join(marks.get(t.status, "?") for t in state.tasks_under(node.id)[-10:])
            bans = "%d bans" % len(node.bans) if len(node.bans) > 1 else ("1 ban" if node.bans else "")
            rows.append((prefix + tail + node.title + kind_mark(node), "v%d" % node.version,
                         words[health[node.id]["level"]],
                         "  ".join(x for x in (tasks, bans) if x)))
            kids = store.children(nodes, node.id)
            for i, child in enumerate(kids):
                last = i == len(kids) - 1
                walk(child, prefix + ("" if not tail else ("   " if tail == "└─ " else "│  ")),
                     "└─ " if last else "├─ ")

        for root in store.roots(nodes):
            walk(root, "", "")
        width = min(max([len(r[0]) for r in rows] or [0]), 56)
        lines = ["%s · %s" % (self.root.name, abstraction_line(size)[0].lower() + abstraction_line(size)[1:]), ""]
        for label, version, level, extra in rows:
            if len(label) > width:
                label = label[: width - 1] + "…"
            lines.append(("%-*s  %-3s  %-12s %s" % (width, label, version, level, extra)).rstrip())
        if not rows:
            lines.append("(no nodes yet: fill in %s/core.md)" % self.cfg["abstraction_dir"])

        order = {"blocked": 0, "active": 1, "planned": 2}
        open_tasks = sorted((t for t in state.tasks.values() if t.status in order), key=lambda t: order[t.status])
        if open_tasks:
            lines.append("")
        for t in open_tasks:
            if t.status == "planned":
                lines.append("○ %s %s   ready to delegate (%s)" % (t.id, t.title, fmt_budget(t.budget)))
            else:
                lines.append("%s %s %s   %s" % (marks[t.status], t.id, t.title, fmt_usage(t)))
            if t.status == "blocked":
                lines.append("   paused, far past its estimate: thinspec task decide %s extend|step-back|ban" % t.id)
        sessions = self.sessions(state)
        if sessions:
            lines += ["", "Sessions"]
            lines += ["  " + self.session_text(r, state) for r in sessions]
        if state.untracked_patches:
            lines += ["", "%d edits with no task declared" % state.untracked_patches]
        return "\n".join(lines)

    def context_text(self, node_id: str) -> str:
        """Everything an agent must respect when working under a node: the whole chain above it."""
        nodes, state = self.nodes(), self.state()
        if node_id not in nodes:
            raise ThinSpecError("No node '%s'. Nodes: %s." % (node_id, ", ".join(nodes) or "(none)"))
        lines: List[str] = []
        for n in store.chain(nodes, node_id):
            lines.append("%s  \"%s\"%s  v%d" % (n.id, n.title, kind_mark(n), n.version))
            if n.summary:
                lines.append("  %s" % n.summary)
            lines += ["  invariant: %s" % i for i in n.invariants]
            lines += ["  banned (never take this path again): %s" % b for b in n.bans]
        revisions = [e for e in state.timeline if e.get("ev") == "node_revised" and e.get("node") == node_id]
        if revisions:
            lines += ["", "Why '%s' was revised:" % node_id]
            lines += [("  v%s, reworded: %s" % (e.get("to"), e.get("reason", "")) if e.get("edit") else
                       "  v%s -> v%s: %s" % (e.get("from"), e.get("to"), e.get("reason", ""))) for e in revisions]
        kept = state.digest.get(node_id) or {}
        if any(kept.values()):
            lines += ["", "Digest of '%s' (what the person reads in place of its tasks):" % node_id]
            lines += ["  %s: %s" % (name, line) for name in DIGEST_SECTIONS for line in kept.get(name, [])]
        tasks = state.tasks_under(node_id)
        if tasks:
            lines += ["", "Tasks under '%s':" % node_id]
            lines += ["  %s  %s  \"%s\"  %s" % (t.id, t.status, t.title, fmt_usage(t)) for t in tasks[-12:]]
        return "\n".join(lines)

    def task_text(self, task: Task, extra_seconds: float = 0.0) -> str:
        lines = [
            "%s  %s  \"%s\"" % (task.id, task.status, task.title),
            "  under: %s" % task.parent,
            "  check: %s" % task.check,
        ]
        for i, m in enumerate(task.metrics, 1):
            lines.append("  metric %d added: %s%s" % (i, m["text"], " (the agent's own)" if m.get("own") else ""))
        if task.check_cmd:
            lines.append("  check command: %s" % task.check_cmd)
        who = task.set_by or "nobody"
        if task.set_by == "agent" and task.confirmed:
            who = "agent, confirmed by the user"
        elif task.guess:
            who = "agent, as a guess: the user has not given their own numbers"
        lines.append("  budget: %s (set by %s)" % (fmt_budget(task.budget), who))
        lines.append("  used:   %s" % fmt_usage(task, extra_seconds))
        if task.lines:
            lines.append("  edits:  %d lines across %d files" % (task.lines, len(task.files)))
        if task.result:
            lines.append("  result: %s" % task.result)
        for cmd, why in task.dropped.items():
            lines.append("  dropped an earlier check: `%s` — %s" % (cmd, why))
        for d in task.decisions:
            lines.append("  decision: %s — %s" % (d.get("choice"), d.get("note") or ""))
        return "\n".join(lines)
