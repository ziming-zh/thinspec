import io
import json
import sys

import pytest

from thinspec import hooks
from thinspec.config import CONFIG_FILE, STATE_DIR
from thinspec.core import Repo

SID = "sess-1"


def set_cfg(repo, **kw):
    path = repo.dir / CONFIG_FILE
    cfg = json.loads(path.read_text())
    cfg.update(kw)
    path.write_text(json.dumps(cfg))


def ev(repo, event, tool=None, tool_input=None, sid=SID, now=None, mode=None):
    payload = {"hook_event_name": event, "session_id": sid, "cwd": str(repo.root)}
    if mode:
        payload["permission_mode"] = mode
    if tool:
        payload["tool_name"] = tool
        payload["tool_input"] = tool_input or {}
    return hooks.handle(payload, now=now)


def decision(out):
    return out["hookSpecificOutput"]["permissionDecision"] if out else None


def context(out):
    return out["hookSpecificOutput"]["additionalContext"] if out else None


def edit(repo, path="src/hooks.py", event="PreToolUse", now=None, sid=SID):
    return ev(repo, event, "Edit", {"file_path": str(repo.root / path), "old_string": "a\nb", "new_string": "c"},
              sid=sid, now=now)


def bash(repo, cmd, event="PreToolUse", now=None):
    return ev(repo, event, "Bash", {"command": cmd}, now=now)


START = {"parent": "instrument", "title": "Hook backward ops", "check": "hooks match", "trials": 2, "patches": 5}


def start_via_mcp(repo, args=START, sid=SID, now=None, reviewed=True):
    """What Claude Code does around an MCP task_start call: pre hook, the call, post hook."""
    pre = ev(repo, "PreToolUse", "mcp__thinspec__task_start", args, sid=sid, now=now)
    from thinspec.mcp_server import call_tool

    server = Repo(repo.root)
    server.actor = sid               # Claude Code gives its MCP servers the session id its hooks carry
    call_tool(server, "task_start", args)
    ev(repo, "PostToolUse", "mcp__thinspec__task_start", args, sid=sid, now=now)
    task = server.task(args.get("task") or list(server.state().tasks)[-1])
    if reviewed and task.check_review_pending:
        call_tool(server, "task_metric", {"task": task.id, "none": True})
    return pre


def test_outside_an_thinspec_repo_the_hook_stays_silent(tmp_path):
    out = hooks.handle({"hook_event_name": "PreToolUse", "cwd": str(tmp_path), "tool_name": "Edit",
                        "tool_input": {"file_path": str(tmp_path / "a.py")}})
    assert out is None


def test_session_start_explains_the_protocol_and_shows_the_graph(repo):
    text = context(ev(repo, "SessionStart"))
    assert "task_start" in text and "instrument" in text and "One unique hook point per step." in text


def test_nudge_refuses_the_first_untracked_edit_once(repo):
    first = edit(repo)
    assert decision(first) == "deny" and "task_start" in first["hookSpecificOutput"]["permissionDecisionReason"]
    assert edit(repo) is None                                # second try goes through
    edit(repo, event="PostToolUse")
    assert repo.state().untracked_patches == 1


def test_strict_gate_refuses_every_untracked_edit_and_off_refuses_none(repo):
    set_cfg(repo, gate="strict")
    assert decision(edit(repo)) == "deny" and decision(edit(repo)) == "deny"
    set_cfg(repo, gate="off")
    assert edit(repo, sid="other") is None


def test_by_default_a_budget_goes_ahead_and_the_agent_is_told_to_report_it(repo):
    from thinspec.mcp_server import call_tool

    assert ev(repo, "PreToolUse", "mcp__thinspec__task_start", START) is None   # nothing waits for an approval
    call_tool(Repo(repo.root), "task_start", START)
    note = context(ev(repo, "PostToolUse", "mcp__thinspec__task_start", START))
    assert "went ahead without asking" in note and "2 trials, 5 patches" in note and "when this turn ends" in note
    task = repo.task("T1")
    assert task.status == "active" and task.set_by == "agent" and not task.confirmed

    # Said once a turn, however many changes follow. The next turn owes its own report.
    assert edit(repo, "abstraction/instrument.md") is None
    assert context(edit(repo, "abstraction/instrument.md", event="PostToolUse")) is None
    ev(repo, "Stop")
    edit(repo, "abstraction/instrument.md")
    again = context(edit(repo, "abstraction/instrument.md", event="PostToolUse"))
    assert "changed abstraction/instrument.md" in again and "history/" in again


