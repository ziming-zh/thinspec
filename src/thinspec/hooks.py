"""Claude Code hooks: count the work, ask for budgets, and pause a task that goes far past its estimate.

`thinspec hook` reads one hook event as JSON on stdin and may print one JSON
decision on stdout. It always exits 0: ThinSpec never breaks a session, and
any internal error is written to .thinspec/hook-errors.log instead.

What the hooks do:

  SessionStart   tell the agent how work is tracked here and show the graph
  PreToolUse     edits and check runs: refuse once the task is far past its
                 estimate; nudge when no task is declared; put the verdict on a
                 task to the human, and a change to the abstraction or a budget
                 too where the project asks for approvals
  PostToolUse    count patches and trials, keep time, say when the estimate is
                 reached, and say what went ahead unasked and is owed a report
  Stop           flush the time counted during the turn
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from .core import Repo, fmt_budget, fmt_usage, fmt_when
from .ledger import Task, _budget, parse_iso

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore

EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch")  # apply_patch: Codex
MUTATING_CLI = re.compile(
    r"\bthinspec\s+(task\s+(start|add|decide|budget)|node\s+(add|rename|retire|move)|revise|verify\s+[\w-]+|restore|ban)\b"
)
# A shell command that writes into the state folder: a redirect, or a file-changing verb aimed at it.
TAMPER = re.compile(
    r"(>>?\s*\S*\.thinspec\b|\b(rm|mv|cp|tee|truncate|dd|sed\s+-i\S*)\b[^;&|]*\.thinspec\b)"
)
START_LIMIT = 9000  # characters of context a session start may add
MAX_TOOL_SECONDS = 4 * 3600
FLUSH_SECONDS = 30

PROTOCOL = """This repository uses ThinSpec. The system's design lives in {abs}/ as a small graph of nodes: a core abstraction, the designs under it, and under each design the components that carry it out. Each node has invariants and a ban list. People maintain that graph; agents implement leaf tasks under it. A design is a decision that sets the direction, named by that decision in a plain sentence. A component is a part of the system that carries designs out, named for what it is as a noun phrase. Both would survive a rewrite of the code. Neither is ever a code module: new code is a task under a node that exists.

How work is tracked here:
- Implementation work is declared as a task under a design node with the thinspec tool task_start: the parent node, a title, the check that verifies the work, and a budget. A budget is stated in what a person can judge: trials (how many runs of the check until the result is solid) and lines (how many lines of code change, tests included). Time is measured, never budgeted. The budget is your honest estimate; the user sees it and can change it.
- When you cannot size the work with confidence (debugging a kernel or a training run, tuning, flaky behaviour, code you have not read), start with your best numbers and confidence "low", and ask the user in your message for theirs: about how many runs until the result is solid, and about how much code they expect to change. Do not wait for the answer. If they give numbers, record them with task_budget; if they do not, yours stand.
- The lines your edits change and the runs of the check are counted automatically against the active task.
- A budget is an estimate, not a limit. Reaching it stops nothing: you are told once, and you look at why the work is taking more than expected.
- When a task goes far past its estimate, edits and check runs for that task pause. This is treated as evidence about the design above the task, and the user chooses: extend the budget, step back and revise the design, or ban the approach.
- Bans on a node apply to everything under it and are not retried.
- A change to {abs}/ or to a budget does not wait for the user's approval. Go on, and when the turn ends tell them every such change you made: what changed and why. To change a node, call node_revise first: the earlier text is kept, so they can switch back. A version is a decision: its number goes up only when you pass decision=true, which is when a rule is added, dropped or reversed or the user stepped back. A rewording, a rename or moved text takes no new number.
- The spec is verified as the work goes on. When a round of work under a node ends (a task closes with a result, or your turn ends having changed code or run the check), that node is owed a verification: read it against the result or the change and settle which holds. It still fits: record why with node_verify. The evidence overturns it, or something new was learned: revise it. It, or a rule in it, holds more generally: move it up a level.
- A revision is not finished at the node revised: the node above it and the nodes under it are owed a verification against the new text, and a node you revise is carried on the same way. The overview lists every node still to verify; the spec is sound when it lists none.
- The verdict on a paused task is the user's alone: never extend, step back or ban on your own.
- Other sessions may be working in this project at the same time, in this agent or another. The state below and the overview tool list them with their tasks. A task another session holds is not yours: declare your own, or, to continue that very work, join it by name (task_start with its id). You are told when you edit a file another session's open task has edited; read their change first.
- The thinspec tools overview and context return the current graph and the rules for a node. The thinspec-rules skill has the full protocol.

