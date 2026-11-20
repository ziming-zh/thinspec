import json
import shlex
import sys

from thinspec.cli import main
from thinspec.install import HOOK_COMMAND, init
from thinspec.viewer import build_data, render_html


def run(repo, *argv):
    return main(["--root", str(repo.root)] + list(argv))


def test_compare_replays_each_fixture_on_both_versions_and_reports_a_difference(repo, capsys):
    (repo.root / "old.py").write_text("import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read().upper())\n")
    candidate = repo.root / "new code.py"
    candidate.write_text("import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read().upper())\n")
    (repo.root / "workload A.txt").write_text("same")
    (repo.root / "workload B.txt").write_text("different")
    args = ("compare", "--baseline", shlex.join([sys.executable, "old.py"]), "--candidate",
            shlex.join([sys.executable, candidate.name]), "--fixture", "workload A.txt", "--fixture", "workload B.txt")
    assert run(repo, *args) == 0
    assert "2 matched, 0 differed" in capsys.readouterr().out
    candidate.write_text("import sys\nraw = sys.stdin.buffer.read()\nsys.stdout.buffer.write(raw if raw == b'different' else raw.upper())\n")
    assert run(repo, *args) == 1
    result = capsys.readouterr().out
    assert "workload A.txt: match" in result and "workload B.txt: outputs differ" in result
    assert "+different" in result and "1 matched, 1 differed" in result


def test_restore_switches_a_node_back_from_the_command_line(repo, capsys):
    assert run(repo, "revise", "instrument", "--decision", "--reason", "try another hook point") == 0
    assert run(repo, "restore", "instrument", "--reason", "it broke replay") == 0
    assert "holds the text of v1 again, as v3" in capsys.readouterr().out
    assert repo.node("instrument").version == 3
    assert run(repo, "restore", "core") == 1                 # nothing earlier to switch back to
    assert "no earlier version" in capsys.readouterr().err


def test_rename_and_retire_a_node_from_the_command_line(repo, capsys):
    assert run(repo, "node", "rename", "instrument", "hook-points") == 0
    assert "'instrument' is now 'hook-points'" in capsys.readouterr().out
    assert run(repo, "node", "rename", "hook-points", "agents") == 1     # a name an agent reads as instructions
    assert "cannot be a node id" in capsys.readouterr().err
    assert run(repo, "node", "retire", "hook-points", "--reason", "folded into the core") == 0
    assert "abstraction/history/hook-points.v1.md" in capsys.readouterr().out
    assert set(repo.nodes()) == {"core"}


def test_init_wires_claude_code_without_touching_existing_settings(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "./mine.sh"}]}]},
    }))
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    init(tmp_path)
    init(tmp_path)                                           # twice: must not duplicate
    settings = json.loads((claude / "settings.json").read_text())
    assert settings["permissions"] == {"allow": ["Bash(ls:*)"]}
    pre = settings["hooks"]["PreToolUse"]
    assert [h["hooks"][0]["command"] for h in pre] == ["./mine.sh", HOOK_COMMAND]
    assert set(settings["hooks"]) == {"SessionStart", "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop"}
    mcp = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]
    assert mcp["other"] == {"command": "x"} and mcp["thinspec"] == {"command": "thinspec", "args": ["mcp"]}
    # The agent's rules are a skill of their own name, kept out of the person's command menu:
    # /thinspec is the person's, and opens the graph.
    rules = (claude / "skills" / "thinspec-rules" / "SKILL.md").read_text()
    assert rules.startswith("---\nname: thinspec-rules\n") and "\nuser-invocable: false\n" in rules.split("---")[1]
    assert not (claude / "skills" / "thinspec").exists()
    assert (tmp_path / "abstraction" / "core.md").exists()


def test_init_removes_the_rules_it_once_wrote_as_the_skill_thinspec_and_no_one_elses(tmp_path):
    from thinspec.install import ASSETS

    skills = tmp_path / ".claude" / "skills"
    old = skills / "thinspec"
    old.mkdir(parents=True)
    # What an earlier version of init wrote there.
    (old / "SKILL.md").write_text(
        (ASSETS / "SKILL.md").read_text().replace("name: thinspec-rules", "name: thinspec", 1))
    done = init(tmp_path)
    assert not old.exists() and any("removed" in line and "thinspec-rules" in line for line in done)
    assert (skills / "thinspec-rules" / "SKILL.md").exists()

    # A skill of that name with something else in it, or with files beside it, is not init's to remove.
    old.mkdir()
    (old / "SKILL.md").write_text("---\nname: thinspec\n---\n\n# My own notes\n")
    init(tmp_path)
    assert (old / "SKILL.md").read_text().endswith("# My own notes\n")
    (old / "SKILL.md").write_text(
        (ASSETS / "SKILL.md").read_text().replace("name: thinspec-rules", "name: thinspec", 1))
    (old / "extra.md").write_text("kept")
    init(tmp_path)
    assert not (old / "SKILL.md").exists() and (old / "extra.md").read_text() == "kept"