def test_a_project_that_asks_for_approvals_is_asked_about_the_budget(repo):
    set_cfg(repo, approvals="ask")
    pre = start_via_mcp(repo)
    assert decision(pre) == "ask"
    reason = pre["hookSpecificOutput"]["permissionDecisionReason"]
    assert "2 trials" in reason and "5 patches" in reason and "instrument" in reason
    task = repo.task("T1")
    assert task.status == "active" and task.set_by == "agent" and task.confirmed


def test_no_budget_prompt_when_disabled_or_when_the_human_planned_it(repo):
    set_cfg(repo, approvals="ask")
    tid = repo.plan_task("instrument", "Planned by me", "c", budget={"trials": 3}, set_by="user")
    assert ev(repo, "PreToolUse", "mcp__thinspec__task_start", {"task": tid}) is None
    # an agent trying to change that budget is asked about again
    assert decision(ev(repo, "PreToolUse", "mcp__thinspec__task_start", {"task": tid, "trials": 30})) == "ask"
    set_cfg(repo, confirm_budget=False)
    assert ev(repo, "PreToolUse", "mcp__thinspec__task_start", START) is None


def test_edits_and_check_runs_are_counted_against_the_active_task(repo):
    start_via_mcp(repo)
    assert edit(repo) is None                                # a task is active: no nudge
    edit(repo, event="PostToolUse")
    bash(repo, "ls -la", event="PostToolUse")                # not a check run
    bash(repo, "python -m pytest tests/ -x", event="PostToolUse")
    bash(repo, "pytest -q", event="PostToolUseFailure")      # a failing run still counts
    task = repo.task("T1")
    assert (task.patches, task.lines, task.trials, task.failed) == (1, 2, 2, 1)
    assert task.files == {"src/hooks.py"}


def test_a_task_with_its_own_check_command_counts_only_that_command(repo):
    start_via_mcp(repo, dict(START, check_cmd="make  bench"))
    bash(repo, "pytest -q", event="PostToolUse")
    bash(repo, "cd build && make bench WORKLOAD=b", event="PostToolUse")
    assert repo.task("T1").trials == 1


def test_check_review_and_all_paths_of_a_hook_edit_are_checked_before_work(repo):
    owner = repo.node("instrument").path
    owner.write_text(owner.read_text().replace("\n---\n", "\nmodule: src/instrument\n---\n", 1))
    repo.add_node("probe", "Probe", "instrument", "Observe a step.", ["Count each step once."], kind="component")
    start_via_mcp(repo, dict(START, parent="probe"), reviewed=False)
    assert decision(edit(repo, "src/instrument/probe.py")) == "deny"
    assert "cheapest way to pass" in bash(repo, "pytest -q")["hookSpecificOutput"]["permissionDecisionReason"]
    assert ev(repo, "PreToolUse", "Read", {"file_path": str(owner)}) is None

    repo.add_metric("T1", "one hook on each workload")
    assert edit(repo, "src/instrument/probe.py") is None
    assert bash(repo, "pytest -q") is None
    patch = "*** Begin Patch\n*** Add File: src/instrument/a.py\n+x\n*** Add File: src/other.py\n+y\n*** End Patch"
    denied = ev(repo, "PreToolUse", "apply_patch", {"command": patch})
    assert decision(denied) == "deny" and "src/other.py" in denied["hookSpecificOutput"]["permissionDecisionReason"]
    move = "*** Begin Patch\n*** Update File: src/other.py\n*** Move to: src/instrument/a.py\n@@\n-x\n+y\n*** End Patch"
    assert decision(ev(repo, "PreToolUse", "apply_patch", {"command": move})) == "deny"


