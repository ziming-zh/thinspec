import pytest

from thinspec import ThinSpecError, store
from thinspec.core import fmt_usage

BUDGET = {"minutes": 60, "trials": 4, "patches": 20}


def start(repo, title="Hook backward ops", parent="instrument", budget=BUDGET, **kw):
    return repo.start_task(parent=parent, title=title, check="hooks match on workload B", budget=budget, **kw).id


def test_task_needs_a_check_and_a_budget(repo):
    with pytest.raises(ThinSpecError, match="check"):
        repo.plan_task("instrument", "No check", "")
    with pytest.raises(ThinSpecError, match="budget"):
        repo.start_task(parent="instrument", title="No budget", check="c")
    with pytest.raises(ThinSpecError, match="No node"):
        repo.plan_task("nowhere", "t", "c")
    assert repo.state().tasks == {}                      # nothing half-created


def test_plan_then_start_keeps_the_planned_budget(repo):
    tid = repo.plan_task("instrument", "Planned", "c", budget={"trials": 3}, set_by="user")
    assert tid == "T1" and repo.task(tid).status == "planned"
    task = repo.start_task(task_id=tid)
    assert (task.status, task.budget, task.set_by) == ("active", {"trials": 3}, "user")
    with pytest.raises(ThinSpecError, match="already active"):
        repo.start_task(task_id=tid)
    assert start(repo) == "T2"


def test_usage_and_which_metrics_are_past_the_estimate(repo):
    tid = start(repo)
    for _ in range(4):
        repo.record_trial(tid, "s", "pytest", False)
    repo.record_patch(tid, "s", "a.py", 10)
    repo.record_time(tid, "s", 30 * 60)
    task = repo.task(tid)
    assert fmt_usage(task) == "4/4 trials · 1/20 patches · 30/60 min"
    assert task.past() == ["trials"]                     # the estimate is reached; nothing stops
    assert task.past(extra_seconds=30 * 60) == ["trials", "minutes"]
    assert task.past(2.0) == []                          # twice the estimate: not yet
    assert (task.failed, task.lines, task.files) == (4, 10, {"a.py"})


def test_alarm_blocks_once_and_extend_reopens(repo):
    tid = start(repo)
    for _ in range(4):
        repo.record_trial(tid, "s", "pytest", False)
    assert repo.raise_alarm(tid) is True
    assert repo.raise_alarm(tid) is False                # already blocked: no second alarm
    assert repo.task(tid).status == "blocked"
    with pytest.raises(ThinSpecError, match="how much more"):
        repo.decide(tid, "extend")
    task = repo.decide(tid, "extend", note="right approach", extend={"trials": 2})
    assert (task.status, task.budget["trials"], task.past()) == ("active", 6, [])
    assert task.hit_budget                               # the overrun stays on record


def test_ban_closes_task_and_writes_the_ban(repo):
    tid = start(repo, title="Stable node names")
    task = repo.decide(tid, "ban", note="names shift with the model", ban_text="Stable node names across steps")
    assert task.status == "banned"
    assert repo.node("instrument").bans == ["Stable node names across steps — names shift with the model"]
    with pytest.raises(ThinSpecError, match="open tasks"):
        repo.decide(tid, "abandon")


def test_step_back_archives_the_design_and_opens_a_new_version(repo):
    tid = start(repo)
    before = repo.node("instrument").path.read_text()
    task = repo.decide(tid, "step-back", note="offload needs a global view")
    assert task.status == "stepped_back"
    node = repo.node("instrument")
    assert node.version == 2
    hist = store.history(repo.abs_dir, "instrument")
    assert [v for v, _ in hist] == [1] and hist[0][1].path.read_text() == before
    rev = [e for e in repo.ledger.events() if e["ev"] == "node_revised"][0]
    assert (rev["from"], rev["to"], rev["task"], rev["reason"]) == (1, 2, tid, "offload needs a global view")


def test_self_report_pauses_only_when_strictly_past_the_line(repo):
    tid = start(repo, budget={"trials": 2})
    assert repo.report(tid, trials=2).status == "active"   # at the estimate: nothing stops
    assert repo.report(tid, trials=2).status == "active"   # exactly twice the estimate: may still pass
    task = repo.report(tid, trials=1)
    assert task.status == "blocked" and task.self_reported and task.alarms[0]["exhausted"] == ["trials"]
    with pytest.raises(ThinSpecError, match="negative"):
        repo.report(tid, trials=-1)


