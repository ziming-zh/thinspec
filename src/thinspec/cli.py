"""Command line for people. Agents use the MCP server (`thinspec mcp`) instead."""
from __future__ import annotations

import argparse
import os
import shlex
import sys
import webbrowser
from pathlib import Path
from typing import List, Optional

from . import ThinSpecError, __version__, store
from .core import Repo, agent_from_env, check_review_prompt, fmt_budget, fmt_usage, session_from_env
from .ledger import MAJOR_REVIEW_PASSES


def _repo(args) -> Repo:
    repo = Repo.find(getattr(args, "root", None) or os.getcwd())
    if repo is None:
        raise ThinSpecError("No ThinSpec repo here. Run `thinspec init` at the root of your project.")
    # Set when an agent session runs the command, not in a person's terminal: by --session and --agent,
    # or by the environment (THINSPEC_SESSION, THINSPEC_AGENT, or Claude Code's own session variable).
    repo.actor = getattr(args, "session", None) or session_from_env()
    repo.actor_agent = getattr(args, "agent", None) or (agent_from_env() if not getattr(args, "session", None) else None)
    _USED.append(repo)
    return repo


_USED: List[Repo] = []   # the repo a command acted on, for the note about what the person said


def _budget(args) -> dict:
    return {k: getattr(args, k, None) for k in ("trials", "lines", "patches", "minutes") if getattr(args, k, None)}


def _add_budget(p) -> None:
    """A budget is asked for in what a person can judge: runs of the check, and size of the change."""
    p.add_argument("--trials", type=int, help="how many runs of the check until the result is solid")
    p.add_argument("--lines", type=int, help="how many lines of code are expected to change, tests included")
    # Older measures. A budget may still be given in them, but nobody is asked for one.
    p.add_argument("--patches", type=int, help=argparse.SUPPRESS)
    p.add_argument("--minutes", type=float, help=argparse.SUPPRESS)


# ---- commands ----------------------------------------------------------

def cmd_init(args) -> int:
    from .install import init

    root = Path(args.root or os.getcwd())
    done = init(root, claude=not args.no_claude, agents_md=args.agents_md, codex=args.codex)
    print("ThinSpec is set up in %s" % root)
    for line in done:
        print("  %s" % (line if line.startswith("removed ") else "wrote %s" % line))
    print("\nNext:")
    print("  1. Fill in abstraction/core.md, then add designs, the decisions that set the direction:")
    print("       thinspec node add <id> --parent core --title \"<the decision, in a plain sentence>\"")
    print("     and under each the components that carry it out:")
    print("       thinspec node add <id> --parent <design> --kind component --title \"<what it is>\"")
    print("  2. Start Claude Code in this repo and approve the thinspec MCP server when asked.")
    print("  3. See the graph: /thinspec in Claude Code (with the thinspec plugin), or thinspec status here.")
    return 0


def cmd_status(args) -> int:
    repo = _repo(args)
    print(repo.overview_text() if args.full else repo.tree_text())
    return 0


def cmd_state(args) -> int:
    import json

    from .viewer import build_data

    repo = _repo(args)
    print(json.dumps(build_data(repo, me=args.session or repo.actor), ensure_ascii=False))
    return 0


def cmd_show(args) -> int:
    repo = _repo(args)
    state = repo.state()
    if args.id in state.tasks:
        print(repo.task_text(state.tasks[args.id]))
    else:
        print(repo.context_text(args.id))
    return 0


def cmd_check(args) -> int:
    repo = _repo(args)
    found = store.problems(repo.abs_dir, repo.cfg) + repo.to_verify_text()
    size = repo.size()
    from .core import abstraction_line
    print(abstraction_line(size))
    for p in found:
        print("  - %s" % p)
    if not found:
        print("  no problems")
    return 1 if found else 0


def cmd_node_add(args) -> int:
    repo = _repo(args)
    path = repo.add_node(args.id, args.title or args.id, args.parent, args.summary or "", args.invariant,
                         kind=args.kind)
    print("Created %s" % path.relative_to(repo.root))
    return 0


def cmd_node_rename(args) -> int:
    repo = _repo(args)
    path = repo.rename_node(args.id, args.new_id)
    print("'%s' is now '%s' (%s). Its tasks and its kept versions followed."
          % (args.id, args.new_id, path.relative_to(repo.root)))
    return 0


