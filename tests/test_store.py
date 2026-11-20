import pytest

from thinspec import ThinSpecError, store
from thinspec.config import DEFAULTS

NODE = """---
id: instrument
title: Instrument: where we hook
kind: design
parent: core
version: 2
---

Where we hook into
each step.

## Invariants

- One unique hook point
  per step.
* Hooks never change results.

## Notes

- not a ban, not an invariant

## Bans

- Stable node names across steps
"""


def test_parse_node_reads_header_summary_and_lists():
    n = store.parse_node(NODE)
    assert (n.id, n.kind, n.parent, n.version) == ("instrument", "design", "core", 2)
    assert n.title == "Instrument: where we hook"          # only the first colon splits
    assert n.summary == "Where we hook into each step."
    assert n.invariants == ["One unique hook point per step.", "Hooks never change results."]
    assert n.bans == ["Stable node names across steps"]


def test_parse_node_without_header_falls_back_to_file_name_and_h1():
    n = store.parse_node("# Core idea\n\nJust text.\n", fallback_id="core")
    assert (n.id, n.title, n.kind, n.parent, n.version) == ("core", "Core idea", "core", None, 1)
    assert n.summary == "Just text."


def test_add_ban_appends_inside_existing_section_and_creates_one(tmp_path):
    p = tmp_path / "instrument.md"
    p.write_text(NODE)
    node = store.parse_node(NODE, path=p)
    store.add_ban(node, "Steady-state   interception at every node")
    again = store.parse_node(p.read_text(), path=p)
    assert again.bans == ["Stable node names across steps", "Steady-state interception at every node"]
    assert again.invariants == node.invariants                 # nothing else moved

    q = tmp_path / "plain.md"
    q.write_text("---\nid: plain\n---\n\nText.\n")
    store.add_ban(store.parse_node(q.read_text(), path=q), "Never do X")
    assert store.parse_node(q.read_text()).bans == ["Never do X"]


def test_archive_and_bump_keeps_old_text_and_raises_version(tmp_path):
    p = tmp_path / "instrument.md"
    p.write_text(NODE)
    old, new, archived = store.archive_and_bump(tmp_path, store.parse_node(NODE, path=p))
    assert (old, new) == (2, 3)
    assert archived.read_text() == NODE
    assert store.parse_node(p.read_text()).version == 3
    hist = store.history(tmp_path, "instrument")
    assert [(v, n.title) for v, n in hist] == [(2, "Instrument: where we hook")]


def test_problems_reports_structure_and_size(repo):
    cfg = dict(DEFAULTS, max_lines_per_node=3, max_lines_view=5)
    (repo.abs_dir / "orphan.md").write_text("---\nid: orphan\nparent: nowhere\n---\n\nx\n\n## Invariants\n\n- y\n")
    found = " ".join(store.problems(repo.abs_dir, cfg))
    assert "parent 'nowhere' that does not exist" in found
    assert "cap is 3" in found and "The view of 'core', it and the 1 nodes under it" in found and "cap is 5" in found


def test_the_cap_counts_a_view_not_the_whole_spec(repo):
    from thinspec.config import load_config
    from thinspec.core import abstraction_line

    # A chain three levels deep: every view is a node and the one under it, each well inside the
    # cap, while the whole spec is not. Depth is not capped; what one view holds is.
    for child, parent in (("probe", "instrument"), ("window", "probe")):
        repo.add_node(child, child.title(), parent, "One line of story.", ["holds"])
    nodes = store.load_nodes(repo.abs_dir)
    total = sum(n.lines for n in nodes.values())
    largest = max(v["lines"] for v in store.views(nodes))
    cfg = dict(DEFAULTS, max_lines_view=largest)
    assert total > largest and not [p for p in store.problems(repo.abs_dir, cfg) if "view" in p]
    found = store.problems(repo.abs_dir, dict(DEFAULTS, max_lines_view=largest - 1))
    over = [v["node"] for v in store.views(nodes) if v["lines"] > largest - 1]
    assert sorted(p.split("'")[1] for p in found if "The view of" in p) == sorted(over)   # each view over it, by name
    size = repo.size()
    assert size["view_lines"] == max(v["lines"] for v in store.views(repo.nodes()))
    assert abstraction_line(size).startswith("Abstraction: %d nodes; largest view '" % len(nodes))
    # A project set up by an earlier version capped the whole spec: that number now caps a view.
    (repo.root / ".thinspec" / "config.json").write_text('{"max_lines_total": 40}', encoding="utf-8")
    assert load_config(repo.root)["max_lines_view"] == 40