def test_reaching_the_estimate_stops_nothing_and_far_past_it_pauses(repo):
    start_via_mcp(repo)                                      # 5 patches, 2 trials
    notes = []
    for _ in range(10):
        assert edit(repo) is None                            # nothing is refused up to twice the estimate
        notes.append(context(edit(repo, event="PostToolUse")))
    assert notes[:4] == [None] * 4
    assert "reached its patches estimate" in notes[4] and "stops nothing" in notes[4]   # 5 of 5
    assert notes[5:] == [None] * 5                           # said once
    assert repo.task("T1").status == "active"                # 10 of 5: at the line, nothing refused yet

    stop = edit(repo)                                        # the 11th edit is past twice the estimate
    assert decision(stop) == "deny"
    reason = stop["hookSpecificOutput"]["permissionDecisionReason"]
    assert "10/5 patches" in reason and "One unique hook point per step." in reason and "task_decide" in reason
    task = repo.task("T1")
    assert task.status == "blocked" and task.alarms[0]["exhausted"] == ["patches"]

    assert decision(bash(repo, "pytest -q")) == "deny"       # check runs pause too
    assert bash(repo, "git status") is None                  # looking around does not
    assert decision(edit(repo)) == "deny"
    assert len(repo.task("T1").alarms) == 1                  # one alarm, however often it is hit


def test_check_runs_follow_the_same_line_and_the_line_is_a_setting(repo):
    set_cfg(repo, alarm_ratio=1.5)
    start_via_mcp(repo)                                      # 2 trials, so the line is at 3
    for _ in range(3):
        assert bash(repo, "pytest -q") is None
        bash(repo, "pytest -q", event="PostToolUseFailure")
    assert decision(bash(repo, "pytest -q")) == "deny"       # the 4th run
    assert repo.task("T1").alarms[0]["exhausted"] == ["trials"]


def test_extending_reopens_the_task_and_the_new_estimate_is_noted_afresh(repo):
    start_via_mcp(repo)
    for _ in range(10):
        edit(repo, event="PostToolUse")
    assert decision(edit(repo)) == "deny"
    args = {"task": "T1", "choice": "extend", "patches": 10, "note": "right approach"}
    assert decision(ev(repo, "PreToolUse", "mcp__thinspec__task_decide", args)) == "ask"
    repo.decide("T1", "extend", extend={"patches": 10})
    ev(repo, "PostToolUse", "mcp__thinspec__task_decide", args)
    assert edit(repo) is None                                # 10 of 15: under the new estimate
    notes = [context(edit(repo, event="PostToolUse")) for _ in range(5)]
    assert notes[:4] == [None] * 4 and "reached its patches estimate" in notes[4]   # 15 of 15


def test_closing_a_task_frees_the_session(repo):
    start_via_mcp(repo)
    repo.done_task("T1", "ok")
    ev(repo, "PostToolUse", "mcp__thinspec__task_done", {"task": "T1", "result": "ok"})
    set_cfg(repo, gate="strict")
    assert decision(edit(repo)) == "deny"                    # no task again


def test_where_approvals_are_asked_abstraction_edits_need_one_and_are_never_patches(repo):
    set_cfg(repo, approvals="ask")
    start_via_mcp(repo)
    out = edit(repo, "abstraction/instrument.md")
    assert decision(out) == "ask" and "abstraction/instrument.md" in out["hookSpecificOutput"]["permissionDecisionReason"]
    edit(repo, "abstraction/instrument.md", event="PostToolUse")
    events = [e for e in repo.ledger.events() if e["ev"] == "abstraction_edited"]
    assert events[0]["node"] == "instrument" and repo.task("T1").patches == 0
    set_cfg(repo, protect_abstraction=False)
    assert edit(repo, "abstraction/instrument.md") is None


def test_the_record_cannot_be_edited_or_overwritten(repo):
    assert decision(edit(repo, ".thinspec/ledger.jsonl")) == "deny"
    assert decision(bash(repo, "echo '{}' > .thinspec/ledger.jsonl")) == "deny"
    assert decision(bash(repo, "rm -rf .thinspec")) == "deny"
    assert decision(bash(repo, "sed -i '' 's/4/40/' .thinspec/ledger.jsonl")) == "deny"
    assert bash(repo, "cat .thinspec/ledger.jsonl | tail -3") is None
    assert bash(repo, 'git add .thinspec/ && git commit -m "v1 -> v2"') is None   # committing it is fine


def test_the_project_root_is_found_even_after_the_agent_changes_directory(repo, tmp_path_factory, monkeypatch):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    payload = {"hook_event_name": "PreToolUse", "session_id": SID, "cwd": str(elsewhere), "tool_name": "Edit",
               "tool_input": {"file_path": str(repo.root / ".thinspec" / "config.json")}}
    monkeypatch.chdir(elsewhere)
    assert hooks.handle(payload) is None                       # nothing points at the repo
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo.root))
    assert decision(hooks.handle(payload)) == "deny"