def test_done_and_closed_tasks(repo):
    tid = start(repo)
    task = repo.done_task(tid, "overhead 0.4%")
    assert (task.status, task.result) == ("done", "overhead 0.4%")
    with pytest.raises(ThinSpecError):
        repo.done_task(tid)
    with pytest.raises(ThinSpecError):
        repo.report(tid, trials=1)


def run_out(repo, title, parent="instrument"):
    tid = start(repo, title=title, parent=parent)
    for _ in range(4):
        repo.record_trial(tid, "s", "pytest", False)
    repo.raise_alarm(tid)
    return tid


def test_health_follows_the_recent_run_of_overruns(repo, clock):
    assert repo.health()["instrument"]["level"] == "idle"
    a = run_out(repo, "first path")
    clock.step(60)
    h = repo.health()["instrument"]
    assert h["level"] == "watch" and h["needs_decision"] == [a]
    repo.decide(a, "ban", note="x")
    clock.step(60)
    b = run_out(repo, "second path")
    clock.step(60)
    h = repo.health()
    assert h["instrument"]["level"] == "step_back"
    assert "last 2 tasks" in h["instrument"]["reason"]
    assert h["core"]["level"] == "watch"                 # trouble below shows on the parent
    repo.decide(b, "ban", note="y")
    clock.step(60)
    c = start(repo, title="third path")
    clock.step(60)
    repo.done_task(c, "works")
    h = repo.health()["instrument"]
    assert h["level"] == "ok" and "2 of 3" in h["reason"]


def test_revision_resets_the_health_of_a_design(repo, clock):
    a = run_out(repo, "first")
    clock.step(60)
    repo.decide(a, "ban", note="x")
    b = run_out(repo, "second")
    clock.step(60)
    repo.decide(b, "step_back", note="design was wrong")
    clock.step(60)
    assert repo.health()["instrument"]["level"] == "idle"


def test_a_task_past_its_estimate_puts_the_design_on_watch(repo):
    tid = start(repo, budget={"patches": 10})
    for _ in range(9):
        repo.record_patch(tid, "s", "a.py", 1)
    assert repo.health()["instrument"]["level"] == "ok"      # under the estimate: nothing to look at
    repo.record_patch(tid, "s", "a.py", 1)
    h = repo.health()["instrument"]
    assert h["level"] == "watch" and "past its estimate" in h["reason"]


def test_restore_brings_an_earlier_text_back_as_a_new_version(repo):
    path = repo.node("instrument").path
    first = path.read_text()
    repo.revise("instrument", "hook points differ per backend", decision=True)
    path.write_text(first.replace("One unique hook point per step.", "One hook point per backend.")
                    .replace("version: 1", "version: 2"))
    assert repo.node("instrument").invariants == ["One hook point per backend."]

    assert repo.restore("instrument", reason="the per-backend rule  broke replay") == (1, 3)
    node = repo.node("instrument")
    assert node.version == 3 and node.invariants == ["One unique hook point per step."]   # that text again
    kept = dict(store.history(repo.abs_dir, "instrument"))
    assert kept[2].invariants == ["One hook point per backend."]         # what it replaced is kept
    rev = [e for e in repo.ledger.events() if e["ev"] == "node_revised"][-1]
    assert (rev["from"], rev["to"], rev["restored"]) == (2, 3, 1)
    assert rev["reason"] == "Switched back to v1: the per-backend rule broke replay"

    assert repo.restore("instrument", to=2) == (2, 4)                    # the switch can be switched back
    assert repo.node("instrument").invariants == ["One hook point per backend."]
    with pytest.raises(ThinSpecError, match="no archived version 9"):
        repo.restore("instrument", to=9)
    with pytest.raises(ThinSpecError, match="no earlier version"):
        repo.restore("core")