Current state:
"""


# ---- session file ------------------------------------------------------

@contextmanager
def _session(repo: Repo, sid: str) -> Iterator[dict]:
    """Load, lock and save the small per-session scratch file."""
    path = repo.session_file(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = open(str(path) + ".lock", "a+")
    try:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            sess = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            sess = {}
        yield sess
        path.write_text(json.dumps(sess), encoding="utf-8")
    finally:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _flush(repo: Repo, sid: str, sess: dict) -> None:
    if sess.get("pending_task") and sess.get("pending", 0) > 0:
        repo.record_time(sess["pending_task"], sid, sess["pending"])
    sess["pending"] = 0.0


def _current(repo: Repo, sid: str, sess: dict, now: float) -> Optional[Task]:
    """The task this session is working on: its own, or the only open one if no other session holds it."""
    state = repo.state()
    tid = sess.get("task")
    if tid and tid in state.tasks and state.tasks[tid].is_open:
        return state.tasks[tid]
    sess.pop("task", None)
    open_tasks = state.open_tasks()
    if len(open_tasks) != 1 or repo.holders(open_tasks[0].id, but=sid, state=state, now=now):
        return None  # another session's task is joined by name, never picked up by default
    return open_tasks[0]


def _known(repo: Repo, sid: str, sess: dict, agent: str) -> None:
    """Put the session in the record the first time it is seen working."""
    if sid != "unknown" and not sess.get("known"):
        repo.note_session(sid, agent)
        sess["known"] = True


def _tick(repo: Repo, sid: str, sess: dict, kind: str, task: Optional[Task], now: float) -> None:
    """Add the time since the last event to the current task.

    A tool's own run time counts in full. Other gaps count up to the idle cap,
    and the wait between turns does not count at all.
    """
    tid = task.id if task else None
    if sess.get("pending_task") != tid:
        _flush(repo, sid, sess)
        sess["pending_task"] = tid
    last, last_kind = sess.get("last_ts"), sess.get("last_kind")
    if tid and last is not None and last_kind != "stop":
        delta = now - float(last)
        if delta > 0:
            if last_kind == "pre" and kind == "post":
                sess["pending"] = sess.get("pending", 0.0) + min(delta, MAX_TOOL_SECONDS)
            else:
                sess["pending"] = sess.get("pending", 0.0) + min(delta, float(repo.cfg["idle_cap_seconds"]))
    sess["last_ts"], sess["last_kind"] = now, kind
    if kind == "stop" or sess.get("pending", 0.0) >= FLUSH_SECONDS:
        _flush(repo, sid, sess)


# ---- output shapes -----------------------------------------------------

def _permission(decision: str, reason: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }}


def _context(event: str, text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


# ---- messages ----------------------------------------------------------

def _stop_text(repo: Repo, task: Task, pending: float) -> str:
    nodes = repo.nodes()
    parent = nodes.get(task.parent)
    design = "'%s'" % (parent.title if parent else task.parent)
    invariants = ("; ".join(parent.invariants) if parent and parent.invariants else "none stated")
    return (
        "ThinSpec: task %s \"%s\" is far past its estimate (%s; the line is %g times the estimate). Edits "
        "and check runs for this task are paused until the user decides. Going this far past an estimate is "
        "treated here as a signal about the design above the task, %s (invariants: %s), and not only about "
        "the code. What the user needs now is a short report: what was tried, what keeps failing, and "
        "whether the failures point at that design. They then choose one of: extend the budget, step back "
        "and revise %s, or ban this approach. The thinspec tool task_decide records their choice, and "
        "only theirs. If the check already passes, task_done closes the task."
        % (task.id, task.title, fmt_usage(task, pending), float(repo.cfg["alarm_ratio"]), design, invariants,
           design)
    )


def _nudge_text(repo: Repo, sid: str, now: float) -> str:
    others = repo.others_text(sid, now=now)
    held = (
        "\nOther sessions are at work in this project:\n%s\nTheir tasks are theirs. If this session is "
        "continuing one of them, join it by name with task_start (task: its id); otherwise declare its own."
        % others if others else ""
    )
    return _NUDGE % repo.cfg["abstraction_dir"] + held


_NUDGE = (
    "ThinSpec: no task is active in this session, so this edit has no budget to count against. "
    "Work that implements part of a design in %s/ is declared first with the thinspec tool task_start: "
    "the parent node (the overview tool lists them), a title, the check that verifies the work, and an "
    "estimated budget in trials (runs of the check until the result is solid) and lines (of code changed). The user sees "
    "the budget and can change it. A trivial change that belongs to no design can simply be retried: it will be "
    "logged as untracked."
)


def _threshold_note(repo: Repo, sess: dict, task_id: str) -> Optional[str]:
    """A one-time note per metric when a task reaches its estimate. It stops nothing."""
    task = repo.state().tasks.get(task_id)
    if task is None or task.status != "active":
        return None
    pending = sess.get("pending", 0.0) if sess.get("pending_task") == task_id else 0.0
    told = sess.setdefault("told", {}).setdefault(task_id, {})
    notes = []
    for r in task.usage(pending):
        mark = "at:%s" % r["budget"]             # an extended budget is a new estimate to reach
        if r["actual"] < r["budget"] or told.get(r["metric"]) == mark:
            continue
        told[r["metric"]] = mark
        notes.append(
            "ThinSpec: task %s has reached its %s estimate (%s). This stops nothing: an estimate is not a "
            "limit. Look now at why the work is taking more than expected. If the cause is the design '%s' "
            "(a case it did not anticipate, an invariant that does not hold), tell the user before going on. "
            "If it is ordinary work, carry on. At %g times the estimate the task is paused and the user decides."
            % (task.id, r["metric"], fmt_usage(task, pending), task.parent, float(repo.cfg["alarm_ratio"]))
        )
    return "\n".join(notes) or None


# ---- helpers -----------------------------------------------------------

def _rel(repo: Repo, file_path: str) -> Optional[str]:
    """Path relative to the repo root, or None when the file is outside it."""
    if not file_path:
        return None
    try:
        p = Path(file_path)
        if not p.is_absolute():
            p = repo.root / p
        return p.resolve().relative_to(repo.root.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _zone(repo: Repo, rel: Optional[str]) -> str:
    if rel is None:
        return "outside"
    if rel == ".thinspec" or rel.startswith(".thinspec/"):
        return "state"
    abs_dir = repo.cfg["abstraction_dir"].strip("/")
    if rel == abs_dir or rel.startswith(abs_dir + "/"):
        return "abstraction"
    return "code"


def _edit_path(tool_input: dict) -> str:
    return str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")


def _edit_lines(tool: str, tool_input: dict) -> int:
    def count(s) -> int:
        return len(str(s).splitlines()) if s else 0

    if tool == "Write":
        return count(tool_input.get("content"))
    if tool == "MultiEdit":
        return sum(max(count(e.get("old_string")), count(e.get("new_string")))
                   for e in tool_input.get("edits") or [] if isinstance(e, dict))
    if tool == "NotebookEdit":
        return count(tool_input.get("new_source"))
    return max(count(tool_input.get("old_string")), count(tool_input.get("new_string")))


PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$")


def _patch_edits(patch: str) -> list:
    """The files a Codex patch touches, each with the lines it changes: per file the larger of the lines
    it removes and the lines it adds, as an edit of old text into new text is counted."""
    out, cur = [], None
    for line in (patch or "").splitlines():
        m = PATCH_FILE.match(line)
        if m:
            cur = [m.group(2), 0, 0]
            out.append(cur)
        elif line.startswith("*** Move to: ") and cur is not None:
            cur[0] = line[len("*** Move to: "):].strip()
        elif cur is not None and line.startswith("+"):
            cur[1] += 1
        elif cur is not None and line.startswith("-"):
            cur[2] += 1
    return [(path, max(add, rem)) for path, add, rem in out]


def _edits(tool: str, tool_input: dict) -> list:
    """(path, lines changed) for each file an edit touches: one for Claude Code's edit tools, one per file
    of a Codex patch."""
    if tool == "apply_patch":
        cmd = tool_input.get("command") or tool_input.get("input") or tool_input.get("patch") or ""
        if isinstance(cmd, list):
            cmd = next((c for c in cmd if isinstance(c, str) and "*** Begin Patch" in c), "")
        return _patch_edits(str(cmd))
    return [(_edit_path(tool_input), _edit_lines(tool, tool_input))]


def _command(tool_input: dict) -> str:
    """The shell command of a Bash call. Codex may give it as a list of words."""
    cmd = tool_input.get("command") or ""
    return " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)


def _exit_failed(response) -> bool:
    """A shell call reported a non-zero exit in its response (Codex reports Bash failures this way)."""
    if isinstance(response, dict):
        for key in ("exit_code", "exitCode", "returncode"):
            if isinstance(response.get(key), int):
                return response[key] != 0
    return False


def is_trial(cmd: str, task: Task, cfg: dict) -> bool:
    """Is this Bash command one run of the task's check?"""
    norm = " ".join((cmd or "").split())
    if not norm:
        return False
    if task.check_cmd:
        return " ".join(task.check_cmd.split()) in norm
    for pattern in cfg.get("trial_patterns") or []:
        try:
            if re.search(pattern, norm):
                return True
        except re.error:
            continue
    return False