def test_from_the_shell_a_verdict_goes_to_the_human_and_other_changes_only_where_approvals_are_asked(repo):
    changes = ("thinspec revise core --reason x", "thinspec restore core", "cd . && thinspec ban core 'x'",
               "thinspec node rename instrument hooks", "thinspec node retire instrument --reason x",
               "thinspec task start --parent core --title t --check c --trials 99")
    assert decision(bash(repo, "thinspec task decide T1 extend --trials 9")) == "ask"
    for cmd in changes:
        assert bash(repo, cmd) is None, cmd                  # they go ahead, and are reported
    set_cfg(repo, approvals="ask")
    for cmd in changes:
        assert decision(bash(repo, cmd)) == "ask", cmd
    for cmd in ("thinspec status", "thinspec task list", "thinspec view"):
        assert bash(repo, cmd) is None, cmd


def test_a_session_set_to_bypass_permissions_is_never_asked(repo):
    set_cfg(repo, approvals="ask")
    by = "bypassPermissions"
    assert ev(repo, "PreToolUse", "mcp__thinspec__task_start", START, mode=by) is None
    assert ev(repo, "PreToolUse", "mcp__thinspec__node_revise", {"node": "core", "reason": "x"}, mode=by) is None
    assert ev(repo, "PreToolUse", "mcp__thinspec__task_decide", {"task": "T1", "choice": "extend"}, mode=by) is None
    assert ev(repo, "PreToolUse", "Edit", {"file_path": str(repo.root / "abstraction/core.md")}, mode=by) is None
    assert ev(repo, "PreToolUse", "Bash", {"command": "thinspec task decide T1 ban"}, mode=by) is None
    # The record itself stays out of reach in every mode.
    record = {"file_path": str(repo.root / ".thinspec/ledger.jsonl")}
    assert decision(ev(repo, "PreToolUse", "Edit", record, mode=by)) == "deny"


