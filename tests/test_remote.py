"""Agents no hook sees: edits counted from the working tree, and a person's word from the viewer."""
import json
import subprocess

from thinspec.cli import main
from thinspec.remote import post_message, sync, unread, viewer_action
from thinspec.viewer import build_data, handle_post, render_html


def run(repo, *argv):
    return main(["--root", str(repo.root)] + list(argv))


def git(root, *args):
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


def git_repo(repo):
    git(repo.root, "init", "-q")
    git(repo.root, "config", "user.email", "t@example.com")
    git(repo.root, "config", "user.name", "t")
    (repo.root / "app.py").write_text("a = 1\nb = 2\n")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "start")


def started(repo, session="cloud-1"):
    tid = repo.plan_task("instrument", "Hook the step", "the step is hooked", budget={"trials": 3, "lines": 50})
    repo.actor, repo.actor_agent = session, "claude-cloud"
    repo.start_task(tid)
    return repo.task(tid)


def test_sync_takes_a_snapshot_first_then_counts_what_changed_on_the_sessions_task(repo):
    git_repo(repo)
    task = started(repo)
    first = sync(repo)
    assert first["baseline"] and first["git"]
    (repo.root / "app.py").write_text("a = 1\nb = 3\nc = 4\n")      # one line changed, one added
    (repo.root / "new.py").write_text("x = 1\n")
    res = sync(repo)
    assert not res["baseline"] and res["task"] == task.id
    assert dict(res["code"]) == {"app.py": 3, "new.py": 1}
    t = repo.task(task.id)
    assert t.actual()["patches"] == 2 and t.lines == 4
    assert sync(repo)["code"] == []                                   # nothing new since


def test_sync_leaves_the_real_git_index_alone_and_records_spec_edits_apart(repo):
    git_repo(repo)
    started(repo)
    sync(repo)
    (repo.root / "abstraction" / "instrument.md").write_text("changed by hand\n")
    (repo.root / "app.py").write_text("a = 9\nb = 2\n")
    res = sync(repo)
    assert [rel for rel, _ in res["abstraction"]] == ["abstraction/instrument.md"]
    assert [rel for rel, _ in res["code"]] == ["app.py"]
    status = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=str(repo.root),
                            capture_output=True, text=True).stdout
    assert status.strip() == ""                                       # nothing staged in the real index
    kinds = [e["ev"] for e in repo.ledger.events()]
    assert "abstraction_edited" in kinds


def test_sync_without_git_sizes_changes_by_line_count(repo):
    started(repo)
    (repo.root / "a.txt").write_text("1\n2\n")
    assert sync(repo)["baseline"] and not sync(repo)["code"]
    (repo.root / "a.txt").write_text("1\n2\n3\n4\n")
    res = sync(repo)
    assert res["git"] is False and dict(res["code"]) == {"a.txt": 2}


def test_sync_from_the_cli_with_session_flags_names_the_session(repo, capsys):
    git_repo(repo)
    task = repo.task(repo.plan_task("instrument", "Hook the step", "the step is hooked", budget={"trials": 3}))
    assert run(repo, "--session", "cloud-7", "--agent", "claude-cloud", "task", "start", task.id) == 0
    assert run(repo, "--session", "cloud-7", "sync") == 0
    (repo.root / "app.py").write_text("changed\n")
    capsys.readouterr()
    assert run(repo, "--session", "cloud-7", "sync") == 0
    out = capsys.readouterr().out
    assert "Recorded 1 edited file" in out and task.id in out
    sess = repo.state().sessions["cloud-7"]
    assert sess.agent == "claude-cloud" and sess.task == task.id


def test_a_message_reaches_the_agent_once_and_other_commands_point_to_it(repo, capsys):
    task = started(repo, "cloud-1")
    post_message(repo, "Stop tuning the cache; read the paper's section 4 first", task=task.id, via="viewer")
    assert run(repo, "--session", "cloud-1", "status") == 0
    assert "1 new from your person" in capsys.readouterr().err
    assert run(repo, "--session", "cloud-1", "inbox") == 0
    assert "section 4" in capsys.readouterr().out
    assert run(repo, "--session", "cloud-1", "inbox") == 0
    assert "Nothing new" in capsys.readouterr().out
    # another session has not read it yet; a person's terminal (no session) is never told
    assert len(unread(repo, "cloud-2")) == 1
    assert run(repo, "status") == 0
    assert "new from your person" not in capsys.readouterr().err


def test_a_decision_pressed_in_the_viewer_is_recorded_as_the_persons_and_reaches_the_inbox(repo):
    task = started(repo)
    out = viewer_action(repo, "/api/decide", {"task": task.id, "choice": "extend", "trials": 2,
                                              "note": "one more workload"})
    assert out["ok"] and repo.task(task.id).budget["trials"] == 5
    (seq, ev), = unread(repo, "cloud-1")
    assert ev["ev"] == "decision" and ev["by"] == "person" and ev["extend"] == {"trials": 2}
    viewer_action(repo, "/api/decide", {"task": task.id, "choice": "ban", "text": "special-casing a workload"})
    assert "special-casing a workload" in repo.node("instrument").bans
    texts = [e["text"] for e in build_data(repo)["timeline"]]
    assert any("in the viewer: ban" in t for t in texts)


def test_the_served_viewer_takes_presses_only_from_its_own_page(repo):
    task = started(repo)
    body = json.dumps({"text": "hello", "task": task.id}).encode()
    status, out = handle_post(repo, "/api/message", {}, body, "tok")
    assert status == 403                                               # no token
    status, out = handle_post(repo, "/api/message", {"X-ThinSpec-Token": "tok", "Origin": "https://evil.example"},
                              body, "tok")
    assert status == 403
    status, out = handle_post(repo, "/api/message", {"X-ThinSpec-Token": "tok", "Origin": "http://127.0.0.1:8765"},
                              body, "tok")
    assert status == 200 and out["ok"]
    status, out = handle_post(repo, "/api/message", {"X-ThinSpec-Token": "tok"}, b"{\"text\": \"\"}", "tok")
    assert status == 400 and "empty" in out["error"]
    timeline = build_data(repo)["timeline"]
    assert timeline[0]["kind"] == "message" and timeline[0]["note"] == "hello"


def test_the_live_page_carries_its_token_and_the_snapshot_none(repo):
    assert '"tok-123"' in render_html(repo, live=True, token="tok-123")
    page = render_html(repo, live=False)
    assert "const TOKEN = \"\";" in page and "__TOKEN__" not in page