def _thinspec_tool(tool: str) -> Optional[str]:
    """'task_start' for mcp__thinspec__task_start (and plugin-prefixed variants)."""
    parts = tool.split("__")
    if len(parts) >= 3 and parts[0] == "mcp" and "thinspec" in parts[1]:
        return parts[-1]
    return None


def _budget_stop(repo: Repo, task: Task, pending: float) -> Optional[str]:
    """The refusal for a task that is paused, or far enough past its estimate to be paused now."""
    if task.status == "blocked":
        return _stop_text(repo, task, pending)
    if task.past(float(repo.cfg["alarm_ratio"]), pending):
        repo.raise_alarm(task.id, pending)
        return _stop_text(repo, task, pending)
    return None


# ---- event handlers ----------------------------------------------------

def _should_ask(cfg: dict, mode: str, kind: str, agent: str = "claude-code") -> bool:
    """Does this go to the person before it happens?

    Never in a session the person set to bypass permissions: they said not to
    be asked. Otherwise the verdict on a task always does, and a change to the
    spec or to a budget does only where the project asks for approvals.
    """
    if mode == "bypassPermissions" or agent == "codex":
        return False  # Codex's hooks can deny or allow a call, not hold it for the person
    return kind == "verdict" or cfg.get("approvals", "ask") == "ask"