def cmd_node_move(args) -> int:
    repo = _repo(args)
    left = repo.move_node(args.id, args.under, args.reason)
    print("'%s' now sits under '%s', no longer under '%s'. Its text, its version and its tasks stay."
          % (args.id, args.under, left))
    owed = [row["node"] for row in repo.to_verify()]
    if owed:
        print("To verify against the move: %s. `thinspec check` lists them until each is." % ", ".join(owed))
    return 0


def cmd_node_digest(args) -> int:
    repo = _repo(args)
    given = {"features": args.feature, "as_built": args.as_built, "reverts": args.revert,
             "positive": args.positive, "negative": args.negative}
    kept = repo.digest(args.id, **{name: lines for name, lines in given.items() if lines is not None})
    for name in given:
        for line in kept.get(name, []):
            print("%-9s %s" % (name, line))
    return 0


def cmd_node_retire(args) -> int:
    repo = _repo(args)
    archived = repo.retire_node(args.id, args.reason, args.into)
    moved = " Its tasks moved to '%s'." % args.into if args.into else ""
    print("'%s' is out of the graph. Its text is kept in %s.%s" % (args.id, archived.relative_to(repo.root), moved))
    return 0


def cmd_revise(args) -> int:
    repo = _repo(args)
    was = repo.node(args.node).version
    new = repo.revise(args.node, args.reason, task=args.task, decision=args.decision)
    print(("'%s' is now v%d." if new != was else "'%s' is still v%d: a rewording takes no new number.") % (args.node, new)
          + " The previous text is in %s/history/. Rewrite the node file next." % repo.cfg["abstraction_dir"])
    near = repo.next_to(args.node)
    if near:
        print("Then read again the nodes next to it (%s): `thinspec check` lists them until each is "
              "revised or recorded as still following." % ", ".join(near))
    return 0


def cmd_verify(args) -> int:
    repo = _repo(args)
    if not args.node:
        owed = repo.to_verify_text()
        print("\n".join(owed) if owed else "No node is owed a verification.")
        return 1 if owed else 0
    repo.verify(args.node, args.note or "")
    left = [row["node"] for row in repo.to_verify()]
    print("Recorded: '%s' was verified and still fits.%s"
          % (args.node, " Still to verify: %s." % ", ".join(left) if left else ""))
    return 0


def cmd_restore(args) -> int:
    repo = _repo(args)
    restored, new = repo.restore(args.node, args.to, args.reason or "")
    print("'%s' holds the text of v%d again, as v%d. The text it replaced is in %s/history/."
          % (args.node, restored, new, repo.cfg["abstraction_dir"]))
    return 0


def cmd_ban(args) -> int:
    repo = _repo(args)
    repo.add_ban(args.node, args.text, args.reason or "", task=args.task)
    print("Added to the ban list of '%s'." % args.node)
    return 0


def cmd_task_add(args) -> int:
    repo = _repo(args)
    tid = repo.plan_task(args.parent, args.title, args.check, args.check_cmd, _budget(args), set_by="user", major=args.major)
    print("Planned %s under '%s' (%s)." % (tid, args.parent, fmt_budget(_budget(args))))
    return 0


def cmd_task_start(args) -> int:
    repo = _repo(args)
    task = repo.start_task(task_id=args.task, parent=args.parent, title=args.title, check=args.check,
                           check_cmd=args.check_cmd, budget=_budget(args), set_by="user", review_check=True, major=args.major)
    print("Started %s \"%s\" under '%s'. Budget: %s." % (task.id, task.title, task.parent, fmt_budget(task.budget)))
    if task.check_review_pending:
        print(check_review_prompt(task))
    owed = repo.owed_checks(task)
    if owed:
        print(repo.owed_text(task, owed))
    if task.major:
        print("%d independent review passes are required before closing." % MAJOR_REVIEW_PASSES)
    return 0


def cmd_task_trial(args) -> int:
    repo = _repo(args)
    task = repo.task(args.task)
    if not task.is_open:
        raise ThinSpecError("Task %s is %s." % (task.id, task.status))
    if task.check_review_pending:
        raise ThinSpecError(check_review_prompt(task))
    passed = True if args.passed else (False if args.failed else None)
    repo.record_trial(task.id, None, args.note or "(recorded by hand)", passed)
    print("%s: %s" % (task.id, fmt_usage(repo.task(task.id))))
    return 0


def cmd_task_patch(args) -> int:
    repo = _repo(args)
    task = repo.report(args.task, patches=args.n, lines=args.lines)
    print("%s: %s" % (task.id, fmt_usage(task)))
    return 0