def test_no_shipped_text_names_the_old_abs_command():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    shipped = [root / "README.md", root / "docs" / "DESIGN.md", root / "claude-plugin" / "README.md",
               root / "claude-plugin" / "hooks" / "register.tsx", root / "claude-plugin" / ".claude-plugin" / "plugin.json",
               root / ".claude-plugin" / "marketplace.json"]
    shipped += sorted((root / "src" / "thinspec").rglob("*.py")) + sorted((root / "src" / "thinspec" / "assets").glob("*"))
    for path in shipped:
        assert "/abs" not in path.read_text(encoding="utf-8").replace("/abstraction", ""), path


def test_init_keeps_an_existing_abstraction_and_config(tmp_path):
    init(tmp_path, claude=False)
    core = tmp_path / "abstraction" / "core.md"
    core.write_text(core.read_text().replace("Core abstraction", "My idea"))
    cfg = tmp_path / ".thinspec" / "config.json"
    cfg.write_text(json.dumps({"gate": "strict"}))
    init(tmp_path, claude=False)
    assert "My idea" in core.read_text() and json.loads(cfg.read_text()) == {"gate": "strict"}
    assert not (tmp_path / ".claude").exists()


def test_a_task_from_the_command_line(repo, capsys):
    assert run(repo, "task", "add", "--parent", "instrument", "--title", "Planned", "--check", "c",
               "--trials", "2") == 0
    assert run(repo, "task", "start", "T1") == 0
    assert run(repo, "task", "trial", "T1", "--fail") == 1
    assert run(repo, "task", "metric", "T1", "--none") == 0
    assert run(repo, "task", "trial", "T1", "--fail") == 0
    assert run(repo, "task", "decide", "T1", "extend", "--trials", "3", "--note", "ok") == 0
    assert run(repo, "task", "done", "T1", "--result", "passes") == 0
    assert run(repo, "status") == 0 and run(repo, "show", "T1") == 0 and run(repo, "log") == 0
    out = capsys.readouterr().out
    assert "1/5 trials" in out and "result: passes" in out
    assert repo.task("T1").status == "done"


def test_errors_exit_nonzero_with_a_message(repo, tmp_path_factory, capsys):
    assert run(repo, "task", "start", "T99") == 1
    assert "No task 'T99'" in capsys.readouterr().err
    empty = tmp_path_factory.mktemp("empty")
    assert main(["--root", str(empty), "status"]) == 1
    assert "thinspec init" in capsys.readouterr().err


def test_check_fails_on_a_broken_graph(repo, capsys):
    assert run(repo, "check") == 0
    (repo.abs_dir / "orphan.md").write_text("---\nid: orphan\nparent: nowhere\n---\n\n## Invariants\n\n- x\n")
    assert run(repo, "check") == 1
    assert "does not exist" in capsys.readouterr().out


def test_viewer_data_and_page(repo, tmp_path):
    tid = repo.start_task(parent="instrument", title="</script><b>x", check="c", budget={"trials": 1}).id
    repo.record_trial(tid, "s", "pytest", False)
    repo.raise_alarm(tid)
    repo.decide(tid, "step_back", note="wrong design")
    data = build_data(repo)
    node = [n for n in data["nodes"] if n["id"] == "instrument"][0]
    assert node["version"] == 2 and node["revisions"][0]["reason"] == "wrong design"
    assert node["history"][0]["version"] == 1
    task = data["tasks"][0]
    assert task["status"] == "stepped_back" and task["hit"] and task["actual"]["trials"] == 1
    assert [e["kind"] for e in data["timeline"]] == ["revise", "alarm", "add"]
    json.dumps(data)                                          # everything is serialisable

    html = render_html(repo)
    assert "__DATA__" not in html and "__LIVE__" not in html
    assert "</script><b>x" not in html                        # a title cannot break out of the data block
    out = tmp_path / "v.html"
    assert run(repo, "view", "--out", str(out)) == 0 and out.read_text().startswith("<!DOCTYPE html>")