def test_edits_outside_the_repo_are_ignored(repo, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere") / "x.py"
    out = ev(repo, "PreToolUse", "Write", {"file_path": str(other), "content": "x"})
    assert out is None
    ev(repo, "PostToolUse", "Write", {"file_path": str(other), "content": "x"})
    assert repo.state().untracked_patches == 0


def test_time_counts_tool_runs_in_full_and_caps_idle_gaps(repo):
    t = 1_800_000_000.0
    start_via_mcp(repo, dict(START, minutes=600), now=t)
    bash(repo, "pytest -q", now=t)                           # no time has passed yet
    bash(repo, "pytest -q", event="PostToolUse", now=t + 1200)   # a 20-minute run counts in full
    edit(repo, now=t + 1200 + 40)                            # 40 s of thinking counts
    edit(repo, event="PostToolUse", now=t + 1200 + 41)
    ev(repo, "Stop", now=t + 1200 + 45)
    assert repo.task("T1").seconds == pytest.approx(1245, abs=1)
    edit(repo, now=t + 90000)                                # next turn, a day later: the wait is not work
    edit(repo, event="PostToolUse", now=t + 90001)
    edit(repo, now=t + 90001 + 4000)                         # a long gap inside a turn is capped at 300 s
    ev(repo, "Stop", now=t + 90001 + 4000)
    assert repo.task("T1").seconds == pytest.approx(1245 + 1 + 300, abs=1)


def test_waiting_for_the_humans_approval_is_not_counted_as_a_tool_run(repo):
    set_cfg(repo, approvals="ask")
    t = 1_800_000_000.0
    start_via_mcp(repo, dict(START, minutes=600), now=t)
    edit(repo, now=t)
    edit(repo, "abstraction/core.md", now=t + 10)            # returns "ask"
    edit(repo, "abstraction/core.md", event="PostToolUse", now=t + 10 + 3600)   # approved an hour later
    ev(repo, "Stop", now=t + 10 + 3600)
    assert repo.task("T1").seconds == pytest.approx(10 + 300, abs=1)


def test_time_far_past_the_estimate_pauses_work_too(repo):
    t = 1_800_000_000.0
    start_via_mcp(repo, {"parent": "instrument", "title": "Timed", "check": "c", "minutes": 2}, now=t)
    bash(repo, "sleep 150", now=t)
    note = context(bash(repo, "sleep 150", event="PostToolUse", now=t + 150))
    assert "reached its minutes estimate" in note            # 2.5 of 2 minutes
    assert edit(repo, now=t + 151) is None                   # past the estimate, and still working
    edit(repo, event="PostToolUse", now=t + 152)
    bash(repo, "sleep 120", now=t + 153)
    bash(repo, "sleep 120", event="PostToolUse", now=t + 273)    # 4.5 of 2 minutes
    assert decision(edit(repo, now=t + 274)) == "deny"
    assert repo.task("T1").alarms[0]["exhausted"] == ["minutes"]


def test_two_sessions_each_count_against_their_own_task(repo):
    start_via_mcp(repo, sid="A")
    start_via_mcp(repo, dict(START, title="Other task"), sid="B")
    edit(repo, event="PostToolUse", sid="A")
    edit(repo, event="PostToolUse", sid="B")
    edit(repo, event="PostToolUse", sid="B")
    assert (repo.task("T1").patches, repo.task("T2").patches) == (1, 2)
    edit(repo, event="PostToolUse", sid="C")                 # a third session, two open tasks: untracked
    assert repo.state().untracked_patches == 1


def test_a_lone_open_task_is_used_by_any_session(repo):
    repo.start_task(parent="instrument", title="Started in the terminal", check="c", budget={"patches": 3},
                    set_by="user")
    assert edit(repo, sid="fresh") is None
    edit(repo, event="PostToolUse", sid="fresh")
    assert repo.task("T1").patches == 1


def test_main_never_fails_and_prints_only_json(repo, monkeypatch, capsys):
    monkeypatch.chdir(repo.root)     # the error is logged where the hook runs, not in the repo under test
    monkeypatch.setattr(sys, "stdin", io.StringIO("this is not json"))
    assert hooks.main() == 0 and capsys.readouterr().out == ""
    payload = {"hook_event_name": "PreToolUse", "session_id": "s", "cwd": str(repo.root),
               "tool_name": "Edit", "tool_input": {"file_path": str(repo.root / ".thinspec/config.json")}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert hooks.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_an_internal_error_is_logged_not_raised(repo, monkeypatch, capsys):
    monkeypatch.setattr(hooks, "handle", lambda payload, **kw: 1 / 0)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(repo.root)})))
    assert hooks.main() == 0 and capsys.readouterr().out == ""
    assert "ZeroDivisionError" in (repo.root / STATE_DIR / "hook-errors.log").read_text()


def test_a_long_spec_does_not_push_the_open_work_and_the_sessions_out_of_the_session_start(repo):
    small = context(ev(repo, "SessionStart", sid="B"))
    assert "invariant: One unique hook point per step." in small          # a small spec is given whole

    wordy = "This rule is long enough that a few dozen like it do not fit in what a session start may add. " * 2
    for i in range(4):
        repo.add_node("design-%d" % i, "Decide number %d" % i, "core", "x", [wordy + str(n) for n in range(12)])
    repo.add_ban("design-3", "Global locks", "too slow")
    start_via_mcp(repo, sid="A")
    edit(repo, event="PostToolUse", sid="A")
    repo.plan_task("design-0", "Planned for later", "c")
    assert len(hooks.PROTOCOL + repo.overview_text()) > hooks.START_LIMIT   # the whole of it does not fit

    text = context(ev(repo, "SessionStart", sid="B"))
    assert len(text) <= hooks.START_LIMIT
    assert "invariant:" not in text and "The invariants are left out here" in text and "overview tool" in text
    assert "banned: Global locks" in text                                 # a ban is never left out
    for kept in ('"Decide number 3"', "Active tasks:", "Planned, ready to delegate:", '"Planned for later"',
                 "Sessions, working in parallel", 'claude-code A: T1 "Hook backward ops"'):
        assert kept in text, kept


# ---- budgets in runs and lines ------------------------------------------