def _pre(repo: Repo, sid: str, payload: dict, now: float, agent: str) -> Optional[dict]:
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    cfg = repo.cfg
    mode = str(payload.get("permission_mode") or "")
    with _session(repo, sid) as sess:
        _known(repo, sid, sess, agent)
        task = _current(repo, sid, sess, now)
        _tick(repo, sid, sess, "pre", task, now)
        pending = sess.get("pending", 0.0)

        def ask(reason: str, what: str, kind: str = "change") -> Optional[dict]:
            """Put it to the person first, or let it go on and have them told at the end of the turn."""
            if not _should_ask(cfg, mode, kind, agent):
                sess.setdefault("unasked", []).append(what)
                return None
            sess["last_kind"] = "ask"  # the wait for the human is not agent work
            return _permission("ask", reason)

        name = _thinspec_tool(tool)
        if name == "task_start":
            if not cfg["confirm_budget"]:
                return None
            budget = _budget(ti)
            planned = repo.state().tasks.get(str(ti.get("task") or ""))
            if planned and planned.is_open:
                return None  # joining a task another session started sets no budget
            if planned and not budget and planned.set_by == "user":
                return None  # the human already set this budget when planning
            title = ti.get("title") or (planned.title if planned else "?")
            parent = ti.get("parent") or (planned.parent if planned else "?")
            check = ti.get("check") or (planned.check if planned else "?")
            shown = fmt_budget(budget or (planned.budget if planned else {}))
            out = ask(
                "ThinSpec budget check. Task \"%s\" under design '%s'. Budget: %s. Check: %s. "
                "Approve to start with this budget, or reject and tell Claude the budget you expect."
                % (title, parent, shown, check),
                "set the budget of task \"%s\" under '%s' to %s" % (title, parent, shown),
            )
            sess["asked_start"] = out is not None   # only an answer from the person confirms a budget
            return out
        if name in ("task_decide", "task_budget", "ban_add", "node_revise", "node_verify", "node_move",
                    "node_restore", "node_add"):
            detail = ", ".join("%s=%s" % (k, v) for k, v in ti.items() if v not in (None, "", 0))
            return ask("ThinSpec: this records a decision that is yours to make (%s: %s)." % (name, detail[:400]),
                       "recorded %s (%s)" % (name, detail[:200]),
                       "verdict" if name == "task_decide" else "change")
        if name:
            return None

        if tool == "Bash":
            cmd = _command(ti)
            if TAMPER.search(cmd):
                return _permission(
                    "deny",
                    "ThinSpec: files under .thinspec/ are an append-only record written by the thinspec "
                    "tools. They are not edited by hand or by shell commands.",
                )
            if MUTATING_CLI.search(cmd):
                return ask("ThinSpec: this command sets a budget or records a design decision. "
                           "Approve only if it is your call.",
                           "ran `%s`" % " ".join(cmd.split())[:200],
                           "verdict" if re.search(r"\bthinspec\s+task\s+decide\b", cmd) else "change")
            if task and is_trial(cmd, task, cfg):
                stop = _budget_stop(repo, task, pending)
                if stop:
                    return _permission("deny", stop)
            return None

        if tool in EDIT_TOOLS:
            zones = {}
            for path, _lines in _edits(tool, ti):
                rel = _rel(repo, path)
                zones.setdefault(_zone(repo, rel), rel)
            if "state" in zones:
                return _permission(
                    "deny",
                    "ThinSpec: files under .thinspec/ are an append-only record written by the thinspec "
                    "tools. They are not edited directly.",
                )
            if "abstraction" in zones and cfg["protect_abstraction"]:
                out = ask(
                    "ThinSpec: this changes the abstraction (%s). Read the diff and approve only if it "
                    "matches what you believe the design is." % zones["abstraction"],
                    "changed %s" % zones["abstraction"],
                )
                if out or "code" not in zones:
                    return out
            if "code" not in zones:
                return None
            if task is None:
                if cfg["gate"] == "strict" or (cfg["gate"] == "nudge" and not sess.get("nudged")):
                    sess["nudged"] = True
                    return _permission("deny", _nudge_text(repo, sid, now))
                return None
            stop = _budget_stop(repo, task, pending)
            if stop:
                return _permission("deny", stop)
        return None