def test_a_node_carries_a_digest_that_is_rewritten_and_capped(repo):
    from thinspec.viewer import build_data

    kept = repo.digest("instrument", features=["Hooks every op  during forward."], negative=["Stable node names: no gain."])
    assert kept == {"features": ["Hooks every op during forward."], "negative": ["Stable node names: no gain."]}
    # A section given replaces what was there; the others stay.
    repo.digest("instrument", features=["Hooks every op, forward and backward."])
    row = {n["id"]: n for n in build_data(repo)["nodes"]}["instrument"]
    assert row["digest"] == {"features": ["Hooks every op, forward and backward."], "as_built": [], "reverts": [],
                             "positive": [], "negative": ["Stable node names: no gain."]}
    # Where what is built departs from the node's story, the digest says so, with the reason.
    repo.digest("instrument", as_built=["Hooks forward only: the backward pass was not released (likely)."])
    assert "as_built: Hooks forward only: the backward pass was not released (likely)." in repo.context_text("instrument")
    assert repo.state().digest["instrument"]["features"] == ["Hooks every op, forward and backward."]   # the rest stays
    assert "features: Hooks every op, forward and backward." in repo.context_text("instrument")
    # The cap is what keeps it a digest: a sixth line, or a long one, is refused, and nothing is recorded.
    with pytest.raises(ThinSpecError, match="at most 5 lines"):
        repo.digest("instrument", features=["line %d" % i for i in range(6)])
    with pytest.raises(ThinSpecError, match="one short sentence"):
        repo.digest("instrument", reverts=["x" * 161])
    with pytest.raises(ThinSpecError, match="at least one section"):
        repo.digest("instrument")
    assert repo.state().digest["instrument"]["features"] == ["Hooks every op, forward and backward."]
    repo.rename_node("instrument", "hook-points")                        # it follows the node
    assert repo.state().digest["hook-points"]["negative"] == ["Stable node names: no gain."]
    assert "A check that passed is not a result" in repo.digest_prompt("hook-points")
    # The story and the digest are kept from disagreeing: at a task's close the approach is read against it.
    assert "read the node's approach against its digest" in repo.digest_prompt("hook-points")


def test_a_rewording_keeps_the_text_and_takes_no_new_version(repo):
    before = (repo.abs_dir / "instrument.md").read_text(encoding="utf-8")
    assert repo.revise("instrument", "the approach reads better with the decision first") == 1   # still v1
    assert repo.node("instrument").version == 1
    kept = repo.abs_dir / "history" / "instrument.v1.e1.md"
    assert kept.read_text(encoding="utf-8") == before                    # the earlier wording is kept, with its reason
    assert "v1, reworded: the approach reads better" in repo.context_text("instrument")
    assert "core" in [row["node"] for row in repo.to_verify()]           # the node above is read again all the same
    assert repo.revise("instrument", "a second pass") == 1               # and again: a second kept wording, no number
    assert (repo.abs_dir / "history" / "instrument.v1.e2.md").is_file()
    assert store.history(repo.abs_dir, "instrument") == []               # no numbered version to switch back to yet

    # A rule added, dropped or reversed, or a step back, is a decision: that takes the next number.
    assert repo.revise("instrument", "hook points differ per backend", decision=True) == 2
    assert [v for v, _ in store.history(repo.abs_dir, "instrument")] == [1]
    assert "v1 -> v2: hook points differ" in repo.context_text("instrument")
    repo.rename_node("instrument", "hook-points")                        # kept wordings follow a rename too
    assert (repo.abs_dir / "history" / "hook-points.v1.e1.md").is_file()


def test_rename_takes_the_tasks_the_children_and_the_kept_versions_along(repo):
    tid = start(repo)                                                    # a task under 'instrument'
    repo.revise("instrument", "learned something", decision=True)
    repo.add_node("probe", "Probe", "instrument", "Measure the transfer.", ["holds"])
    repo.rename_node("instrument", "hook-points")

    nodes = repo.nodes()
    assert "instrument" not in nodes and nodes["hook-points"].version == 2
    assert nodes["probe"].parent == "hook-points"                        # the node under it follows
    assert repo.task(tid).parent == "hook-points" and repo.health()["hook-points"]["tasks"] == 1
    assert [v for v, _ in store.history(repo.abs_dir, "hook-points")] == [1]
    assert "learned something" in repo.context_text("hook-points")       # its past is still its own
    assert repo.restore("hook-points") == (1, 3) and set(repo.nodes()) == {"core", "hook-points", "probe"}
    assert [e["ev"] for e in repo.state().timeline if e["ev"] == "node_renamed"] == ["node_renamed"]

    with pytest.raises(ThinSpecError, match="already exists"):
        repo.rename_node("probe", "hook-points")
    for taken in ("agents", "README", "claude"):                         # names an agent or the folder reads
        with pytest.raises(ThinSpecError, match="cannot be a node id"):
            repo.rename_node("probe", taken)
    with pytest.raises(ThinSpecError, match="cannot be a node id"):
        repo.add_node("agents", "Agent interface", "core")


