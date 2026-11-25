"""The graph viewer: one self-contained HTML page, written to a file or served live."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional

from . import store
from .core import UNITS, Repo, fmt_budget, fmt_num, fmt_when
from .ledger import MAJOR_REVIEW_PASSES, State, Task, iso

TEMPLATE = Path(__file__).parent / "assets" / "viewer.html"
MAX_TIMELINE = 200


def _task(t: Task, required: List[dict]) -> dict:
    if not t.is_open:
        required = [{"cmd": t.check_runs.get(cmd, {}).get("command", cmd)}
                    for cmd in dict.fromkeys([*t.check_runs, *t.dropped])]
    return {
        "id": t.id, "title": t.title, "parent": t.parent, "status": t.status,
        "check": t.check, "check_cmd": t.check_cmd,
        "budget": dict(t.budget), "set_by": t.set_by, "confirmed": t.confirmed, "guess": t.guess,
        "actual": {k: round(v, 1) for k, v in t.actual().items()},
        "lines": t.lines, "files": len(t.files), "failed": t.failed,
        "self_reported": t.self_reported, "hit": t.hit_budget,
        "alarms": [{"ts": a.get("ts"), "exhausted": a.get("exhausted") or []} for a in t.alarms],
        "decisions": [{"ts": d.get("ts"), "choice": d.get("choice"), "note": d.get("note") or ""} for d in t.decisions],
        "created": t.created, "started": t.started, "ended": t.ended, "result": t.result,
        "started_by": t.started_by, "worked_on_by": list(t.sessions),
        "metrics": t.metrics,
        "check_review": "pending" if t.check_review_pending else "recorded" if t.metric_read else None,
        "required_checks": [{**check, "passed": Repo.check_passed(t, check), "dropped": t.dropped.get(check["cmd"])}
                            for check in required],
        "review": {"required": MAJOR_REVIEW_PASSES, "passed": t.review_passes, "verdicts": list(t.reviews.values())}
                  if t.major else None,
    }


def _timeline(state: State) -> List[dict]:
    """Design-level events as sentences, newest first."""
    out: List[dict] = []
    for e in state.timeline:
        kind, ts = e.get("ev"), e.get("ts")
        task = state.tasks.get(e.get("task") or "")
        label = "%s “%s”" % (task.id, task.title) if task else (e.get("task") or "")
        after = " after %s" % task.id if task else ""
        if kind == "node_revised":
            item = {"kind": "revise",
                    "text": ("Design '%s' reworded%s, still v%s" % (e.get("node"), after, e.get("to")) if e.get("edit")
                             else "Design '%s' revised%s: v%s → v%s" % (e.get("node"), after, e.get("from"), e.get("to"))),
                    "note": e.get("reason") or ""}
        elif kind == "node_verified":
            item = {"kind": "edit", "text": "Design '%s' verified, still fits" % e.get("node"),
                    "note": e.get("note") or ""}
        elif kind == "ban_added":
            item = {"kind": "ban", "text": "Banned under '%s'%s: %s" % (e.get("node"), after, e.get("text")),
                    "note": e.get("reason") or ""}
        elif kind == "alarm":
            used = ", ".join(
                "%s/%s %s" % (fmt_num(u.get("actual") or 0), fmt_num(u.get("budget") or 0), UNITS.get(u.get("metric"), ""))
                for u in e.get("usage") or []
            )
            item = {"kind": "alarm", "text": "%s went far past its estimate" % label, "note": used}
        elif kind == "decision":
            if e.get("choice") in ("ban", "step_back") and e.get("by") != "person":
                continue  # the ban or the revision that follows tells the same story
            choice = str(e.get("choice") or "").replace("_", " ")
            extra = " (+%s)" % fmt_budget(e.get("extend") or {}) if e.get("choice") == "extend" else ""
            where = " in the viewer" if e.get("by") == "person" else ""
            item = {"kind": "decision", "text": "Decision on %s%s: %s%s" % (label, where, choice, extra),
                    "note": e.get("note") or ""}
        elif kind == "task_started":
            item = {"kind": "start", "text": "Started: %s" % label, "note": ""}
        elif kind == "message":
            about = " about %s" % (e.get("task") or e.get("node")) if (e.get("task") or e.get("node")) else ""
            item = {"kind": "message", "text": "You said%s" % about, "note": e.get("text") or ""}
        elif kind == "task_done":
            item = {"kind": "done", "text": "Done: %s" % label, "note": e.get("result") or ""}
        elif kind == "abstraction_edited":
            item = {"kind": "edit", "text": "Abstraction edited: %s" % e.get("file"), "note": ""}
        elif kind == "node_added":
            item = {"kind": "add", "text": "Design '%s' added" % e.get("node"), "note": e.get("title") or ""}
        elif kind == "node_moved":
            item = {"kind": "edit", "note": e.get("reason") or "",
                    "text": "Design '%s' moved from under '%s' to under '%s'" % (e.get("node"), e.get("from"), e.get("to"))}
        elif kind == "node_renamed":
            item = {"kind": "edit", "text": "Design '%s' renamed '%s'" % (e.get("from"), e.get("to")), "note": ""}
        elif kind == "node_retired":
            moved = ", its tasks moved to '%s'" % e.get("into") if e.get("into") else ""
            item = {"kind": "edit", "text": "Design '%s' retired%s" % (e.get("node"), moved),
                    "note": e.get("reason") or ""}
        else:
            continue
        item["ts"] = ts
        out.append(item)
    return list(reversed(out))[:MAX_TIMELINE]


def _sessions(repo: Repo, state: State, me: Optional[str]) -> List[dict]:
    """Every session in the picture, with its task and the names a drawing needs."""
    rows = []
    for r in repo.sessions(state, me=me):
        row = {k: r[k] for k in ("id", "name", "agent", "host", "dir", "here", "me", "task", "state", "last")}
        row["since"] = fmt_when(r["last_ts"])   # the same moment in local time, for showing
        rows.append(row)
    return rows


def build_data(repo: Repo, me: Optional[str] = None) -> dict:
    """The whole state as one value. `me` is the session asking, marked among the sessions."""
    nodes, events = repo.nodes(), repo.ledger.events()
    from .ledger import DIGEST_SECTIONS, replay

    state = replay(events)
    health = repo.health(nodes, state)
    revisions = [e for e in state.timeline if e.get("ev") == "node_revised"]
    node_rows = []
    for n, _depth in store.walk(nodes):  # reading order: a design, then what is under it
        node_rows.append({
            "id": n.id, "title": n.title, "kind": n.kind, "parent": n.parent, "version": n.version,
            "summary": n.summary, "invariants": n.invariants, "bans": n.bans, "lines": n.lines,
            "health": health[n.id],
            **repo.implementation(n.id, nodes),
            "digest": {name: list((state.digest.get(n.id) or {}).get(name, [])) for name in DIGEST_SECTIONS},
            "history": [
                {"version": v, "title": old.title, "summary": old.summary, "invariants": old.invariants, "bans": old.bans}
                for v, old in store.history(repo.abs_dir, n.id)
            ],
            "revisions": [
                {"from": e.get("from"), "to": e.get("to"), "reason": e.get("reason") or "",
                 "task": e.get("task"), "ts": e.get("ts")}
                for e in revisions if e.get("node") == n.id
            ],
        })
    stamps = [int(p.stat().st_mtime) for p in store.node_files(repo.abs_dir)]
    owed = repo.to_verify(nodes, state)
    warnings = store.problems(repo.abs_dir, repo.cfg)
    return {
        "repo": repo.root.name,
        "generated": iso(),
        "fingerprint": [len(events), stamps],
        "size": repo.size(),
        "cfg": {"alarm_ratio": repo.cfg["alarm_ratio"], "stepback_alarms": repo.cfg["stepback_alarms"]},
        "nodes": node_rows,
        "tasks": [_task(t, repo.kept_checks(t, state, nodes) if t.is_open else []) for t in state.tasks.values()],
        "sessions": _sessions(repo, state, me),
        "timeline": _timeline(state),
        "untracked": {"patches": state.untracked_patches, "lines": state.untracked_lines},
        "to_verify": owed,
        "problems": warnings + repo.to_verify_text(owed),
        "spec_warnings": warnings,
    }


def render_html(repo: Repo, live: bool = False, token: str = "") -> str:
    data = json.dumps(build_data(repo), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8")
    return (html.replace("__LIVE__", "true" if live else "false").replace("__TOKEN__", json.dumps(token))
            .replace("__DATA__", data))


def write_static(repo: Repo, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(repo, live=False), encoding="utf-8")
    return out


MAX_POST = 64 * 1024


def handle_post(repo: Repo, path: str, headers, raw: bytes, token: str) -> tuple:
    """A press in the viewer: (status, body). Only the page this server handed out may press."""
    from . import ThinSpecError
    from .remote import viewer_action

    if not token or headers.get("X-ThinSpec-Token") != token:
        return 403, {"ok": False, "error": "This page is not the one the server handed out; reload it."}
    origin = headers.get("Origin")
    if origin and not origin.startswith(("http://127.0.0.1:", "http://localhost:")):
        return 403, {"ok": False, "error": "Presses come only from the local viewer."}
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError
    except ValueError:
        return 400, {"ok": False, "error": "Send a JSON object."}
    try:
        return 200, viewer_action(repo, path, body)
    except ThinSpecError as exc:
        return 400, {"ok": False, "error": str(exc)}


def serve(repo: Repo, port: int = 8765, open_browser: bool = False) -> int:
    import secrets

    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - http.server naming
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(render_html(repo, live=True, token=token).encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._send(json.dumps(build_data(repo)).encode("utf-8"), "application/json")
            else:
                self.send_error(404)

        def do_POST(self):  # noqa: N802 - http.server naming
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_POST:
                self.send_error(413)
                return
            status, body = handle_post(repo, self.path.split("?", 1)[0], self.headers,
                                       self.rfile.read(length), token)
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # keep the terminal quiet
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("ThinSpec viewer for %s at %s  (Ctrl-C to stop)" % (repo.root.name, url))
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