def test_the_lines_an_edit_changes_count_against_a_budget_in_lines(repo):
    start_via_mcp(repo, {"parent": "instrument", "title": "Small fix", "check": "c", "trials": 2, "lines": 3})
    assert edit(repo) is None
    edit(repo, event="PostToolUse")                          # each of these edits changes two lines: 2 of 3
    note = context(edit(repo, event="PostToolUse"))          # 4 of 3: the estimate is reached, and nothing stops
    assert "reached its lines estimate" in note and "4/3 lines" in note
    assert edit(repo) is None
    edit(repo, event="PostToolUse")                          # 6 of 3: twice the estimate
    stop = edit(repo)
    assert decision(stop) == "deny" and "far past its estimate" in stop["hookSpecificOutput"]["permissionDecisionReason"]
    assert repo.task("T1").alarms[0]["exhausted"] == ["lines"]


def test_the_persons_numbers_replace_a_guess_through_the_tool(repo):
    from thinspec.mcp_server import call_tool

    start_via_mcp(repo, {"parent": "instrument", "title": "Debug the kernel", "check": "boots 20 times in a row",
                         "trials": 3, "confidence": "low"})
    assert repo.task("T1").guess
    answer = {"task": "T1", "trials": 25, "lines": 400}
    assert ev(repo, "PreToolUse", "mcp__thinspec__task_budget", answer) is None      # nothing waits for an approval
    server = Repo(repo.root)
    server.actor = SID
    call_tool(server, "task_budget", answer)
    ev(repo, "PostToolUse", "mcp__thinspec__task_budget", answer)
    task = repo.task("T1")
    assert (task.budget, task.set_by, task.guess) == ({"trials": 25, "lines": 400}, "user", False)

    set_cfg(repo, approvals="ask")                           # a project that asks first is asked about this too
    assert decision(ev(repo, "PreToolUse", "mcp__thinspec__task_budget", answer)) == "ask"
    assert decision(bash(repo, "thinspec task budget T1 --trials 9")) == "ask"


def test_the_session_is_told_to_budget_in_runs_and_lines_and_to_ask_when_unsure(repo):
    text = context(ev(repo, "SessionStart"))
    assert "trials (how many runs of the check until the result is solid)" in text and "Time is measured, never budgeted" in text
    assert 'confidence "low"' in text and "Do not wait for the answer" in text and "task_budget" in text
    assert "minutes of active work" not in text and "patches = file edits" not in text
    refused = edit(repo)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "trials (runs of the check until the result is solid) and lines" in refused and "minutes" not in refused


# ---- parallel sessions -------------------------------------------------

def test_a_session_is_put_in_the_record_the_first_time_it_works(repo):
    assert context(ev(repo, "SessionStart", sid="A")) and repo.state().sessions == {}     # reading is not working
    start_via_mcp(repo, sid="A")
    edit(repo, event="PostToolUse", sid="A")
    known = repo.state().sessions["A"]
    assert (known.agent, known.dir, known.task) == ("claude-code", repo.root.name, "T1") and known.host
    assert sum(1 for e in repo.ledger.events() if e.get("ev") == "session") == 1
    hooks.handle({"hook_event_name": "PostToolUse", "session_id": "X", "cwd": str(repo.root),
                  "tool_name": "Read", "tool_input": {}}, agent="codex")     # another agent's hooks, same shape
    assert repo.state().sessions["X"].agent == "codex"