def test_retire_keeps_the_text_moves_the_tasks_and_is_on_record(repo):
    repo.add_node("probe", "Probe", "core", "Measure the transfer.", ["holds"])
    tid = start(repo, parent="probe")
    with pytest.raises(ThinSpecError, match="--into"):
        repo.retire_node("probe", "folded into instrument")              # its task must go somewhere
    with pytest.raises(ThinSpecError, match="needs a reason"):
        repo.retire_node("probe", " ", into="instrument")

    archived = repo.retire_node("probe", "folded  into instrument", into="instrument")
    assert "probe" not in repo.nodes() and "Measure the transfer." in archived.read_text()
    assert archived.name == "probe.v1.md" and archived.parent.name == "history"
    assert repo.task(tid).parent == "instrument"
    gone = [e for e in repo.ledger.events() if e["ev"] == "node_retired"][0]
    assert (gone["node"], gone["into"], gone["reason"]) == ("probe", "instrument", "folded into instrument")

    with pytest.raises(ThinSpecError, match="core abstraction"):
        repo.retire_node("core", "x")
    repo.add_node("child", "Child", "instrument", "x", ["holds"])
    with pytest.raises(ThinSpecError, match="nodes under it"):
        repo.retire_node("instrument", "x", into="core")


def test_damaged_ledger_lines_are_skipped(repo):
    tid = start(repo)
    with open(repo.ledger.path, "a") as fh:
        fh.write("{not json\n\n[1,2]\n")
    repo.record_patch(tid, "s", "a.py", 1)
    assert repo.task(tid).patches == 1


def test_untracked_patches_are_counted_apart(repo):
    repo.record_patch(None, "s", "README.md", 3)
    st = repo.state()
    assert (st.untracked_patches, st.untracked_lines) == (1, 3)


def test_overview_and_context_text(repo):
    tid = start(repo)
    repo.add_ban("core", "Global locks", "too slow")
    text = repo.overview_text()
    assert "instrument" in text and "Active tasks" in text and tid in text
    ctx = repo.context_text("instrument")
    assert "One unique hook point per step." in ctx
    assert "Global locks" in ctx                         # bans above a node bind it too
    with pytest.raises(ThinSpecError):
        repo.context_text("nope")


def test_a_design_with_no_tasks_of_its_own_is_as_well_as_the_component_under_it(repo, clock):
    repo.add_node("hook-table", "Hook table", "instrument", "Where hooks are kept.", ["holds"], kind="component")
    assert [e.get("kind") for e in repo.ledger.events() if e.get("node") == "hook-table"] == ["component"]
    assert repo.health()["instrument"]["level"] == "idle"
    done = start(repo, parent="hook-table")
    repo.done_task(done, "ok")
    h = repo.health()
    assert (h["hook-table"]["level"], h["instrument"]["level"]) == ("ok", "ok")
    assert h["instrument"]["reason"] == "the work under it is within budget" and h["core"]["level"] == "ok"
    clock.step(60)
    a = run_out(repo, "first path", parent="hook-table")     # one overrun: the component is watched, and so is the design
    h = repo.health()
    assert (h["hook-table"]["level"], h["instrument"]["level"]) == ("watch", "watch")
    assert "'hook-table' under it: %s went far past its estimate" % a in h["instrument"]["reason"]
    repo.decide(a, "ban", note="x")
    clock.step(60)
    run_out(repo, "second path", parent="hook-table")        # two in a row: the component is flagged
    h = repo.health()
    assert h["hook-table"]["level"] == "step_back" and h["instrument"]["level"] == "watch"
    assert "'hook-table' under it is flagged" in h["instrument"]["reason"]

    # Where the tree is text a component says that it is one, and it comes after the designs beside it.
    repo.add_node("zz-design", "Decide late", "core", "x", ["holds"])
    repo.add_node("a-shared-part", "A shared part", "core", "x", ["holds"], kind="component")
    tree = repo.tree_text()
    assert "Hook table (component)" in tree and "Instrument (component)" not in tree
    assert tree.index("Decide late") < tree.index("A shared part (component)")
    assert 'hook-table  "Hook table" (component)' in repo.overview_text()
    assert 'hook-table  "Hook table" (component)' in repo.context_text("hook-table")


# ---- what a budget is stated in ----------------------------------------