def test_problems_reports_a_layer_that_is_too_wide(repo):
    for i in range(5):
        store.create_node(repo.abs_dir, "d%d" % i, "Design %d" % i, "core", "x", ["holds"])
    found = " ".join(store.problems(repo.abs_dir, dict(DEFAULTS)))      # 'instrument' and five more
    assert "Node 'core' has 6 designs under it; the cap is 5" in found and "not components of the design" in found
    wider = dict(DEFAULTS, max_children=6)
    assert "under it; the cap" not in " ".join(store.problems(repo.abs_dir, wider))


def test_the_width_cap_counts_designs_and_components_apart(repo):
    # Three designs and four parts shared by them, as in Neutrino: seven under the core, five of neither kind.
    for i in range(2):
        store.create_node(repo.abs_dir, "d%d" % i, "Design %d" % i, "core", "x", ["holds"])
    for i in range(4):
        store.create_node(repo.abs_dir, "c%d" % i, "Part %d" % i, "core", "x", ["holds"], kind="component")
    assert "under it; the cap" not in " ".join(store.problems(repo.abs_dir, dict(DEFAULTS)))
    for i in range(4, 6):
        store.create_node(repo.abs_dir, "c%d" % i, "Part %d" % i, "core", "x", ["holds"], kind="component")
    found = " ".join(store.problems(repo.abs_dir, dict(DEFAULTS)))
    assert "Node 'core' has 6 components under it; the cap is 5" in found and "designs under it" not in found


def test_the_guidance_says_a_node_is_a_component_named_for_what_it_is():
    from thinspec.hooks import PROTOCOL
    from thinspec.install import ASSETS

    texts = {name: (ASSETS / name).read_text(encoding="utf-8") for name in ("ABSTRACTION_README.md", "SKILL.md")}
    texts["the context at session start"] = PROTOCOL
    for name, text in texts.items():
        assert "would survive a rewrite of the code" in text, name
        assert "decision that sets the direction" in text, name               # what a design is
        assert "carries designs out" in text or "carries a design out" in text, name   # what a component is
        assert "plain sentence" in text and "noun phrase" in text, name       # how each is named
        assert "an idea that would" not in text and "component of the system's design" not in text, name
    # A part that would serve every design is a stage of the code: it is split, not lifted to the core.
    for name in ("ABSTRACTION_README.md", "SKILL.md"):
        assert "stage of the code" in texts[name] and "split" in texts[name], name
        assert "under the core when it serves several" not in texts[name], name
        assert "parts of its architecture" not in texts[name], name           # components are not the code's boxes