def cmd_task_budget(args) -> int:
    repo = _repo(args)
    task = repo.set_budget(args.task, _budget(args), by="user", note=args.note or "")
    print("%s: the budget is now %s, set by you. Used so far: %s."
          % (task.id, fmt_budget(task.budget), fmt_usage(task)))
    return 0


def cmd_task_done(args) -> int:
    repo = _repo(args)
    drops = args.drop or []
    if len(drops) != len(args.why or []):
        raise ThinSpecError("Give one --why for each --drop: the reason that earlier check no longer applies.")
    task = repo.done_task(args.task, args.result or "", dict(zip(drops, args.why or [])))
    print("Closed %s as done (%s)." % (task.id, fmt_usage(task)))
    if any(row["node"] == task.parent and row.get("round") for row in repo.to_verify()):
        print("Its result is a round of work under '%s': `thinspec check` lists the node until it is verified "
              "against it." % task.parent)
    return 0


def cmd_task_metric(args) -> int:
    repo = _repo(args)
    if args.reword or args.drop:
        number = (args.reword or [args.drop])[0]
        task = repo.set_metric(args.task, int(number), text=" ".join(args.reword[1:]) if args.reword else None,
                               drop=bool(args.drop))
    elif args.none or args.add:
        task = repo.add_metric(args.task, args.add or "", none=args.none, note=args.note or "", by="user")
    else:
        task = repo.task(args.task)
    print(repo.task_text(task))
    return 0


def cmd_task_review(args) -> int:
    task = _repo(args).review_task(args.task, args.verdict.replace("-", "_"), args.note)
    print("%s: %d/%d independent reviews passed on the current edits." % (task.id, task.review_passes, MAJOR_REVIEW_PASSES))
    return 0


def cmd_run(args) -> int:
    repo = _repo(args)
    words = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not words:
        raise ThinSpecError("Give the command after --: thinspec run T3 -- pytest -q")
    proc = repo.run_check(args.task, words[0] if len(words) == 1 else shlex.join(words))
    sys.stdout.write(proc.stdout[-4000:])
    sys.stderr.write(proc.stderr[-4000:])
    print("Recorded for %s: %s." % (args.task, "passed" if proc.returncode == 0 else
                                   "failed (exit %d)" % proc.returncode))
    return proc.returncode


def cmd_sync(args) -> int:
    from .remote import sync

    repo = _repo(args)
    res = sync(repo, args.task)
    if res["baseline"]:
        print("Took a snapshot of the working tree%s. The next `thinspec sync` records what changed since."
              % ("" if res["git"] else " (no git here: changes are sized roughly by line count)"))
        return 0
    code, spec = res["code"], res["abstraction"]
    if not code and not spec:
        print("Nothing changed since the last sync.")
        return 0
    if code:
        on = "on %s" % res["task"] if res["task"] else "with no task (untracked: start or join one)"
        print("Recorded %d edited file%s, %d lines, %s:" % (len(code), "" if len(code) == 1 else "s",
                                                           sum(n for _, n in code), on))
        for rel, n in code[:20]:
            print("  %s  %d" % (rel, n))
        if len(code) > 20:
            print("  ... and %d more" % (len(code) - 20))
        if res["task"]:
            print("%s: %s" % (res["task"], fmt_usage(repo.task(res["task"]))))
    for rel, _n in spec:
        print("Abstraction edited: %s (record why with `thinspec revise`)" % rel)
    return 0


def cmd_inbox(args) -> int:
    from .remote import inbox_line, mark_read, unread

    repo = _repo(args)
    rows = unread(repo, repo.actor)
    if not rows:
        print("Nothing new from your person.")
        return 0
    for row in rows:
        print(inbox_line(row))
    if not args.peek:
        mark_read(repo, repo.actor, rows[-1][0])
    return 0


def cmd_say(args) -> int:
    from .remote import post_message

    repo = _repo(args)
    post_message(repo, " ".join(args.text), node=args.node, task=args.task, via="cli")
    print("Left for the agent; it reads it with `thinspec inbox`.")
    return 0


def cmd_compare(args) -> int:
    from .comparison import compare

    root = Path(args.root or os.getcwd())
    matches, report = compare(root, args.baseline, args.candidate, args.fixture, args.timeout)
    print("\n".join(report))
    return 0 if matches else 1


