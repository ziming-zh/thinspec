"""A small MCP server over stdio, so any agent can read the abstraction and declare its work.

It speaks newline-delimited JSON-RPC 2.0 and implements only what tools need:
initialize, ping, tools/list and tools/call. No third-party packages.
"""
from __future__ import annotations

import json
import os
import re
import sys
import uuid
from typing import Callable, List, Optional

from . import ThinSpecError, __version__
from .ledger import DIGEST_SECTIONS
from .core import Repo, agent_from_env, fmt_budget, fmt_usage, session_from_env

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "ThinSpec keeps this repository's design as a small graph of nodes with invariants and bans, and "
    "tracks implementation tasks against budgets. Call overview first. Before implementing, call "
    "task_start with the parent node, a check and a budget. A budget is stated in what a person can judge: "
    "runs of the check until the result is solid, and lines of code changed, never time. It is an estimate: "
    "reaching it stops nothing, and you look at why the work is taking more than expected. When you cannot "
    "size the work, start with your best numbers at low confidence and ask the user for theirs without "
    "waiting. When a task goes far past its estimate, stop and let the user decide: extend, step back and "
    "revise the design, or ban the approach."
)


def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _num(desc: str) -> dict:
    return {"type": "number", "description": desc}


# A budget is asked for in what a person can judge. Time and the number of edits are still
# counted, and a budget given in them is still read (LEGACY), but no tool offers them.
BUDGET_PROPS = {
    "trials": _num("How many runs of the check you expect until it passes and the result is solid."),
    "lines": _num("How many lines of code you expect to change, tests included."),
}
LEGACY_BUDGET = ("patches", "minutes")

