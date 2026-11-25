"""Working without hooks: count edits from the working tree, and carry a person's word from the viewer.

An agent whose tool calls no hook sees (a cloud session that reaches the project through a remote
shell, a CI job, an agent with only a terminal) still edits files that land in the project folder.
`sync` counts those edits the way a hook would have: it takes a snapshot of the working tree and,
on the next call, records every file that changed since as a patch on the session's task.

The viewer served by `thinspec serve` is where a person watches such an agent. What the person says
there (a message, or a decision on a paused task) goes to the record, and the agent reads it with
`thinspec inbox`; any other command the agent runs tells it that something is waiting.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import ThinSpecError
from .core import Repo
from .ledger import Task

SYNC_DIR = "sync"
# What a person says reaches the agent; a decision the person took in the viewer does too.
INBOX_EVENTS = ("message", "decision")


# ---- the working tree ----------------------------------------------------

def _git(root: Path, *args: str, env: Optional[dict] = None) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    if proc.returncode != 0:
        raise ThinSpecError("git %s failed: %s" % (" ".join(args[:2]), proc.stderr.strip()[:300]))
    return proc.stdout


def _in_git(root: Path) -> bool:
    try:
        return _git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except (ThinSpecError, OSError):
        return False


def _key(session: Optional[str]) -> str:
    return hashlib.sha1((session or "default").encode("utf-8")).hexdigest()[:12]


def _git_snapshot(repo: Repo, key: str) -> str:
    """The whole working tree as a git tree, built in a private index: the real index is untouched."""
    index = repo.dir / SYNC_DIR / (key + ".index")
    index.parent.mkdir(parents=True, exist_ok=True)
    env = {"GIT_INDEX_FILE": str(index)}
    _git(repo.root, "add", "-A", "--", ".", ":(exclude).thinspec", env=env)
    return _git(repo.root, "write-tree", env=env).strip()


def _git_changes(repo: Repo, old: str, new: str) -> List[Tuple[str, int]]:
    prefix = _git(repo.root, "rev-parse", "--show-prefix").strip()
    out = _git(repo.root, "diff-tree", "-r", "--numstat", "--no-renames", old, new)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        lines = (int(added) if added.isdigit() else 0) + (int(deleted) if deleted.isdigit() else 0)
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        rows.append((path, lines))
    return rows


def _walk_snapshot(repo: Repo) -> Dict[str, List]:
    """Outside git: a hash and a line count per file, so changes are found and roughly sized."""
    snap: Dict[str, List] = {}
    for dirpath, dirnames, filenames in os.walk(repo.root):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".thinspec", "__pycache__", "node_modules")]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                data = p.read_bytes()
            except OSError:
                continue
            rel = p.relative_to(repo.root).as_posix()
            snap[rel] = [hashlib.sha1(data).hexdigest(), data.count(b"\n")]
    return snap


def _walk_changes(old: Dict[str, List], new: Dict[str, List]) -> List[Tuple[str, int]]:
    rows = []
    for rel in sorted(set(old) | set(new)):
        a, b = old.get(rel), new.get(rel)
        if a == b:
            continue
        if a is None or b is None:
            rows.append((rel, (a or b)[1]))
        else:
            rows.append((rel, max(1, abs(b[1] - a[1]))))   # same length, different content: at least one line
    return rows


def session_task(repo: Repo, session: Optional[str]) -> Optional[Task]:
    """The task a session works on: the one it touched last if still open, else the only open task no one holds."""
    state = repo.state()
    sess = state.sessions.get(session or "")
    if sess and sess.task and sess.task in state.tasks and state.tasks[sess.task].is_open:
        return state.tasks[sess.task]
    open_tasks = state.open_tasks()
    if len(open_tasks) == 1 and not repo.holders(open_tasks[0].id, but=session, state=state):
        return open_tasks[0]
    return None


def sync(repo: Repo, task_id: Optional[str] = None) -> dict:
    """Record the files changed since this session's last sync. The first call only takes the snapshot."""
    from .hooks import _zone

    key = _key(repo.actor)
    meta_path = repo.dir / SYNC_DIR / (key + ".json")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    git = _in_git(repo.root)
    if git:
        new = _git_snapshot(repo, key)
        changes = _git_changes(repo, meta["tree"], new) if meta.get("tree") else None
        meta = {"tree": new}
    else:
        new_walk = _walk_snapshot(repo)
        changes = _walk_changes(meta["files"], new_walk) if "files" in meta else None
        meta = {"files": new_walk}

    task = repo.task(task_id) if task_id else session_task(repo, repo.actor)
    if task_id and not task.is_open:
        raise ThinSpecError("Task %s is %s; edits are counted on an open task." % (task.id, task.status))
    result = {"baseline": changes is None, "git": git, "task": task.id if task else None,
              "code": [], "abstraction": []}
    for rel, lines in changes or []:
        zone = _zone(repo, rel)
        if zone == "code":
            repo.record_patch(task.id if task else None, repo.actor, rel, lines)
            result["code"].append((rel, lines))
        elif zone == "abstraction":
            repo.ledger.append({"ev": "abstraction_edited", "file": rel, "node": Path(rel).stem,
                                "session": repo.actor, "via": "sync"})
            result["abstraction"].append((rel, lines))
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return result