def _post(repo: Repo, sid: str, payload: dict, now: float, failed: bool, agent: str) -> Optional[dict]:
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") or {}
    event = str(payload.get("hook_event_name") or "PostToolUse")
    with _session(repo, sid) as sess:
        _known(repo, sid, sess, agent)
        task = _current(repo, sid, sess, now)
        _tick(repo, sid, sess, "post", task, now)
        shared = None

        name = _thinspec_tool(tool)
        if name:
            if failed:
                return None
            if name == "task_start":
                state = repo.state()
                tid = str(ti.get("task") or "")
                if tid not in state.tasks:
                    title = " ".join(str(ti.get("title") or "").split())
                    matches = [t for t in state.tasks.values()
                               if t.status == "active" and t.title == title and t.parent == ti.get("parent")]
                    tid = matches[-1].id if matches else ""
                if tid and state.tasks[tid].is_open:
                    _flush(repo, sid, sess)
                    sess["task"] = tid
                    sess["pending_task"] = tid
                    if sess.pop("asked_start", None):
                        repo.ledger.append({"ev": "budget_confirmed", "task": tid, "session": sid})
            elif name in ("task_done", "task_decide", "task_budget"):
                _flush(repo, sid, sess)
                tid = str(ti.get("task") or "")
                sess.get("told", {}).pop(tid, None)  # an extended budget warns afresh
                if tid in repo.state().tasks and not repo.state().tasks[tid].is_open:
                    if sess.get("task") == tid:
                        sess.pop("task", None)
            note = _unasked_note(repo, sess)
            return _context(event, note) if note else None

        if tool == "Bash":
            cmd = _command(ti)
            failed = failed or _exit_failed(payload.get("tool_response"))
            if task and is_trial(cmd, task, repo.cfg):
                repo.record_trial(task.id, sid, cmd, False if failed else None)
                _worked(sess, task.id)
            kept = repo.kept_check_matching(task, cmd) if task else None
            if kept:
                # A check earlier work under the design passed, run again: not a trial of this task.
                repo.record_check_run(task.id, sid, kept, False if failed else True)
        elif tool in EDIT_TOOLS and not failed and not _exit_failed(payload.get("tool_response")):
            for path, lines in _edits(tool, ti):
                rel = _rel(repo, path)
                zone = _zone(repo, rel)
                if zone == "abstraction":
                    repo.ledger.append({"ev": "abstraction_edited", "file": rel,
                                        "node": Path(rel).stem, "session": sid})
                elif zone == "code":
                    repo.record_patch(task.id if task else None, sid, rel, lines)
                    shared = _shared_file_note(repo, sid, sess, rel, task, now) or shared
                    if task:
                        _worked(sess, task.id)
        # Time passes on any tool, so the estimate is checked after every one.
        notes = [None if failed else _unasked_note(repo, sess),
                 _threshold_note(repo, sess, task.id) if task else None, shared, _verify_note(repo, sess)]
        text = "\n".join(n for n in notes if n)
        return _context(event, text) if text else None