def test_a_budget_in_lines_pauses_a_task_whose_edits_go_far_past_it(repo, clock):
    tid = repo.start_task(parent="instrument", title="Tune the probe", check="c",
                          budget={"trials": 3, "lines": 100}).id
    assert fmt_usage(repo.task(tid)) == "0/3 trials · 0/100 lines"
    repo.record_patch(tid, "s", "src/a.py", 120)
    task = repo.task(tid)
    assert task.past() == ["lines"] and task.status == "active"      # the estimate is reached: nothing stops
    repo.record_patch(tid, "s", "src/a.py", 90)                      # the same lines reworked count again
    assert repo.task(tid).past(2.0) == ["lines"]
    assert repo.raise_alarm(tid) and repo.task(tid).status == "blocked"
    assert repo.task(tid).alarms[0]["exhausted"] == ["lines"]
    repo.decide(tid, "extend", extend={"lines": 200})                # and it is extended in the same measure
    assert repo.task(tid).budget == {"trials": 3, "lines": 300} and repo.task(tid).status == "active"


def test_a_guessed_estimate_is_marked_until_the_person_gives_their_numbers(repo, clock):
    tid = repo.start_task(parent="instrument", title="Debug the kernel", check="boots 20 times in a row",
                          budget={"trials": 5, "lines": 60}, guess=True).id
    task = repo.task(tid)
    assert task.guess and task.set_by == "agent"
    assert "as a guess" in repo.task_text(task) and "the agent's guess" in repo.overview_text()
    with pytest.raises(ThinSpecError, match="trials .* lines"):
        repo.set_budget(tid, {})
    task = repo.set_budget(tid, {"trials": 30}, note="it rarely boots clean before 20 tries")
    assert (task.budget, task.set_by, task.guess) == ({"trials": 30}, "user", False)   # theirs, and theirs whole
    assert "as a guess" not in repo.task_text(task) and "the agent's guess" not in repo.overview_text()

    # A budget the person set themselves is never a guess, and a paused task is extended, not given a new budget.
    own = repo.start_task(parent="instrument", title="Mine", check="c", budget={"trials": 1},
                          set_by="user", guess=True)
    assert not own.guess
    for _ in range(3):
        repo.record_trial(own.id, "s", "pytest", False)
    repo.raise_alarm(own.id)
    with pytest.raises(ThinSpecError, match="extended by a decision"):
        repo.set_budget(own.id, {"trials": 9})


def test_a_budget_recorded_in_minutes_and_edits_still_holds(repo, clock):
    tid = start(repo)                                                # BUDGET: 60 minutes, 4 trials, 20 edits
    assert repo.task(tid).budget == BUDGET
    assert fmt_usage(repo.task(tid)) == "0/4 trials · 0/20 patches · 0/60 min"
    assert set(repo.task(tid).actual()) == {"trials", "lines", "patches", "minutes"}


# ---- sessions ----------------------------------------------------------

def as_session(repo, sid, agent="claude-code"):
    """The same repo, acting as one agent session."""
    from thinspec.core import Repo

    r = Repo(repo.root)
    r.ledger.clock = repo.ledger.clock
    r.actor = sid
    r.note_session(sid, agent)
    return r


def test_the_record_says_which_session_started_a_task_and_which_worked_on_it(repo, clock):
    a, b = as_session(repo, "aaaa-1"), as_session(repo, "bbbb-2", agent="codex")
    t1 = start(a)
    t2 = start(b, title="Probe transfer time")
    b.report(t2, patches=2)
    state = repo.state()
    assert state.tasks[t1].started_by == "aaaa-1" and list(state.tasks[t2].sessions) == ["bbbb-2"]
    known = state.sessions["bbbb-2"]
    assert (known.agent, known.dir, known.task) == ("codex", repo.root.name, t2) and known.host
    a.note_session("aaaa-1", "claude-code")                  # a session is put in the record once
    assert sum(1 for e in repo.ledger.events() if e.get("ev") == "session") == 2