TOOLS: List[dict] = [
    {
        "name": "overview",
        "description": "The current abstraction graph: every node with its invariants, bans and health, "
                       "plus open and planned tasks. Call this before starting work.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "context",
        "description": "Everything that binds work under one node: invariants and bans of the node and of "
                       "every node above it, why it was revised, and the tasks already tried under it.",
        "inputSchema": {"type": "object", "properties": {"node": _str("Node id.")}, "required": ["node"]},
    },
    {
        "name": "task_plan",
        "description": "Record a leaf task under a design without starting it. A task with a check is "
                       "ready to delegate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent": _str("Id of the design node this task implements."),
                "title": _str("Short title of the task."),
                "check": _str("How the task is verified: a command, or a measurable criterion."),
                "check_cmd": _str("Optional exact command that runs the check; each run counts as a trial."),
            },
            "required": ["parent", "title", "check"],
        },
    },
    {
        "name": "task_start",
        "description": "Start work on a task and set its budget. Either name a planned task, or give "
                       "parent, title and check for a new one. The budget is your honest estimate in what a "
                       "person can judge: trials (runs of the check until the result is solid) and lines "
                       "(of code changed). Time is not budgeted. The user sees the budget and can change it. "
                       "When you cannot size the work, give your best numbers with confidence \"low\": you "
                       "then ask the user for theirs and go on without waiting. Returns the rules that bind "
                       "the task.",
        "inputSchema": {
            "type": "object",
            "properties": dict(
                {
                    "task": _str("Id of a planned task to start (e.g. T3)."),
                    "parent": _str("For a new task: id of the design node it implements."),
                    "title": _str("For a new task: short title."),
                    "check": _str("For a new task: how it is verified."),
                    "check_cmd": _str("Optional exact command that runs the check."),
                    "confidence": {
                        "type": "string", "enum": ["ok", "low"],
                        "description": "low when you cannot size this work from what you know: debugging a "
                                       "kernel or a training run, tuning, flaky behaviour, code you have not "
                                       "read. The estimate is then marked as a guess. Default: ok.",
                    },
                },
                **BUDGET_PROPS
            ),
        },
    },
    {
        "name": "task_metric",
        "description": "Answer the one question asked when a task starts: is a metric missing from its check, so "
                       "that the check could pass while the goal is not met? Add a metric only when it clearly "
                       "lowers the chance of reward hacking; corner cases are not a reason. It is marked as your "
                       "own, and the person can reword or drop it. If none is missing, call this with none=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": _str("Task id."),
                "metric": _str("The metric to add: what is measured, on what, and what would not count."),
                "none": {"type": "boolean", "description": "True when no metric is missing: the usual answer."},
                "note": _str("Optional: why it lowers the chance of reward hacking, or why nothing is missing."),
            },
            "required": ["task"],
        },
    },
    {
        "name": "task_budget",
        "description": "Record the budget the user gave for a task, in their numbers: trials (runs of the "
                       "check until the result is solid) and/or lines (of code changed). It replaces the "
                       "budget the task had and is theirs from then on, no longer a guess. Only call this "
                       "with numbers the user stated.",
        "inputSchema": {
            "type": "object",
            "properties": dict({"task": _str("Task id."), "note": _str("What the user's numbers rest on, in their words.")},
                               **BUDGET_PROPS),
            "required": ["task"],
        },
    },
    {
        "name": "task_report",
        "description": "Report work done on a task when nothing counts it automatically (agents without "
                       "ThinSpec hooks). Amounts are added to the task's totals.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": _str("Task id."),
                "trials": _num("Runs of the check since the last report."),
                "lines": _num("Lines of code changed since the last report."),
                "patches": _num("File edits since the last report."),
                "minutes": _num("Minutes worked since the last report."),
                "note": _str("Optional one-line note."),
            },
            "required": ["task"],
        },
    },
    {
        "name": "task_done",
        "description": "Close a task whose check passes. State the measured result, for a reader who "
                       "will look at results and not at code.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": _str("Task id."), "result": _str("The measured result, in one or two sentences."),
                "dropped": {
                    "type": "array",
                    "description": "Checks that earlier work under the design passed and that this task closes "
                                   "without, because the old behaviour they checked was meant to go: each with "
                                   "the reason. Every other such check must pass again first.",
                    "items": {"type": "object", "properties": {"check": _str("The command, as listed."),
                                                               "why": _str("Why it no longer applies.")},
                              "required": ["check", "why"]},
                },
            },
            "required": ["task", "result"],
        },
    },
    {
        "name": "node_digest",
        "description": "Rewrite sections of a node's digest: the few lines the person reads in place of its "
                       "tasks. features: what the node can do now. as_built: where what is built departs from "
                       "the node's story, and why, in one line; say 'likely' when the reason is your reading. "
                       "reverts: what was tried and turned back, and why. positive, negative: what runs of experiments came to, for and against; an ordinary "
                       "check that passes is not a result. A section you give replaces what was there, and holds "
                       "five short lines at most: merge lines that say one thing, drop what no longer matters. "
                       "Write in the person's terms: no task id, no file, no count of tests.",
        "inputSchema": {
            "type": "object",
            "properties": dict({"node": _str("Node id.")},
                               **{name: {"type": "array", "items": {"type": "string"}} for name in DIGEST_SECTIONS}),
            "required": ["node"],
        },
    },
    {
        "name": "task_decide",
        "description": "Record the user's decision on a task, usually after it went far past its estimate. Only call "
                       "this with a choice the user made. extend: add budget. step_back: close the task and "
                       "open a new version of its parent design. ban: close the task and add the approach to "
                       "the parent's ban list. abandon: close the task.",
        "inputSchema": {
            "type": "object",
            "properties": dict(
                {
                    "task": _str("Task id."),
                    "choice": {"type": "string", "enum": ["extend", "step_back", "ban", "abandon"]},
                    "note": _str("The reason, in the user's terms."),
                    "ban_text": _str("For ban: the approach to never take again, in one line."),
                },
                **{k: _num("For extend: additional %s." % k) for k in BUDGET_PROPS}
            ),
            "required": ["task", "choice"],
        },
    },
    {
        "name": "ban_add",
        "description": "Add an approach to a node's ban list so it is never tried again under that node. "
                       "It does not wait for the user: tell them of it when the turn ends.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": _str("Node id."),
                "text": _str("The banned approach, in one line."),
                "reason": _str("Why it is not worth taking again."),
            },
            "required": ["node", "text", "reason"],
        },
    },
    {
        "name": "node_revise",
        "description": "Call this before rewriting a node's file, with the reason: the current text is kept. "
                       "A version is a decision, so the number goes up only with decision=true: a rule of the "
                       "node is added, dropped or reversed, or the person stepped back. A clearer sentence, a "
                       "new name or text moved is a rewording: leave decision out, and the number stays. "
                       "It does not wait for the user: tell them of it when the turn ends.",
        "inputSchema": {
            "type": "object",
            "properties": {"node": _str("Node id."), "reason": _str("What was learned that the old design missed."),
                           "decision": {"type": "boolean", "description": "True only when the decision the node "
                                        "states changes. Default false: a rewording, which takes no new number."}},
            "required": ["node", "reason"],
        },
    },
    {
        "name": "node_verify",
        "description": "Record that a node was verified and still fits. A node is owed a verification after a "
                       "round of work under it (a task closed with a result, or a turn that changed code or ran "
                       "the check) and after the node above it or a node under it was revised. Call it for each "
                       "node the overview lists under 'To verify', unless the node no longer fits: then revise "
                       "it with node_revise, which carries the change on to the nodes next to it. It does not "
                       "wait for the user: tell them of it when the turn ends.",
        "inputSchema": {
            "type": "object",
            "properties": {"node": _str("Node id."),
                           "note": _str("Why it still fits: what in the result or the code, or in the node that "
                                        "changed, it was read against.")},
            "required": ["node", "note"],
        },
    },
    {
        "name": "node_move",
        "description": "Put a node under another one: its place changes, its text, version and tasks stay. Use "
                       "it when verifying a node shows that the whole node holds more generally than where it "
                       "sits, and belongs a level up. Never edit a node's parent line by hand: the nodes next "
                       "to it would not be put up to be verified. It does not wait for the user: tell them of "
                       "it when the turn ends.",
        "inputSchema": {
            "type": "object",
            "properties": {"node": _str("Node id."), "under": _str("Id of the node it should sit under."),
                           "reason": _str("What showed that it belongs there.")},
            "required": ["node", "under", "reason"],
        },
    },
    {
        "name": "node_restore",
        "description": "Switch a node back to the text of an earlier version, as a new version. The text it "
                       "replaces is archived, so the switch can itself be undone. Call it when the user asks "
                       "to go back on a change to the design. It does not wait for the user: tell them of it "
                       "when the turn ends.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "node": _str("Node id."),
                "version": {"type": "integer", "description": "The version to bring back. Default: the one "
                                                              "before the current."},
                "reason": _str("Why the newer text is being dropped."),
            },
            "required": ["node"],
        },
    },
]