def _shared_file_note(repo: Repo, sid: str, sess: dict, rel: str, task: Optional[Task],
                      now: float) -> Optional[str]:
    """Once per file and task: this edit is to a file another session's open task has edited."""
    state = repo.state()
    names = {r["id"]: r["name"] + ("" if r["here"] else " on %s" % r["host"])
             for r in repo.sessions(state, now)}
    told = sess.setdefault("shared", [])
    notes = []
    for other in state.open_tasks():
        last = other.edits.get(rel)
        mark = "%s:%s" % (other.id, rel)
        if (task is not None and other.id == task.id) or not last or mark in told:
            continue
        if last.get("session") in (None, sid, "unknown") or last["session"] not in names:
            continue  # its own earlier edit, or one by a session that has since gone quiet
        told.append(mark)
        notes.append(
            "ThinSpec: %s was also edited under %s \"%s\" (design '%s') by another session, %s, last at %s. "
            "This stops nothing. Read what that session changed in the file before going on, keep both "
            "tasks' changes working, and tell the user if the two tasks pull this file in different directions."
            % (rel, other.id, other.title, other.parent, names[last["session"]],
               fmt_when(parse_iso(last["ts"])) if last.get("ts") else "an unknown time")
        )
    return "\n".join(notes) or None


def _worked(sess: dict, task_id: str) -> None:
    """This turn is a round of work under the task's node. A turn may work under several tasks."""
    seen = sess.get("worked") or []
    seen = [seen] if isinstance(seen, str) else seen     # a session file written before there could be several
    if task_id not in seen:
        sess["worked"] = seen + [task_id]