def test_sessions_are_listed_with_their_task_and_what_they_are_doing(repo, clock):
    a, b = as_session(repo, "aaaa-1"), as_session(repo, "bbbb-2", agent="codex")
    t1 = start(a)
    clock.step(20 * 60)                                      # a is not heard from again
    t2 = start(b, title="Probe transfer time")
    rows = {r["id"]: r for r in repo.sessions(me="bbbb-2")}
    assert [r["id"] for r in repo.sessions(me="bbbb-2")] == ["bbbb-2", "aaaa-1"]      # the asking session first
    assert (rows["bbbb-2"]["name"], rows["bbbb-2"]["task"], rows["bbbb-2"]["state"]) == ("codex bbbb", t2, "working")
    assert (rows["aaaa-1"]["task"], rows["aaaa-1"]["state"], rows["aaaa-1"]["me"]) == (t1, "quiet", False)
    assert repo.holders(t2) and not repo.holders(t1) and not repo.holders(t2, but="bbbb-2")

    a.done_task(t1, "done")                                  # nothing open and nothing recent: out of the picture
    clock.step(20 * 60)
    assert [r["id"] for r in repo.sessions()] == ["bbbb-2"]
    text = a.overview_text()
    assert "Sessions, working in parallel" in text and "codex bbbb: %s" % t2 in text and "Quiet since" in text
    assert "codex bbbb" in repo.tree_text()


def test_a_session_joins_an_open_task_by_name_and_its_budget_stays(repo, clock):
    a, b = as_session(repo, "aaaa-1"), as_session(repo, "bbbb-2")
    t1 = start(a)
    with pytest.raises(ThinSpecError, match="already active"):
        repo.start_task(task_id=t1)                          # nobody to join as: a person's terminal
    joined = b.start_task(task_id=t1, budget={"patches": 99})
    assert joined.budget == BUDGET and joined.started_by == "aaaa-1" and list(joined.sessions) == ["aaaa-1", "bbbb-2"]
    assert repo.state().sessions["bbbb-2"].task == t1
    assert [r["id"] for r in repo.holders(t1, but="aaaa-1")] == ["bbbb-2"]


def test_a_revision_is_carried_to_the_node_above_and_the_nodes_under_until_all_are_read_again(repo):
    repo.add_node("probe", "Probe", "instrument", "Measure the transfer.", ["holds"])
    repo.add_node("replay", "Replay", "core", "Run a recorded step again.", ["holds"])
    assert repo.to_verify() == []                                        # nothing has changed yet

    repo.revise("instrument", "hook points differ per backend", decision=True)
    assert repo.next_to("instrument") == ["core", "probe"]
    owed = {row["node"]: row["since"] for row in repo.to_verify()}
    assert owed == {"core": [{"node": "instrument", "version": 2}],     # the node above it
                    "probe": [{"node": "instrument", "version": 2}]}    # and the node under it
    assert "replay" not in owed                                          # a node beside it is not reached
    assert "'core' has not been read again since 'instrument' (now v2) changed" in repo.to_verify_text()[0]

    with pytest.raises(ThinSpecError, match="Say why 'probe' still follows"):
        repo.verify("probe", "  ")
    repo.verify("probe", "It measures at the hook point, whichever backend sets it.")
    assert [row["node"] for row in repo.to_verify()] == ["core"]

    repo.revise("core", "the hook is per backend, and the core said per step", decision=True)
    owed = {row["node"]: [s["node"] for s in row["since"]] for row in repo.to_verify()}
    # Revising the core counts as reading it, and carries the change on to everything under it.
    assert owed == {"instrument": ["core"], "replay": ["core"]}
    repo.verify("instrument", "It was the reason the core changed.")
    repo.verify("replay", "Replay does not depend on where the hook sits.")
    assert repo.to_verify() == []                                        # the spec is sound again
    assert "To verify." not in repo.overview_text()


def test_what_is_owed_follows_a_node_through_a_rename(repo):
    repo.add_node("probe", "Probe", "instrument", "Measure the transfer.", ["holds"])
    repo.revise("probe", "measures per backend now", decision=True)
    repo.rename_node("instrument", "hook-points")
    assert [row["node"] for row in repo.to_verify()] == ["hook-points"]
    assert "hook-points  since probe v2" in repo.overview_text()
    repo.verify("hook-points", "A hook point per step still holds with a probe per backend.")
    assert repo.to_verify() == []