def _budget_args(args: dict) -> dict:
    return {k: args.get(k) for k in tuple(BUDGET_PROPS) + LEGACY_BUDGET if args.get(k)}


ASK_THE_USER = (
    "You marked this estimate as a guess. Ask the user for their numbers now, in your message, and do not "
    "wait for the answer: about how many runs of the check until the result is solid, and about how many "
    "lines they expect to change. Say what your numbers are, and that they stand if the user does not "
    "answer. If the user gives numbers, record them with task_budget.\n\n"
)


def agent_name(client_name) -> str:
    """The agent as the record names it, from what the MCP client calls itself.

    "claude-code" stays as it is, and Codex's "codex-mcp-client" becomes "codex".
    """
    name = re.sub(r"[^a-z0-9._-]+", "-", str(client_name or "").strip().lower()).strip("-")
    name = re.sub(r"-?(mcp-client|mcp|client)$", "", name)
    return name[:24] or "agent"


def _sign(repo: Repo, client: Optional[dict]) -> None:
    """Make the repo act as this client's session: what the tools record is signed with it."""
    if client and client.get("session"):
        repo.actor, repo.actor_agent = client["session"], client.get("agent") or agent_from_env()


def call_tool(repo: Repo, name: str, args: dict) -> str:
    if name == "overview":
        return repo.overview_text()
    if name == "context":
        return repo.context_text(str(args.get("node") or ""))
    if name == "task_plan":
        tid = repo.plan_task(str(args.get("parent") or ""), str(args.get("title") or ""),
                             str(args.get("check") or ""), args.get("check_cmd"), set_by="agent")
        return "Planned %s under '%s'. It has a check, so it is ready to delegate." % (tid, args.get("parent"))
    if name == "task_start":
        named = repo.state().tasks.get(str(args.get("task") or ""))
        joined = bool(repo.actor and named is not None and named.is_open)
        task = repo.start_task(
            task_id=args.get("task") or None, parent=args.get("parent"), title=args.get("title"),
            check=args.get("check"), check_cmd=args.get("check_cmd"),
            budget=_budget_args(args), set_by="agent", guess=(args.get("confidence") == "low"),
        )
        others = repo.others_text(repo.actor) if repo.actor else ""
        ask_metric = "" if joined or task.metric_read else (
            "One question before any code: read the check of %s once. Is a metric missing, so that the check "
            "could pass while the goal is not met (one number standing for a mechanism the design depends on, "
            "or a goal with nothing pulling against it)? Add one with task_metric only when it clearly lowers "
            "the chance of reward hacking, and leave corner cases alone. Finding nothing missing is the usual "
            "answer: record it with task_metric none=true. Nothing waits on the person either way.\n\n" % task.id)
        kept = repo.kept_checks(task)
        keep = ("Earlier work under '%s' passed these checks, and this task closes only once each passes again "
                "(or is dropped with the reason it no longer applies):\n%s\n\n"
                % (task.parent, "\n".join("  `%s` (%s)" % (k["cmd"], k["task"]) for k in kept))) if kept else ""
        return (
            ("" if joined or not task.guess else ASK_THE_USER) +
            "%s %s \"%s\" under '%s'. Budget: %s.\n\nRules that bind this task:\n%s\n\n%s"
            "When the check passes, call task_done with the measured result. The budget is an estimate: "
            "reaching it stops nothing. If the task goes far past it, stop and report to the user."
            % ("Joined" if joined else "Started", task.id, task.title, task.parent,
               "%s, used %s; it was set when the task started and joining does not change it"
               % (fmt_budget(task.budget), fmt_usage(task)) if joined else fmt_budget(task.budget),
               repo.context_text(task.parent) + ("\n\n" + keep.rstrip() if keep else "")
               + ("\n\n" + ask_metric.rstrip() if ask_metric else ""),
               "Other sessions at work in this project (their tasks are theirs; you are told if you edit "
               "a file one of them has edited):\n%s\n\n" % others if others else "")
        )
    if name == "task_report":
        tid = str(args.get("task") or "")
        before = set(repo.task(tid).past())
        task = repo.report(tid, int(args.get("trials") or 0),
                           int(args.get("patches") or 0), float(args.get("minutes") or 0),
                           str(args.get("note") or ""), lines=int(args.get("lines") or 0))
        text = "%s: %s." % (task.id, fmt_usage(task))
        if task.status == "blocked":
            text += (
                " The task is far past its estimate. Stop work on it and report to the user what was tried "
                "and whether the failures point at the design '%s'. They choose: extend, step back, or ban."
                % task.parent
            )
        elif set(task.past()) - before:
            text += (
                " The estimate is reached. This stops nothing: look at why the work is taking more than "
                "expected, tell the user if the cause is the design '%s', and otherwise carry on."
                % task.parent
            )
        return text
    if name == "task_metric":
        task = repo.add_metric(str(args.get("task") or ""), str(args.get("metric") or ""),
                               none=args.get("none") is True, note=str(args.get("note") or ""), by="agent")
        if args.get("none") is True:
            return "Recorded for %s: no metric is missing from its check." % task.id
        return ("Added to the check of %s, marked as your own: %s. The check as first written is kept, and the "
                "person can reword or drop it." % (task.id, task.metrics[-1]["text"]))
    if name == "task_budget":
        task = repo.set_budget(str(args.get("task") or ""), _budget_args(args), by="user",
                               note=str(args.get("note") or ""))
        return ("The budget of %s is now %s, set by the user. Used so far: %s."
                % (task.id, fmt_budget(task.budget), fmt_usage(task)))
    if name == "task_done":
        dropped = {str(d.get("check") or ""): str(d.get("why") or "")
                   for d in args.get("dropped") or [] if isinstance(d, dict)}
        task = repo.done_task(str(args.get("task") or ""), str(args.get("result") or ""), dropped)
        owed = [row for row in repo.to_verify() if row["node"] == task.parent and row.get("round")]
        return "Closed %s as done (%s).%s %s" % (
            task.id, fmt_usage(task), " " + repo.verify_prompt(task.parent, owed[0]["round"]) if owed else "",
            repo.digest_prompt(task.parent))
    if name == "node_digest":
        kept = repo.digest(str(args.get("node") or ""),
                           **{s: args.get(s) for s in DIGEST_SECTIONS if isinstance(args.get(s), list)})
        return "The digest of '%s' now reads: %s" % (
            args.get("node"), "; ".join("%s: %s" % (s, " | ".join(kept.get(s) or ["(nothing)"])) for s in DIGEST_SECTIONS))
    if name == "task_decide":
        choice = str(args.get("choice") or "")
        task = repo.decide(str(args.get("task") or ""), choice, note=str(args.get("note") or ""),
                           extend=_budget_args(args), ban_text=args.get("ban_text"), by="user")
        if choice == "extend":
            return "Extended %s. Budget is now %s; used %s." % (task.id, fmt_budget(task.budget), fmt_usage(task))
        if choice == "step_back":
            node = repo.node(task.parent)
            return (
                "Closed %s. Design '%s' is now v%d; its previous text is archived under %s/history/. "
                "Next: agree the revised design with the user, then edit %s."
                % (task.id, node.id, node.version, repo.cfg["abstraction_dir"], node.path.name)
            )
        if choice == "ban":
            return "Closed %s and added the approach to the ban list of '%s'." % (task.id, task.parent)
        return "Closed %s as abandoned." % task.id
    if name == "ban_add":
        repo.add_ban(str(args.get("node") or ""), str(args.get("text") or ""), str(args.get("reason") or ""))
        return "Added to the ban list of '%s'." % args.get("node")
    if name == "node_revise":
        was = repo.node(str(args.get("node") or "")).version
        new = repo.revise(str(args.get("node") or ""), str(args.get("reason") or ""), decision=args.get("decision") is True)
        near = repo.next_to(str(args.get("node") or ""))
        carry = (" Then read again the nodes next to it (%s): revise each that no longer follows, or record "
                 "with node_verify why it still does. A node you revise is carried on the same way."
                 % ", ".join(near)) if near else ""
        return (("'%s' is now v%d." if new != was else "'%s' is still v%d: a rewording takes no new number.")
                % (args.get("node"), new) + " The previous text is kept; rewrite the node file next.%s" % carry)
    if name == "node_verify":
        repo.verify(str(args.get("node") or ""), str(args.get("note") or ""))
        left = [row["node"] for row in repo.to_verify()]
        return ("Recorded: '%s' was verified and still fits.%s"
                % (args.get("node"), " Still to verify: %s." % ", ".join(left) if left else
                   " No other node is owed a verification."))
    if name == "node_move":
        node, under = str(args.get("node") or ""), str(args.get("under") or "")
        left = repo.move_node(node, under, str(args.get("reason") or ""))
        owed = [row["node"] for row in repo.to_verify()]
        return ("'%s' now sits under '%s', no longer under '%s'. Its text, its version and its tasks stay.%s"
                % (node, under, left, " To verify against the move: %s." % ", ".join(owed) if owed else ""))
    if name == "node_restore":
        version = args.get("version")
        restored, new = repo.restore(str(args.get("node") or ""), int(version) if version else None,
                                     str(args.get("reason") or ""))
        return (
            "'%s' holds the text of v%d again, as v%d. The text it replaced is archived under %s/history/."
            % (args.get("node"), restored, new, repo.cfg["abstraction_dir"])
        )
    raise ThinSpecError("Unknown tool '%s'." % name)


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_message(msg: dict, get_repo: Callable[[], Optional[Repo]],
                   client: Optional[dict] = None) -> Optional[dict]:
    """Answer one JSON-RPC message. Notifications get no answer.

    `client` is what this connection knows of the session at its other end: its id and,
    once it has introduced itself, its agent. With it, what the tools record is signed.
    """
    method = msg.get("method")
    msg_id = msg.get("id")
    if msg_id is None:
        return None
    params = msg.get("params") or {}
    if method == "initialize":
        if client is not None:
            client["agent"] = agent_name((params.get("clientInfo") or {}).get("name"))
        wanted = params.get("protocolVersion")
        return _result(msg_id, {
            "protocolVersion": wanted if wanted in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "thinspec", "version": __version__},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            repo = get_repo()
            if repo is None:
                raise ThinSpecError("This directory is not set up for ThinSpec. Run `thinspec init` in the repo.")
            _sign(repo, client)
            text, is_error = call_tool(repo, str(name), args), False
        except ThinSpecError as exc:
            text, is_error = str(exc), True
        except Exception as exc:  # noqa: BLE001 - report, never crash the server
            text, is_error = "ThinSpec internal error: %s" % exc, True
        return _result(msg_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
    return _error(msg_id, -32601, "Method not found: %s" % method)


def serve(start: Optional[str] = None) -> int:
    start = start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    def get_repo() -> Optional[Repo]:
        return Repo.find(start)

    # One server process is one agent session. An agent that names its session in the
    # environment (Claude Code does) keeps that id, so its hooks and its tools sign alike.
    client = {"session": session_from_env() or uuid.uuid4().hex, "agent": None}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply: Optional[dict] = _error(None, -32700, "Parse error")
        else:
            if isinstance(msg, dict):
                reply = handle_message(msg, get_repo, client)
            else:
                reply = _error(None, -32600, "Batches are not supported")
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0