def test_a_component_is_a_kind_of_node_that_sits_under_the_design_it_serves(repo):
    # 'instrument' is a design under the core. A component carries it out; another is shared by all.
    store.create_node(repo.abs_dir, "hook-table", "Hook table", "instrument", "Where hooks are kept.", ["holds"],
                      kind="component")
    store.create_node(repo.abs_dir, "a-shared-part", "A shared part", "core", "x", ["holds"], kind="component")
    store.create_node(repo.abs_dir, "zz-late-design", "Decide late", "core", "x", ["holds"])
    nodes = store.load_nodes(repo.abs_dir)
    assert nodes["hook-table"].kind == "component" and nodes["zz-late-design"].kind == "design"
    # Reading order: under a node its designs come first, then its components.
    assert [(n.id, depth) for n, depth in store.walk(nodes)] == [
        ("core", 0), ("instrument", 1), ("hook-table", 2), ("zz-late-design", 1), ("a-shared-part", 1)]
    assert store.problems(repo.abs_dir, dict(DEFAULTS)) == []

    with pytest.raises(ThinSpecError, match="does not sit under what carries it out"):
        store.create_node(repo.abs_dir, "wrong-way", "x", "hook-table")              # a design under a component
    with pytest.raises(ThinSpecError, match="design .* or a component"):
        store.create_node(repo.abs_dir, "odd", "x", "core", kind="module")
    # The same two mistakes made by hand in a file are reported by the check.
    (repo.abs_dir / "wrong-way.md").write_text(
        "---\nid: wrong-way\nkind: design\nparent: hook-table\n---\n\nx\n\n## Invariants\n\n- y\n")
    (repo.abs_dir / "odd.md").write_text("---\nid: odd\nkind: module\nparent: core\n---\n\nx\n\n## Invariants\n\n- y\n")
    found = " ".join(store.problems(repo.abs_dir, dict(DEFAULTS)))
    assert "Design 'wrong-way' sits under the component 'hook-table'" in found
    assert "Node 'odd' has kind 'module'" in found


def test_create_node_rejects_bad_ids_duplicates_and_second_root(repo):
    with pytest.raises(ThinSpecError):
        store.create_node(repo.abs_dir, "bad id", "x", "core")
    with pytest.raises(ThinSpecError):
        store.create_node(repo.abs_dir, "instrument", "x", "core")
    with pytest.raises(ThinSpecError):
        store.create_node(repo.abs_dir, "second-root", "x", None)
    with pytest.raises(ThinSpecError):
        store.create_node(repo.abs_dir, "child", "x", "missing")


def test_readme_and_history_are_not_nodes(repo):
    assert set(repo.nodes()) == {"core", "instrument"}
    repo.revise("instrument", "learned something", decision=True)
    assert set(repo.nodes()) == {"core", "instrument"}
    assert [n.id for n in store.chain(repo.nodes(), "instrument")] == ["core", "instrument"]


def test_the_guidance_says_a_revision_is_carried_to_the_nodes_next_to_it():
    from thinspec.hooks import MUTATING_CLI, PROTOCOL
    from thinspec.install import ASSETS

    texts = {name: (ASSETS / name).read_text(encoding="utf-8")
             for name in ("ABSTRACTION_README.md", "SKILL.md", "AGENTS_SECTION.md")}
    texts["the context at session start"] = PROTOCOL
    for name, text in texts.items():
        assert "the node above it and the nodes under it" in text, name
        assert "verify" in text, name                                    # how a second reading is recorded
    assert MUTATING_CLI.search('thinspec verify core --note "still follows"')   # it writes to the record
    assert not MUTATING_CLI.search("thinspec verify")                    # listing what is owed writes nothing


def test_nothing_proposed_ahead_of_time_is_read_from_a_node(repo):
    from thinspec.install import ASSETS
    from thinspec.viewer import build_data

    # A list of components a design might have, left in its file by an earlier version.
    path = repo.abs_dir / "instrument.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## Proposed\n\n"
                    "- Hook table: where hooks are kept, so each is found once.\n", encoding="utf-8")
    node = store.load_nodes(repo.abs_dir)["instrument"]
    assert node.invariants == ["One unique hook point per step."] and node.bans == []   # it is no rule
    assert "Hook table" not in node.summary and not hasattr(node, "proposed")          # nor part of the story
    rows = {n["id"]: n for n in build_data(repo)["nodes"]}
    assert "proposed" not in rows["instrument"] and "Hook table" not in str(rows["instrument"])
    # And no guidance asks anyone to write such a list.
    for name in ("SKILL.md", "ABSTRACTION_README.md"):
        assert "## Proposed" not in (ASSETS / name).read_text(encoding="utf-8"), name