def test_a_task_closed_with_a_result_puts_its_node_up_to_be_verified(repo):
    tid = start(repo)                                                    # a task under 'instrument'
    repo.record_patch(tid, "s", "a.py", 3)
    assert repo.to_verify() == []                                        # work alone raises nothing
    repo.done_task(tid, "the hook fires once per step")
    assert repo.to_verify() == [{"node": "instrument", "since": [], "round": {"task": tid, "after": "result"}}]
    assert "Node 'instrument' has not been checked against %s's result" % tid in repo.to_verify_text()[0]
    assert "instrument  against %s's result" % tid in repo.overview_text()
    assert "verify the node against %s's result" % tid in repo.verify_prompt("instrument", {"task": tid, "after": "result"})

    repo.verify("instrument", "One hook per step is what the result shows.")
    assert repo.to_verify() == []
    other = start(repo)
    repo.done_task(other, "replay matches")
    repo.revise("instrument", "the result showed two hooks on a retried step", decision=True)   # a revision reads the node too
    assert [row["node"] for row in repo.to_verify()] == ["core"]         # and carries on to the node above


def test_a_round_of_work_is_raised_once_and_not_after_the_node_was_verified(repo):
    tid = start(repo)
    assert repo.round_ended(tid, "work") is None                         # no work under the task yet
    repo.record_patch(tid, "s", "a.py", 3)
    assert repo.round_ended(tid, "work") == "instrument"
    assert repo.round_ended(tid, "work") is None                         # the same work is not raised twice
    assert repo.to_verify()[0]["round"] == {"task": tid, "after": "work"}
    assert "has not been checked against the work on %s" % tid in repo.to_verify_text()[0]

    repo.record_trial(tid, "s", "pytest", True)
    repo.verify("instrument", "Read against the edit to a.py: still one hook per step.")
    assert repo.round_ended(tid, "work") is None                         # verified after its latest work
    repo.record_patch(tid, "s", "a.py", 1)
    assert repo.round_ended(tid, "work") == "instrument"                 # new work is a new round


def test_a_node_moved_up_a_level_keeps_its_text_and_puts_the_nodes_next_to_it_up_to_be_verified(repo):
    repo.add_node("probe", "Probe", "instrument", "Measure the transfer.", ["holds"])
    repo.add_node("gauge", "Gauge", "probe", "Read one probe.", ["holds"])
    tid = start(repo, parent="probe")
    before = repo.node("probe").path.read_text()

    assert repo.move_node("probe", "core", "every design measures the transfer, not only this one") == "instrument"
    node = repo.node("probe")
    assert node.parent == "core" and node.version == 1                   # only its place changed
    assert node.path.read_text() == before.replace("parent: instrument", "parent: core")
    assert repo.task(tid).parent == "probe"                              # its tasks stay with it
    moved = [e for e in repo.ledger.events() if e["ev"] == "node_moved"][-1]
    assert (moved["from"], moved["to"]) == ("instrument", "core") and moved["reason"].startswith("every design")

    owed = {row["node"]: row for row in repo.to_verify()}
    assert set(owed) == {"core", "instrument", "gauge"}                  # above it now, where it left, under it
    assert owed["instrument"]["left"] == "probe" and owed["instrument"]["since"] == []
    assert "since 'probe' moved out from under it" in " ".join(repo.to_verify_text())
    for other in owed:
        repo.verify(other, "read against the move")
    assert repo.to_verify() == []


def test_a_move_that_would_break_the_tree_is_refused_and_changes_nothing(repo):
    repo.add_node("probe", "Probe", "instrument", "Measure the transfer.", ["holds"], kind="component")
    repo.add_node("replay", "Replay", "core", "Run a recorded step again.", ["holds"])
    for node, under, why, error in (
        ("probe", "core", "  ", "needs a reason"),
        ("core", "probe", "x", "nothing sits above it"),
        ("probe", "nowhere", "x", "no node 'nowhere'"),
        ("probe", "instrument", "x", "already sits under"),
        ("instrument", "probe", "x", "itself or sits under it"),
        ("instrument", "instrument", "x", "itself or sits under it"),
        ("replay", "probe", "x", "cannot sit under the component"),
    ):
        with pytest.raises(ThinSpecError, match=error):
            repo.move_node(node, under, why)
    assert repo.node("probe").parent == "instrument" and repo.to_verify() == []
    assert not [e for e in repo.ledger.events() if e["ev"] == "node_moved"]


# ---- a new version keeps what the old one proved ------------------------------------------

def _done_with_check(repo, title, cmd):
    tid = repo.start_task(parent="instrument", title=title, check="it passes", check_cmd=cmd, budget={"trials": 2}).id
    repo.record_trial(tid, "s", cmd, None)
    repo.done_task(tid, "passed")
    return tid