def cmd_task_decide(args) -> int:
    repo = _repo(args)
    task = repo.decide(args.task, args.choice, note=args.note or "", extend=_budget(args),
                       ban_text=args.text, by="user")
    print("%s is now %s. Budget %s; used %s." % (task.id, task.status, fmt_budget(task.budget), fmt_usage(task)))
    if args.choice.replace("-", "_") == "step_back":
        node = repo.node(task.parent)
        print("'%s' is now v%d. Rewrite %s to the revised design." % (node.id, node.version, node.path.name))
    return 0


def cmd_task_list(args) -> int:
    repo = _repo(args)
    tasks = list(repo.state().tasks.values())
    if not tasks:
        print("No tasks yet.")
    for t in tasks:
        print("%-4s %-12s %-14s %s  [%s]" % (t.id, t.status, t.parent, t.title, fmt_usage(t)))
    return 0


def cmd_log(args) -> int:
    repo = _repo(args)
    skip = ("patch", "time", "trial")
    events = [e for e in repo.ledger.events() if args.all or e.get("ev") not in skip]
    for e in events[-args.n:]:
        rest = ", ".join("%s=%s" % (k, v) for k, v in sorted(e.items()) if k not in ("ts", "ev") and v not in (None, ""))
        print("%s  %-18s %s" % (e.get("ts", ""), e.get("ev", ""), rest))
    return 0


def cmd_view(args) -> int:
    from .viewer import write_static

    repo = _repo(args)
    out = Path(args.out) if args.out else repo.dir / "view.html"
    write_static(repo, out)
    print("Wrote %s" % out)
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_serve(args) -> int:
    from .viewer import serve

    return serve(_repo(args), args.port, open_browser=args.open)


def cmd_mcp(args) -> int:
    from .mcp_server import serve

    return serve(args.root)


def cmd_hook(args) -> int:
    from .hooks import main as hook_main

    return hook_main(args.agent)