# ---- what a person says ----------------------------------------------------

def post_message(repo: Repo, text: str, node: Optional[str] = None, task: Optional[str] = None,
                 via: str = "cli") -> dict:
    text = (text or "").strip()
    if not text:
        raise ThinSpecError("Say something: the message is empty.")
    if node:
        repo.node(node)
    if task:
        repo.task(task)
    ev = {"ev": "message", "by": "person", "via": via, "text": text[:4000]}
    if node:
        ev["node"] = node
    if task:
        ev["task"] = task
    return repo.ledger.append(ev)


def _read_upto(events: List[dict], session: Optional[str]) -> int:
    upto = -1
    for e in events:
        if e.get("ev") == "inbox_read" and e.get("session") == (session or "default"):
            upto = max(upto, int(e.get("upto") or -1))
    return upto


def unread(repo: Repo, session: Optional[str] = None) -> List[Tuple[int, dict]]:
    """What the person said, or decided, since this session last read its inbox."""
    events = repo.ledger.events()
    upto = _read_upto(events, session)
    out = []
    for seq, e in enumerate(events):
        if seq <= upto or e.get("ev") not in INBOX_EVENTS:
            continue
        if e.get("ev") == "decision" and e.get("by") != "person":
            continue  # a decision recorded from a terminal is already known to whoever typed it
        out.append((seq, e))
    return out


def mark_read(repo: Repo, session: Optional[str], upto: int) -> None:
    repo.ledger.append({"ev": "inbox_read", "session": session or "default", "upto": upto})


def inbox_line(seq_ev: Tuple[int, dict]) -> str:
    _seq, e = seq_ev
    where = " (on %s)" % (e.get("task") or e.get("node")) if (e.get("task") or e.get("node")) else ""
    if e.get("ev") == "message":
        return "%s  your person%s: %s" % (e.get("ts", "")[:16].replace("T", " "), where, e.get("text"))
    choice = str(e.get("choice") or "").replace("_", " ")
    extra = ""
    if e.get("extend"):
        extra = " (+%s)" % ", ".join("%s %s" % (v, k) for k, v in e["extend"].items())
    note = ": %s" % e.get("note") if e.get("note") else ""
    return "%s  your person decided %s on %s%s%s" % (e.get("ts", "")[:16].replace("T", " "), choice,
                                                  e.get("task"), extra, note)


def inbox_notice(repo: Repo) -> Optional[str]:
    """One line for an agent's session when the person has said something it has not read."""
    if not repo.actor:
        return None
    try:
        n = len(unread(repo, repo.actor))
    except Exception:   # a notice never breaks the command it rides on
        return None
    if not n:
        return None
    return "thinspec: %d new from your person in the viewer. Read it with `thinspec inbox`." % n


# ---- the viewer's actions --------------------------------------------------

def viewer_action(repo: Repo, path: str, body: dict) -> dict:
    """What a press in the served viewer does. The person is the one pressing: nothing here asks again."""
    if path == "/api/message":
        ev = post_message(repo, str(body.get("text") or ""), node=body.get("node") or None,
                          task=body.get("task") or None, via="viewer")
        return {"ok": True, "said": ev.get("text")}
    if path == "/api/decide":
        choice = str(body.get("choice") or "").replace("-", "_")
        extend = {k: body[k] for k in ("trials", "lines", "patches", "minutes") if body.get(k)}
        task = repo.decide(str(body.get("task") or ""), choice, note=str(body.get("note") or ""),
                           extend=extend or None, ban_text=body.get("text") or None, by="person")
        return {"ok": True, "task": task.id, "status": task.status}
    raise ThinSpecError("Unknown action %s." % path)