def test_agents_md_section_is_added_once_and_refreshed_in_place(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# House rules\n\nBe kind.\n")
    init(tmp_path, claude=False, agents_md=True)
    init(tmp_path, claude=False, agents_md=True)
    text = (tmp_path / "AGENTS.md").read_text()
    assert text.startswith("# House rules") and text.count("thinspec:start") == 1
    assert "task_report" in text


def test_status_is_one_line_per_design_and_full_adds_the_rules(repo, capsys):
    tid = repo.start_task(parent="instrument", title="Hook backward ops", check="c", budget={"trials": 1}).id
    repo.record_trial(tid, "s", "pytest", False)
    repo.raise_alarm(tid)
    assert run(repo, "status") == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert any(line.startswith("└─ Instrument") and "watch" in line and "⏸" in line for line in lines)
    assert "One unique hook point per step." not in out            # the glance view leaves the rules out
    assert "thinspec task decide %s" % tid in out
    assert run(repo, "status", "--full") == 0
    assert "One unique hook point per step." in capsys.readouterr().out


def test_state_prints_what_the_pane_reads(repo, capsys):
    repo.start_task(parent="instrument", title="Hook backward ops", check="c", budget={"trials": 2})
    assert run(repo, "state", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert [n["id"] for n in data["nodes"]] == ["core", "instrument"]
    task = data["tasks"][0]
    assert task["status"] == "active" and task["budget"] == {"trials": 2}
    assert set(task["actual"]) == {"trials", "lines", "patches", "minutes"} and task["guess"] is False
    assert set(data["nodes"][0]["health"]) >= {"level", "reason"}


def test_the_person_sets_a_budget_in_runs_and_lines_from_the_command_line(repo, capsys):
    import pytest

    assert run(repo, "task", "start", "--parent", "instrument", "--title", "Tune", "--check", "c", "--trials", "3") == 0
    assert run(repo, "task", "budget", "T1", "--trials", "20", "--lines", "300", "--note", "training is noisy") == 0
    assert "the budget is now 20 trials, 300 lines, set by you" in capsys.readouterr().out
    assert repo.task("T1").budget == {"trials": 20, "lines": 300}
    assert run(repo, "task", "budget", "T1") == 1            # no numbers given
    assert "trials" in capsys.readouterr().err
    assert run(repo, "task", "metric", "T1", "--none") == 0
    assert run(repo, "task", "patch", "T1", "-n", "2", "--lines", "40") == 0
    assert "40/300 lines" in capsys.readouterr().out
    # The help offers runs and lines, and no longer time or the number of edits.
    with pytest.raises(SystemExit):
        main(["task", "budget", "--help"])
    out = capsys.readouterr().out
    assert "--trials" in out and "--lines" in out and "--minutes" not in out and "--patches" not in out


def test_a_component_is_added_from_the_command_line_and_listed_after_the_designs(repo, capsys):
    assert run(repo, "node", "add", "hook-table", "--parent", "instrument", "--kind", "component",
               "--title", "Hook table", "--invariant", "holds") == 0
    assert run(repo, "node", "add", "a-shared-part", "--parent", "core", "--kind", "component",
               "--invariant", "holds") == 0
    assert run(repo, "node", "add", "zz-design", "--parent", "core", "--title", "Decide late",
               "--invariant", "holds") == 0
    assert run(repo, "node", "add", "wrong-way", "--parent", "hook-table") == 1      # a design under a component
    assert "does not sit under what carries it out" in capsys.readouterr().err
    assert run(repo, "check") == 0
    capsys.readouterr()
    assert run(repo, "state") == 0
    rows = json.loads(capsys.readouterr().out)["nodes"]
    assert [(n["id"], n["kind"]) for n in rows] == [
        ("core", "core"), ("instrument", "design"), ("hook-table", "component"),
        ("zz-design", "design"), ("a-shared-part", "component")]
    assert run(repo, "status") == 0
    assert "Hook table (component)" in capsys.readouterr().out


def test_state_and_status_show_the_sessions_and_mark_the_one_asking(repo, capsys, monkeypatch):
    from thinspec.core import Repo

    other = Repo(repo.root)
    other.actor = "bbbb-2"
    other.note_session("bbbb-2", "codex")
    other.start_task(parent="instrument", title="Probe transfer time", check="c", budget={"trials": 2})
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "aaaa-1")   # an agent session runs the command
    assert run(repo, "task", "start", "--parent", "instrument", "--title", "Hook backward ops", "--check", "c",
               "--patches", "3") == 0
    capsys.readouterr()
    assert run(repo, "state", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    rows = {s["id"]: s for s in data["sessions"]}
    assert rows["aaaa-1"]["me"] and rows["aaaa-1"]["task"] == "T2" and not rows["bbbb-2"]["me"]
    assert (rows["bbbb-2"]["name"], rows["bbbb-2"]["task"], rows["bbbb-2"]["state"]) == ("codex bbbb", "T1", "working")
    assert set(rows["bbbb-2"]) >= {"agent", "host", "dir", "here", "last", "since"}
    assert data["tasks"][0]["started_by"] == "bbbb-2" and data["tasks"][1]["worked_on_by"] == ["aaaa-1"]
    assert run(repo, "state", "--session", "bbbb-2") == 0    # a pane names the session it sits in
    assert [s["id"] for s in json.loads(capsys.readouterr().out)["sessions"] if s["me"]] == ["bbbb-2"]
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert run(repo, "status") == 0
    out = capsys.readouterr().out
    assert "Sessions" in out and "codex bbbb: T1" in out and "(this session)" not in out


def test_check_reports_nodes_not_read_again_after_a_revision_and_verify_clears_them(repo, capsys):
    assert run(repo, "check") == 0
    assert run(repo, "revise", "instrument", "--decision", "--reason", "try another hook point") == 0
    assert "read again the nodes next to it (core)" in capsys.readouterr().out
    assert run(repo, "check") == 1
    assert "Node 'core' has not been read again since 'instrument' (now v2) changed" in capsys.readouterr().out
    assert run(repo, "verify") == 1                          # with no node, it lists what is owed
    assert "thinspec verify core --note" in capsys.readouterr().out
    assert build_data(repo)["to_verify"] == [{"node": "core", "since": [{"node": "instrument", "version": 2}]}]
    assert any("'core' has not been read again" in p for p in build_data(repo)["problems"])

    assert run(repo, "verify", "core") == 1                  # a second reading needs its reason
    assert "Say why 'core' still follows" in capsys.readouterr().err
    assert run(repo, "verify", "core", "--note", "the core names no hook point") == 0
    assert "was verified and still fits" in capsys.readouterr().out
    assert run(repo, "check") == 0 and run(repo, "verify") == 0
    data = build_data(repo)
    assert data["to_verify"] == [] and data["timeline"][0]["text"] == "Design 'core' verified, still fits"


def test_node_move_from_the_command_line_names_the_nodes_to_verify(repo, capsys):
    assert run(repo, "node", "add", "probe", "--parent", "instrument", "--summary", "Measure.", "--invariant", "holds") == 0
    capsys.readouterr()
    assert run(repo, "node", "move", "probe", "--under", "core", "--reason", "it holds for every design") == 0
    out = capsys.readouterr().out
    assert "'probe' now sits under 'core', no longer under 'instrument'" in out
    assert "To verify against the move: core, instrument." in out
    assert run(repo, "check") == 1
    assert build_data(repo)["timeline"][0]["text"] == "Design 'probe' moved from under 'instrument' to under 'core'"
    assert run(repo, "node", "move", "probe", "--under", "core", "--reason", "again") == 1
    assert "already sits under" in capsys.readouterr().err


def test_init_codex_wires_hooks_the_mcp_server_and_the_rules_and_is_safe_to_run_twice(tmp_path):
    import json as _json
    from thinspec.install import init
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('model = "gpt-5"\n')
    (tmp_path / ".codex" / "hooks.json").write_text(_json.dumps(
        {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "mine"}]}]}}))
    for _ in range(2):
        done = init(tmp_path, claude=False, codex=True)
    assert any(".codex/hooks.json" in d for d in done)
    hooks = _json.loads((tmp_path / ".codex" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}
    pre = hooks["PreToolUse"]
    assert pre[0]["hooks"][0]["command"] == "mine" and len(pre) == 2     # theirs kept, ours once
    assert "thinspec hook --agent codex" in pre[1]["hooks"][0]["command"] and "apply_patch" in pre[1]["matcher"]
    cfg = (tmp_path / ".codex" / "config.toml").read_text()
    assert cfg.startswith('model = "gpt-5"') and cfg.count("[mcp_servers.thinspec]") == 1
    assert 'THINSPEC_AGENT = "codex"' in cfg
    assert (tmp_path / ".codex" / "skills" / "thinspec-rules" / "SKILL.md").exists()