def _verify_note(repo: Repo, sess: dict) -> Optional[str]:
    """Once: the turn before this one ended a round of work, and its nodes are still owed a verification."""
    nodes = sess.pop("verify", None)
    if not nodes:
        return None
    nodes = [nodes] if isinstance(nodes, str) else nodes
    owed = [row for row in repo.to_verify() if row["node"] in nodes and row.get("round")]
    return "\n".join("ThinSpec: " + repo.verify_prompt(row["node"], row["round"]) for row in owed) or None


def _unasked_note(repo: Repo, sess: dict) -> Optional[str]:
    """Once a turn: what went ahead without asking, which the agent owes the person a report of."""
    done = sess.get("unasked") or []
    if not done or sess.get("unasked_told"):
        return None
    sess["unasked_told"] = True
    return (
        "ThinSpec: this went ahead without asking the person first (%s). Nothing here waits for an "
        "approval. In return, when this turn ends, tell them every change of this kind you made in it, "
        "to the spec, to a budget or to the record: what changed and why. The earlier text of a revised "
        "node is kept in %s/history/, so they can switch a change back (`thinspec restore <node>`, or "
        "the node_restore tool when they ask you to)."
        % (done[-1], repo.cfg["abstraction_dir"])
    )


def handle(payload: dict, now: Optional[float] = None, agent: str = "claude-code") -> Optional[dict]:
    """Process one hook event. Returns the JSON to print, or None for no decision.

    `agent` names the coding agent whose hooks these are; it is how the session is
    known in the record.
    """
    now = time.time() if now is None else now
    event = payload.get("hook_event_name")
    repo = None
    for start in (payload.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        repo = Repo.find(start) if start else None
        if repo is not None:
            break  # the agent may have changed directory; the project root still counts
    if repo is None:
        return None
    sid = str(payload.get("session_id") or "unknown")
    if event == "SessionStart":
        head = PROTOCOL.format(abs=repo.cfg["abstraction_dir"])
        text = head + repo.overview_text(me=sid, now=now)
        if len(text) > START_LIMIT:
            # Cutting the end would drop the open work and the other sessions, which only this
            # context gives at the start. The invariants are what can be fetched later.
            text = head + repo.overview_text(me=sid, now=now, brief=True)
        return _context("SessionStart", text[:START_LIMIT])
    if event == "PreToolUse":
        return _pre(repo, sid, payload, now, agent)
    if event in ("PostToolUse", "PostToolUseFailure"):
        return _post(repo, sid, payload, now, failed=(event == "PostToolUseFailure"), agent=agent)
    if event in ("Stop", "SessionEnd"):
        with _session(repo, sid) as sess:
            _tick(repo, sid, sess, "stop", _current(repo, sid, sess, now), now)
            worked = sess.pop("worked", None) or []
            # The turn changed code or ran the check under these tasks: a round of work under each of
            # their nodes. It is raised here, and said to the agent at its next tool call.
            raised = [repo.round_ended(tid, "work", session=sid)
                      for tid in ([worked] if isinstance(worked, str) else worked)]
            if any(raised):
                sess["verify"] = sorted({node for node in raised if node})
            sess.pop("unasked", None)        # the turn is over: the next one owes its own report
            sess.pop("unasked_told", None)
    return None


def main(agent: str = "claude-code") -> int:
    payload = {}
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        out = handle(payload, agent=agent)
        if out:
            sys.stdout.write(json.dumps(out))
    except Exception:  # noqa: BLE001 - a hook must never break the session
        try:
            repo = Repo.find((payload or {}).get("cwd") or os.getcwd())
            if repo:
                with open(str(repo.dir / "hook-errors.log"), "a", encoding="utf-8") as fh:
                    fh.write(traceback.format_exc() + "\n")
        except Exception:  # noqa: BLE001
            pass
    return 0