def test_a_session_with_no_task_leaves_a_task_another_session_holds(repo):
    import time

    start_via_mcp(repo, sid="A")
    edit(repo, event="PostToolUse", sid="A")
    refused = edit(repo, sid="C")                            # the only open task, but A holds it
    reason = refused["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(refused) == "deny" and "claude-code A: T1" in reason and "join it by name" in reason
    edit(repo, event="PostToolUse", sid="C")
    assert repo.task("T1").patches == 1 and repo.state().untracked_patches == 1

    start_via_mcp(repo, {"task": "T1"}, sid="C")             # C joins by name: now its edits count there
    edit(repo, event="PostToolUse", sid="C")
    assert repo.task("T1").patches == 2 and list(repo.task("T1").sessions) == ["A", "C"]

    later = time.time() + 3600                               # an hour on, A and C are quiet: T1 can be picked up
    assert edit(repo, sid="D", now=later) is None
    edit(repo, event="PostToolUse", sid="D", now=later + 1)
    assert repo.task("T1").patches == 3


def test_the_other_sessions_are_named_when_a_session_starts(repo):
    start_via_mcp(repo, sid="A")
    edit(repo, event="PostToolUse", sid="A")
    ev(repo, "Stop", sid="A")                                # A's turn is over: it waits for its person
    text = context(ev(repo, "SessionStart", sid="B"))
    assert "Sessions, working in parallel" in text and 'claude-code A: T1 "Hook backward ops"' in text
    assert "Waiting for its person since" in text and "join it by name" in text
    edit(repo, sid="A")                                      # A's next turn: working again
    assert [(r["id"], r["state"]) for r in repo.sessions()] == [("A", "working")]


def test_an_edit_to_a_file_another_sessions_task_edited_is_said_once(repo):
    start_via_mcp(repo, sid="A")
    edit(repo, "src/shared.py", event="PostToolUse", sid="A")
    start_via_mcp(repo, dict(START, title="Other task"), sid="B")
    assert edit(repo, "src/shared.py", sid="B") is None      # it stops nothing
    note = context(edit(repo, "src/shared.py", event="PostToolUse", sid="B"))
    assert 'src/shared.py was also edited under T1 "Hook backward ops"' in note and "claude-code A" in note
    assert context(edit(repo, "src/shared.py", event="PostToolUse", sid="B")) is None     # once
    assert context(edit(repo, "src/own.py", event="PostToolUse", sid="B")) is None        # a file of its own
    assert context(edit(repo, "src/shared.py", event="PostToolUse", sid="A")) is not None  # and A hears of B


def test_a_turn_that_worked_under_two_tasks_puts_both_nodes_up_to_be_verified(repo):
    repo.add_node("replay", "Replay", "core", "Run a recorded step again.", ["holds"])
    start_via_mcp(repo)                                      # a task under 'instrument'
    edit(repo, event="PostToolUse")
    start_via_mcp(repo, dict(START, parent="replay", title="Replay a step"))   # the turn moves to another
    edit(repo, path="src/replay.py", event="PostToolUse")
    assert ev(repo, "Stop") is None
    assert {row["node"]: row["round"]["after"] for row in repo.to_verify()} == {"instrument": "work", "replay": "work"}
    note = context(bash(repo, "ls", event="PostToolUse"))
    assert "A round of work under 'instrument' ended" in note and "A round of work under 'replay' ended" in note
    assert bash(repo, "ls", event="PostToolUse") is None     # said once


def test_a_turn_of_work_under_a_task_puts_its_node_up_to_be_verified_and_the_agent_is_told_once(repo):
    start_via_mcp(repo)
    assert ev(repo, "Stop") is None                          # a turn with no work under the task
    assert repo.to_verify() == []

    edit(repo, event="PostToolUse")                          # the turn changes code under the task
    assert ev(repo, "Stop") is None                          # the round is recorded; nothing stops the agent
    tid = repo.state().open_tasks()[0].id
    assert repo.to_verify() == [{"node": "instrument", "since": [], "round": {"task": tid, "after": "work"}}]
    due = [e for e in repo.ledger.events() if e["ev"] == "verify_due"]
    assert len(due) == 1 and due[0]["session"] == SID

    note = context(bash(repo, "ls", event="PostToolUse"))    # its next tool call, in the next turn
    assert "verify the node against the work on %s" % tid in note and "node_verify" in note
    assert bash(repo, "ls", event="PostToolUse") is None     # said once
    assert ev(repo, "Stop") is None                          # no new work: nothing more is raised
    assert len([e for e in repo.ledger.events() if e["ev"] == "verify_due"]) == 1

    repo.verify("instrument", "Read against the edit: still one hook point per step.")
    assert repo.to_verify() == []
    edit(repo, event="PostToolUse")
    ev(repo, "Stop")
    repo.verify("instrument", "Read against the second edit as well.")
    assert context(bash(repo, "ls", event="PostToolUse")) is None    # verified before the next turn: not said


def test_a_run_of_an_earlier_check_is_recorded_as_a_check_run_not_a_trial(repo):
    old = repo.start_task(parent="instrument", title="v1", check="c", check_cmd="pytest tests/test_v1.py",
                          budget={"trials": 2}).id
    repo.done_task(old, "passed")
    start_via_mcp(repo, dict(START, check_cmd="pytest tests/test_v2.py"))
    tid = [t for t in repo.state().tasks.values() if t.status == "active"][0].id
    bash(repo, "cd src && pytest tests/test_v1.py -q", event="PostToolUse")
    task = repo.task(tid)
    assert task.trials == 0 and task.check_runs["pytest tests/test_v1.py"]["passed"] is True
    ev(repo, "PostToolUse", "Bash", {"command": "pytest tests/test_v1.py"}, sid=SID)
    payload = {"hook_event_name": "PostToolUse", "session_id": SID, "cwd": str(repo.root), "tool_name": "Bash",
               "tool_input": {"command": "pytest tests/test_v1.py"}, "tool_response": {"exit_code": 1}}
    hooks.handle(payload)                                   # Codex reports a failed command in its response
    assert repo.task(tid).check_runs["pytest tests/test_v1.py"]["passed"] is False


# ---- Codex: the same hooks, its own tool names --------------------------------------------

PATCH = """*** Begin Patch
*** Update File: src/cache.py
@@ def get(key):
-    return table.get(key)
+    entry = table.get(key)
+    return entry.value if entry else None
*** Add File: src/evict.py
+def pick():
+    return None
*** End Patch"""


def codex(repo, event, tool=None, tool_input=None, response=None, sid="codex-1"):
    payload = {"hook_event_name": event, "session_id": sid, "cwd": str(repo.root), "model": "gpt-5",
               "permission_mode": "default"}
    if tool:
        payload.update(tool_name=tool, tool_input=tool_input or {}, tool_use_id="call_1", turn_id="t1")
    if response is not None:
        payload["tool_response"] = response
    return hooks.handle(payload, agent="codex")


def codex_start(repo, args=START, sid="codex-1"):
    """What Codex does around an MCP task_start call. Its MCP server has no session id of the hooks'."""
    from thinspec.mcp_server import call_tool
    codex(repo, "PreToolUse", "mcp__thinspec__task_start", args, sid=sid)
    server = Repo(repo.root)
    call_tool(server, "task_start", args)
    codex(repo, "PostToolUse", "mcp__thinspec__task_start", args, sid=sid)
    task = server.task(args.get("task") or list(server.state().tasks)[-1])
    if task.check_review_pending:
        call_tool(server, "task_metric", {"task": task.id, "none": True})


def test_a_codex_patch_is_counted_per_file_against_the_task(repo):
    codex_start(repo)
    tid = [t for t in repo.state().tasks.values() if t.status == "active"][0].id
    assert codex(repo, "PreToolUse", "apply_patch", {"command": PATCH}) is None
    codex(repo, "PostToolUse", "apply_patch", {"command": PATCH}, response={"output": "Success"})
    task = repo.task(tid)
    assert (task.patches, task.lines, task.files) == (2, 4, {"src/cache.py", "src/evict.py"})
    assert repo.state().sessions["codex-1"].agent == "codex"


def test_a_codex_patch_into_the_record_is_refused_and_codex_is_never_asked_to_wait(repo):
    out = codex(repo, "PreToolUse", "apply_patch",
                {"command": "*** Begin Patch\n*** Update File: .thinspec/ledger.jsonl\n+x\n*** End Patch"})
    assert decision(out) == "deny"
    set_cfg(repo, protect_abstraction=True, approvals="ask")
    out = codex(repo, "PreToolUse", "apply_patch",
                {"command": "*** Begin Patch\n*** Update File: abstraction/core.md\n+x\n*** End Patch"})
    assert out is None                     # Codex cannot hold a call: it goes ahead and is reported instead
    out = codex(repo, "PostToolUse", "mcp__thinspec__ban_add", {"node": "core", "text": "x"})
    assert out is None or "deny" not in json.dumps(out)


def test_a_codex_command_that_exits_non_zero_is_a_failed_trial(repo):
    codex_start(repo, dict(START, check_cmd="pytest -q"))
    tid = [t for t in repo.state().tasks.values() if t.status == "active"][0].id
    codex(repo, "PostToolUse", "Bash", {"command": ["bash", "-lc", "pytest -q"]}, response={"exit_code": 1})
    codex(repo, "PostToolUse", "Bash", {"command": "pytest -q"}, response={"exit_code": 0})
    task = repo.task(tid)
    assert (task.trials, task.failed) == (2, 1)


def test_codex_session_start_gets_the_protocol_and_the_graph(repo):
    out = codex(repo, "SessionStart")
    assert "This repository uses ThinSpec" in context(out)