def test_a_task_closes_only_once_earlier_checks_under_its_design_pass_again(repo):
    old = _done_with_check(repo, "v1", "pytest tests/test_v1.py")
    new = repo.start_task(parent="instrument", title="v2", check="v2 passes", check_cmd="pytest tests/test_v2.py",
                          budget={"trials": 2}).id
    assert [k["cmd"] for k in repo.kept_checks(repo.task(new))] == ["pytest tests/test_v1.py"]
    with pytest.raises(ThinSpecError, match=r"(?s)cannot close yet.*pytest tests/test_v1.py.*%s" % old):
        repo.done_task(new, "v2 works")
    repo.record_check_run(new, "s", "pytest  tests/test_v1.py", False)
    with pytest.raises(ThinSpecError, match="cannot close yet"):        # it failed: still owed
        repo.done_task(new, "v2 works")
    repo.record_check_run(new, "s", "pytest tests/test_v1.py", True)
    assert repo.task(new).trials == 0                                   # a run of an earlier check is no trial
    assert repo.done_task(new, "v2 works").status == "done"


def test_an_earlier_check_can_be_dropped_only_with_a_reason(repo):
    _done_with_check(repo, "v1", "pytest tests/test_v1.py")
    new = repo.start_task(parent="instrument", title="v2", check="c", budget={"trials": 2}).id
    with pytest.raises(ThinSpecError, match="needs the reason"):
        repo.done_task(new, "ok", {"pytest tests/test_v1.py": " "})
    with pytest.raises(ThinSpecError, match="nothing to drop"):
        repo.done_task(new, "ok", {"pytest other": "gone"})
    task = repo.done_task(new, "ok", {"pytest tests/test_v1.py": "v1's special case for workload B was meant to go"})
    assert task.dropped == {"pytest tests/test_v1.py": "v1's special case for workload B was meant to go"}
    assert "dropped an earlier check" in repo.task_text(task)


def test_checks_under_other_designs_and_the_tasks_own_check_are_not_owed(repo):
    repo.add_node("evict", "Evict", "core")
    repo.start_task(parent="evict", title="other", check="c", check_cmd="pytest x", budget={"trials": 1})
    _done_with_check(repo, "same cmd", "pytest tests/test_v2.py")
    new = repo.start_task(parent="instrument", title="v2", check="c", check_cmd="pytest tests/test_v2.py",
                          budget={"trials": 2}).id
    assert repo.kept_checks(repo.task(new)) == []
    assert repo.done_task(new, "fine").status == "done"


def test_thinspec_run_records_the_exit_code_itself(repo):
    _done_with_check(repo, "v1", "python3 -c 'import sys; sys.exit(0)'")
    new = repo.start_task(parent="instrument", title="v2", check="c", check_cmd="python3 -c 'print(2)'",
                          budget={"trials": 2}).id
    assert repo.run_check(new, "python3 -c 'import sys; sys.exit(0)'").returncode == 0
    assert repo.run_check(new, "python3 -c 'print(2)'").returncode == 0
    assert repo.task(new).trials == 1
    with pytest.raises(ThinSpecError, match="neither the check"):
        repo.run_check(new, "echo hi")
    assert repo.done_task(new, "ok").status == "done"


def test_a_run_keeps_only_the_check_and_none_of_the_rest_of_the_shell_line(repo):
    tid = repo.start_task(parent="instrument", title="t", check="c", check_cmd="pytest -q tests",
                          budget={"trials": 3}).id
    line = "cd ~/secret/project && cat > notes.py <<'EOF'\nTOKEN = 'abc'\n" + "x = 1\n" * 200 + "EOF\npytest  -q tests 2>&1 | tail -3"
    repo.record_trial(tid, "s", line, None)
    other = repo.start_task(parent="instrument", title="u", check="c", budget={"trials": 3}).id
    repo.record_trial(other, "s", "export K=v; cargo build && pytest tests/test_x.py -k fast | tee out.log", False)
    repo.record_trial(other, "s", "cat <<'EOF' > a.txt\nsecret words\nEOF", None)
    cmds = [e["cmd"] for e in repo.ledger.events() if e.get("ev") == "trial"]
    assert cmds == ["pytest -q tests", "pytest tests/test_x.py -k fast", "cat <<'EOF' > a.txt"]
    assert not any("TOKEN" in c or "secret" in c or "x = 1" in c for c in cmds)
    assert (repo.task(tid).trials, repo.task(other).trials, repo.task(other).failed) == (1, 2, 1)