# ---- parser ------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="thinspec",
        description="Keep a system's abstraction small, visible and honest while agents write the code.",
    )
    p.add_argument("--version", action="version", version="thinspec %s" % __version__)
    p.add_argument("--root", help="repo to act on (default: found from the current directory)")
    p.add_argument("--session", help="the agent session this command is for, when no hook or environment says "
                                     "(e.g. a cloud session working through a remote shell)")
    p.add_argument("--agent", help="the agent of --session, shown in the sessions list (e.g. claude-cloud)")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("init", help="set up ThinSpec in this repo and wire it into Claude Code")
    s.add_argument("--no-claude", action="store_true", help="skip the Claude Code hooks, MCP entry and skill")
    s.add_argument("--codex", action="store_true",
                   help="also wire ThinSpec into Codex: .codex/hooks.json, the MCP server in .codex/config.toml, the rules")
    s.add_argument("--agents-md", action="store_true",
                   help="also add the protocol to AGENTS.md, for agents without hooks (Codex, Cursor, ...)")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("status", help="the graph at a glance: one line per design, then the open tasks")
    s.add_argument("--full", action="store_true", help="also print every invariant and ban")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("state", help="everything as JSON, for editor panes and scripts")
    s.add_argument("--json", action="store_true", help="accepted for clarity; the output is always JSON")
    s.add_argument("--session", help="the id of the session asking, to mark it among the sessions")
    s.set_defaults(fn=cmd_state)

    s = sub.add_parser("show", help="show one node (with the rules above it) or one task")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)

    sub.add_parser("check", help="validate the graph and its size caps").set_defaults(fn=cmd_check)

    s = sub.add_parser("node", help="add, rename or retire a node of the abstraction")
    node_sub = s.add_subparsers(dest="node_command")
    a = node_sub.add_parser("add", help="create a node file")
    a.add_argument("id")
    a.add_argument("--parent", help="parent node id (omit for the root)")
    a.add_argument("--kind", choices=["design", "component"],
                   help="design (the default): a decision that sets the direction. component: a part of the "
                        "system that carries designs out, under the design it serves")
    a.add_argument("--title")
    a.add_argument("--summary")
    a.add_argument("--invariant", action="append", help="an invariant; repeat for several")
    a.set_defaults(fn=cmd_node_add)
    a = node_sub.add_parser("rename", help="give a node a new id; its tasks and its kept versions follow")
    a.add_argument("id")
    a.add_argument("new_id")
    a.set_defaults(fn=cmd_node_rename)
    a = node_sub.add_parser("move", help="put a node under another one, as when it holds more generally than "
                                         "where it sits; the nodes next to it are then owed a verification")
    a.add_argument("id")
    a.add_argument("--under", required=True, help="the node it should sit under")
    a.add_argument("--reason", required=True, help="what showed that it belongs there")
    a.set_defaults(fn=cmd_node_move)
    a = node_sub.add_parser("digest", help="rewrite sections of a node's digest: the few lines a person reads "
                                           "in place of its tasks; a section given replaces what was there")
    a.add_argument("id")
    a.add_argument("--feature", action="append", help="what the node can do now; repeat for several")
    a.add_argument("--as-built", action="append", dest="as_built",
                   help="where what is built departs from the node's story, and why")
    a.add_argument("--revert", action="append", help="what was tried and turned back, and why")
    a.add_argument("--positive", action="append", help="what a run of an experiment showed, for")
    a.add_argument("--negative", action="append", help="what a run of an experiment showed, against")
    a.set_defaults(fn=cmd_node_digest)
    a = node_sub.add_parser("retire", help="take a node out of the graph; its text is kept and its tasks move")
    a.add_argument("id")
    a.add_argument("--reason", required=True, help="where its idea went")
    a.add_argument("--into", help="the node its tasks move to (needed when it has tasks)")
    a.set_defaults(fn=cmd_node_retire)

    s = sub.add_parser("revise", help="keep a node's current text before rewriting it; with --decision, as a new version")
    s.add_argument("node")
    s.add_argument("--reason", required=True, help="what was learned that the old design missed")
    s.add_argument("--task", help="the task that triggered the revision")
    s.add_argument("--decision", action="store_true",
                   help="the decision changed (a rule added, dropped or reversed, or a step back): the version goes up")
    s.set_defaults(fn=cmd_revise)

    s = sub.add_parser("verify", help="list the nodes owed a verification (after a round of work under them, or "
                                      "a change to a node next to them), or record one as still fitting")
    s.add_argument("node", nargs="?", help="the node that was verified (leave out to list what is owed)")
    s.add_argument("--note", help="why it still fits the work under it and the nodes next to it")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("restore", help="switch a node back to an earlier version's text, as a new version")
    s.add_argument("node")
    s.add_argument("--to", type=int, help="the version to bring back (default: the one before the current)")
    s.add_argument("--reason", help="why the newer text is being dropped")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("ban", help="add an approach to a node's ban list")
    s.add_argument("node")
    s.add_argument("text", help="the approach never to take again")
    s.add_argument("--reason")
    s.add_argument("--task")
    s.set_defaults(fn=cmd_ban)

    s = sub.add_parser("task", help="plan, start, close and decide tasks")
    task_sub = s.add_subparsers(dest="task_command")

    a = task_sub.add_parser("add", help="plan a task under a design (ready to delegate once it has a check)")
    a.add_argument("--parent", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--check", required=True, help="how the task is verified")
    a.add_argument("--check-cmd", help="exact command that runs the check; each run counts as a trial")
    a.add_argument("--major", action="store_true", help="require three independent review passes before closing")
    _add_budget(a)
    a.set_defaults(fn=cmd_task_add)

    a = task_sub.add_parser("start", help="start a planned task, or plan and start a new one")
    a.add_argument("task", nargs="?")
    a.add_argument("--parent")
    a.add_argument("--title")
    a.add_argument("--check")
    a.add_argument("--check-cmd")
    a.add_argument("--major", action="store_true", help="require three independent review passes before closing")
    _add_budget(a)
    a.set_defaults(fn=cmd_task_start)

    a = task_sub.add_parser("trial", help="record one run of the check by hand")
    a.add_argument("task")
    g = a.add_mutually_exclusive_group()
    g.add_argument("--pass", dest="passed", action="store_true")
    g.add_argument("--fail", dest="failed", action="store_true")
    a.add_argument("--note")
    a.set_defaults(fn=cmd_task_trial)

    a = task_sub.add_parser("patch", help="record file edits by hand")
    a.add_argument("task")
    a.add_argument("-n", type=int, default=1)
    a.add_argument("--lines", type=int, default=0, help="lines those edits changed")
    a.set_defaults(fn=cmd_task_patch)

    a = task_sub.add_parser("budget", help="set a task's budget to your own numbers; it is then yours, not a guess")
    a.add_argument("task")
    a.add_argument("--note", help="what the numbers rest on")
    _add_budget(a)
    a.set_defaults(fn=cmd_task_budget)

    a = task_sub.add_parser("done", help="close a task whose check passes")
    a.add_argument("task")
    a.add_argument("--result", help="the measured result")
    a.add_argument("--drop", action="append", metavar="CHECK",
                   help="close without an earlier check under the design, as listed (with --why)")
    a.add_argument("--why", action="append", help="why the check given with --drop no longer applies")
    a.set_defaults(fn=cmd_task_done)

    a = task_sub.add_parser("metric", help="a metric added to a task's check: add one, record none missing, "
                                           "or, as the person, reword or drop one the agent added")
    a.add_argument("task")
    a.add_argument("--add", metavar="METRIC", help="add a metric to the check")
    a.add_argument("--none", action="store_true", help="record that no metric is missing")
    a.add_argument("--note", help="why")
    a.add_argument("--reword", nargs="+", metavar=("N", "TEXT"), help="reword added metric N (it is then yours)")
    a.add_argument("--drop", metavar="N", help="drop added metric N")
    a.set_defaults(fn=cmd_task_metric)

    a = task_sub.add_parser("review", help="record an independent review of a major task")
    a.add_argument("task")
    a.add_argument("verdict", choices=["pass", "changes-requested"])
    a.add_argument("--note", required=True, help="evidence or changes needed")
    a.set_defaults(fn=cmd_task_review)

    s = sub.add_parser("run", help="run a check for a task and record it (for agents whose runs no hook sees)")
    s.add_argument("task")
    s.add_argument("command", nargs=argparse.REMAINDER, help="-- then the command, as the task or earlier work ran it")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("sync", help="record the files changed since the last sync (for agents whose edits no hook sees)")
    s.add_argument("--task", help="the task to count them on (default: this session's open task)")
    s.set_defaults(fn=cmd_sync)

    s = sub.add_parser("inbox", help="what your person said or decided in the viewer since you last read")
    s.add_argument("--peek", action="store_true", help="show it without marking it read")
    s.set_defaults(fn=cmd_inbox)

    s = sub.add_parser("say", help="leave a message for the agent (what the viewer's message box does)")
    s.add_argument("text", nargs="+")
    s.add_argument("--node", help="the design or component it is about")
    s.add_argument("--task", help="the task it is about")
    s.set_defaults(fn=cmd_say)

    s = sub.add_parser("compare", help="run old and new implementations on the same fixtures and compare stdout")
    s.add_argument("--baseline", required=True, help="command to run the old implementation")
    s.add_argument("--candidate", required=True, help="command to run the new implementation")
    s.add_argument("--fixture", action="append", required=True, help="input file to feed both commands on stdin, repeatable")
    s.add_argument("--timeout", type=float, default=30, help="seconds for each command on each fixture")
    s.set_defaults(fn=cmd_compare)

    a = task_sub.add_parser("decide", help="your call on a task: extend, step-back, ban or abandon")
    a.add_argument("task")
    a.add_argument("choice", choices=["extend", "step-back", "step_back", "ban", "abandon"])
    a.add_argument("--note", help="the reason")
    a.add_argument("--text", help="for ban: the approach never to take again")
    _add_budget(a)
    a.set_defaults(fn=cmd_task_decide)

    task_sub.add_parser("list", help="list all tasks").set_defaults(fn=cmd_task_list)

    s = sub.add_parser("log", help="recent design-level events from the ledger")
    s.add_argument("-n", type=int, default=20)
    s.add_argument("--all", action="store_true", help="include every patch, trial and time entry")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("view", help="write the graph viewer as one HTML file")
    s.add_argument("--out", help="output file (default: .thinspec/view.html)")
    s.add_argument("--open", action="store_true", help="open it in the browser")
    s.set_defaults(fn=cmd_view)

    s = sub.add_parser("serve", help="serve the viewer locally; it refreshes as work happens")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open it in the browser")
    s.set_defaults(fn=cmd_serve)

    sub.add_parser("mcp", help="run the MCP server on stdio (for agents)").set_defaults(fn=cmd_mcp)
    s = sub.add_parser("hook", help="handle one hook event from stdin (Claude Code's shape)")
    s.add_argument("--agent", default="claude-code", help="the agent whose hooks call this (default: claude-code)")
    s.set_defaults(fn=cmd_hook)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "fn", None):
        parser.print_help()
        return 2
    _USED.clear()
    try:
        code = int(args.fn(args) or 0)
        if args.fn not in (cmd_inbox,) and _USED:
            from .remote import inbox_notice

            note = inbox_notice(_USED[-1])
            if note:
                print(note, file=sys.stderr)
        return code
    except ThinSpecError as exc:
        print("thinspec: %s" % exc, file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