def test_the_guidance_says_what_puts_a_node_up_to_be_verified_and_how_it_can_end():
    from thinspec.hooks import PROTOCOL
    from thinspec.install import ASSETS

    texts = {name: (ASSETS / name).read_text(encoding="utf-8") for name in ("SKILL.md", "AGENTS_SECTION.md")}
    texts["the context at session start"] = PROTOCOL
    for name, text in texts.items():
        assert "closes with a result" in text, name                      # a round of results
        assert "changed code or ran the check" in text or "changed code or run the check" in text, name
        assert "still fits" in text and "overturns" in text, name        # two of the ways it can end
        assert "up a level" in text, name                                # and what holds more generally moves up


def test_nodes_under_one_are_listed_in_the_order_their_headers_give(repo):
    from thinspec.viewer import build_data

    repo.add_node("ask", "Ask the person", "core", "Ask.", ["holds"])
    repo.add_node("check", "Check as the work goes", "core", "Check.", ["holds"])
    repo.add_node("zeta", "Zeta", "core", "A part.", ["holds"], kind="component")
    repo.add_node("alpha", "Alpha", "core", "A part.", ["holds"], kind="component")

    def listed():
        return [n.id for n in store.children(repo.nodes(), "core")]

    assert listed() == ["ask", "check", "instrument", "alpha", "zeta"]   # by id, designs first
    for node_id, place in (("instrument", 1), ("check", 2), ("zeta", 1)):
        path = repo.node(node_id).path
        path.write_text(path.read_text().replace("version: 1", "version: 1\norder: %d" % place))
    assert listed() == ["instrument", "check", "ask", "zeta", "alpha"]   # the order given, then the rest
    assert [n["id"] for n in build_data(repo)["nodes"]][1:] == listed()
    assert repo.overview_text().index("instrument  ") < repo.overview_text().index("check  ")


def test_a_restore_brings_back_the_text_and_leaves_the_node_where_it_now_sits(repo):
    repo.add_node("probe", "Probe", "instrument", "Measure the transfer.", ["holds"])
    repo.revise("probe", "measures per backend now", decision=True)
    path = repo.node("probe").path
    path.write_text(path.read_text().replace("Measure the transfer.", "Measure per backend."))
    repo.move_node("probe", "core", "it holds for every design")
    path.write_text(path.read_text().replace("version: 2", "version: 2\norder: 1"))

    assert repo.restore("probe", to=1) == (1, 3)
    node = repo.node("probe")
    assert node.summary == "Measure the transfer."                       # the first version's text
    assert node.parent == "core" and node.order == 1                     # where it sits now, not where it sat
    assert [n.id for n in store.children(repo.nodes(), "core")][0] == "probe"


def test_the_guidance_says_a_whole_node_is_moved_by_the_tool_never_by_hand():
    from thinspec.hooks import MUTATING_CLI
    from thinspec.install import ASSETS

    skill = (ASSETS / "SKILL.md").read_text(encoding="utf-8")
    assert "`node_move`" in skill and "Never edit a node's `parent:` line by hand" in skill
    assert "do not guess it: ask them" in skill                          # what only the person knows is asked for
    assert MUTATING_CLI.search('thinspec node move probe --under core --reason "x"')


def test_the_guidance_reads_a_changelog_only_to_enrich_the_nodes_already_there():
    from thinspec.install import ASSETS

    text = " ".join((ASSETS / "SKILL.md").read_text(encoding="utf-8").split())
    for words in ("changelog, release notes or a roadmap", "before any commit history",
                  "They add no section, no node and no move", "Skip fixes, packaging",
                  "rewrite that node's `features` line, not add a second one",
                  "A roadmap item is not built, so it is never a feature", "never commit by commit",
                  "the commit history, top down", "compare it with now, file by file through renames, counted per node",
                  "Read commits only for what is new or rewritten", "A node left alone says nothing"):
        assert words in text, words
