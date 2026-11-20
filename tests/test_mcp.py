import json
import subprocess
import sys
from pathlib import Path

import pytest

from thinspec.core import Repo
from thinspec.mcp_server import PROTOCOL_VERSIONS, TOOLS, call_tool, handle_message

SRC = str(Path(__file__).resolve().parents[1] / "src")


def rpc(repo, method, params=None, msg_id=1):
    return handle_message({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}},
                          lambda: Repo(repo.root))


def call(repo, name, **args):
    res = rpc(repo, "tools/call", {"name": name, "arguments": args})["result"]
    return res["content"][0]["text"], res["isError"]


def test_initialize_echoes_a_known_version_and_falls_back_otherwise(repo):
    res = rpc(repo, "initialize", {"protocolVersion": "2024-11-05"})["result"]
    assert res["protocolVersion"] == "2024-11-05" and res["capabilities"] == {"tools": {}}
    assert res["serverInfo"]["name"] == "thinspec"
    assert rpc(repo, "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == PROTOCOL_VERSIONS[0]


def test_notifications_get_no_reply_and_unknown_methods_get_an_error(repo):
    assert handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, lambda: None) is None
    assert rpc(repo, "resources/list")["error"]["code"] == -32601
    assert rpc(repo, "ping")["result"] == {}


def test_every_tool_has_a_schema_and_a_handler(repo):
    listed = rpc(repo, "tools/list")["result"]["tools"]
    assert [t["name"] for t in listed] == [t["name"] for t in TOOLS]
    for tool in listed:
        assert tool["description"] and tool["inputSchema"]["type"] == "object"
        try:
            call_tool(repo, tool["name"], {})      # bad input must be a clean error, never "Unknown tool"
        except Exception as exc:  # noqa: BLE001
            assert "Unknown tool" not in str(exc)


def test_a_full_task_through_the_tools(repo):
    text, err = call(repo, "overview")
    assert not err and "instrument" in text
    text, err = call(repo, "task_start", parent="instrument", title="Hook backward ops", check="hooks match",
                     trials=2, patches=10)
    assert not err and "Started T1" in text and "One unique hook point per step." in text
    text, err = call(repo, "task_report", task="T1", trials=2, patches=4)
    assert not err and "2/2 trials" in text and "The estimate is reached. This stops nothing" in text
    text, err = call(repo, "task_report", task="T1", trials=2)
    assert "4/2 trials" in text and "estimate" not in text and repo.task("T1").status == "active"   # said once
    text, err = call(repo, "task_report", task="T1", trials=1)
    assert "far past its estimate" in text and repo.task("T1").status == "blocked"
    text, err = call(repo, "task_decide", task="T1", choice="ban", note="names shift",
                     ban_text="Stable node names across steps")
    assert not err and repo.task("T1").status == "banned"
    assert "Stable node names across steps" in call(repo, "context", node="instrument")[0]


def test_step_back_through_the_tools_opens_a_new_version(repo):
    call(repo, "task_start", parent="instrument", title="t", check="c", trials=1)
    text, err = call(repo, "task_decide", task="T1", choice="step_back", note="design misses the global view")
    assert not err and "now v2" in text and repo.node("instrument").version == 2


def test_errors_come_back_as_tool_errors_not_crashes(repo):
    text, err = call(repo, "task_start", parent="instrument", title="No budget", check="c")
    assert err and "budget" in text
    text, err = call(repo, "context", node="nope")
    assert err and "No node" in text
    text, err = call(repo, "no_such_tool")
    assert err and "Unknown tool" in text
    res = handle_message({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                          "params": {"name": "overview", "arguments": {}}}, lambda: None)["result"]
    assert res["isError"] and "thinspec init" in res["content"][0]["text"]


def test_stdio_round_trip_in_a_subprocess(repo):
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "overview", "arguments": {}}},
    ]
    stdin = "\n".join(json.dumps(m) for m in lines) + "\nnot json\n"
    proc = subprocess.run([sys.executable, "-m", "thinspec", "--root", str(repo.root), "mcp"],
                          input=stdin, capture_output=True, text=True, env={"PYTHONPATH": SRC, "PATH": ""}, timeout=30)
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, 3, None]
    assert replies[2]["result"]["content"][0]["text"].startswith("ThinSpec")
    assert replies[3]["error"]["code"] == -32700


def test_with_the_official_mcp_client(repo):
    """The hand-written server must satisfy a real MCP client, not just our own reading of the spec."""
    mcp = pytest.importorskip("mcp")
    import asyncio

    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "thinspec", "--root", str(repo.root), "mcp"],
                                       env={"PYTHONPATH": SRC})
        async with stdio_client(params) as (read, write):
            async with mcp.ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                started = await session.call_tool("task_start", {"parent": "instrument", "title": "Via SDK",
                                                                 "check": "c", "trials": 3})
                bad = await session.call_tool("context", {"node": "nope"})
                return init, tools, started, bad

    def field(obj, camel, snake):  # the SDK renamed its fields between major versions
        return getattr(obj, camel) if hasattr(obj, camel) else getattr(obj, snake)

    init, tools, started, bad = asyncio.run(run())
    assert field(init, "serverInfo", "server_info").name == "thinspec"
    assert {t.name for t in tools.tools} >= {"overview", "task_start", "task_decide"}
    assert not field(started, "isError", "is_error") and "Started T1" in started.content[0].text
    assert field(bad, "isError", "is_error")
    assert repo.task("T1").title == "Via SDK"


def test_a_budget_is_asked_for_in_runs_and_lines_and_a_guess_tells_the_agent_to_ask(repo):
    tools = {t["name"]: t for t in TOOLS}
    for name in ("task_start", "task_budget", "task_decide"):
        props = set(tools[name]["inputSchema"]["properties"])
        assert {"trials", "lines"} <= props and not {"minutes", "patches"} & props, name

    text, err = call(repo, "task_start", parent="instrument", title="Debug the kernel",
                     check="boots 20 times in a row", trials=6, lines=80, confidence="low")
    assert not err and text.startswith("You marked this estimate as a guess. Ask the user")
    assert "do not wait for the answer" in text and "task_budget" in text and "Budget: 6 trials, 80 lines" in text
    assert repo.task("T1").guess
    text, err = call(repo, "task_budget", task="T1", trials=40, note="it took 30 boots last time")
    assert not err and "now 40 trials, set by the user" in text
    assert not repo.task("T1").guess and repo.task("T1").budget == {"trials": 40}

    text, err = call(repo, "task_start", parent="instrument", title="Rename a flag", check="c", trials=1, lines=10)
    assert not err and text.startswith("Started T2") and not repo.task("T2").guess
    text, err = call(repo, "task_report", task="T2", trials=1, lines=25)     # an agent with no hooks reports lines
    assert not err and "25/10 lines" in text and "far past its estimate" in text

    # A budget given the older way is still read, though no tool offers it.
    text, err = call(repo, "task_start", parent="instrument", title="Old style", check="c", minutes=30, patches=5)
    assert not err and repo.task("T3").budget == {"patches": 5, "minutes": 30}


def test_a_session_with_no_hooks_is_in_the_record_under_the_name_its_agent_gives(repo):
    from thinspec.mcp_server import agent_name

    assert [agent_name(n) for n in ("claude-code", "codex-mcp-client", "Cursor", None)] == [
        "claude-code", "codex", "cursor", "agent"]
    client = {"session": "c0dec0de", "agent": None, "noted": False}

    def send(method, params):
        return handle_message({"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                              lambda: Repo(repo.root), client)["result"]

    send("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "codex-mcp-client", "version": "1"}})
    send("tools/call", {"name": "task_start", "arguments": {"parent": "instrument", "title": "From Codex",
                                                           "check": "c", "trials": 3}})
    send("tools/call", {"name": "task_report", "arguments": {"task": "T1", "patches": 2}})
    state = repo.state()
    assert state.tasks["T1"].started_by == "c0dec0de" and state.tasks["T1"].patches == 2
    assert (state.sessions["c0dec0de"].agent, state.sessions["c0dec0de"].task) == ("codex", "T1")
    assert [(r["name"], r["task"], r["state"]) for r in repo.sessions()] == [("codex c0de", "T1", "working")]

    # A second session, in another agent, is told of the first when it starts its own task,
    # sees it in the overview, and joins the first one's task by naming it.
    other = {"session": "abcd1234", "agent": "claude-code", "noted": False}

    def call_as(name, **args):
        res = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": name, "arguments": args}}, lambda: Repo(repo.root), other)["result"]
        assert not res["isError"], res
        return res["content"][0]["text"]

    started = call_as("task_start", parent="instrument", title="From Claude", check="c", patches=4)
    assert "Started T2" in started and "Other sessions at work" in started and 'codex c0de: T1 "From Codex"' in started
    overview = call_as("overview")
    assert "claude-code abcd (this session): T2" in overview and "codex c0de: T1" in overview
    joined = call_as("task_start", task="T1")
    assert "Joined T1" in joined and "joining does not change it" in joined
    assert list(repo.state().tasks["T1"].sessions) == ["c0dec0de", "abcd1234"]


def test_node_revise_names_the_nodes_to_read_again_and_node_verify_records_the_reading(repo):
    text, is_error = call(repo, "node_revise", node="instrument", reason="try another hook point", decision=True)
    assert not is_error and "read again the nodes next to it (core)" in text and "node_verify" in text
    overview, _ = call(repo, "overview")
    assert "To verify." in overview and "core  since instrument v2" in overview

    text, is_error = call(repo, "node_verify", node="core", note="")
    assert is_error and "Say why 'core' still follows" in text
    text, is_error = call(repo, "node_verify", node="core", note="the core names no hook point")
    assert not is_error and "No other node is owed a verification" in text
    assert "To verify." not in call(repo, "overview")[0]


def test_task_done_says_the_result_is_a_round_of_work_to_verify_the_node_against(repo):
    text, _ = call(repo, "task_start", parent="instrument", title="Hook backward ops", check="hooks match", trials=2)
    tid = text.split()[1]
    text, is_error = call(repo, "task_done", task=tid, result="one hook per step")
    assert not is_error and "verify the node against %s's result" % tid in text
    for outcome in ("It still fits", "overturns", "something new was learned", "move it up a level"):
        assert outcome in text                               # the four ways a verification can end
    assert "instrument  against %s's result" % tid in call(repo, "overview")[0]
    call(repo, "node_verify", node="instrument", note="the result is what the node says")
    assert "To verify." not in call(repo, "overview")[0]


def test_node_move_puts_a_node_at_another_level_and_says_what_to_verify(repo):
    repo.add_node("probe", "Probe", "instrument", "Measure the transfer.", ["holds"])
    text, is_error = call(repo, "node_move", node="probe", under="core", reason="it holds for every design")
    assert not is_error and "'probe' now sits under 'core'" in text and "To verify against the move: core, instrument." in text
    text, is_error = call(repo, "node_move", node="probe", under="core", reason="")
    assert is_error and "needs a reason" in text


def test_task_start_asks_once_whether_a_metric_is_missing_and_task_metric_answers_it(repo):
    text, err = call(repo, "task_start", parent="instrument", title="Raise hit rate", check="hit rate >= 90%",
                     trials=3)
    assert not err and "Is a metric missing" in text and "clearly lowers the chance of reward hacking" in text
    assert "corner cases" in text
    text, err = call(repo, "task_metric", task="T1", metric="stale reads = 0 on workload B")
    assert not err and "your own" in text
    task = Repo(repo.root).task("T1")
    assert task.check == "hit rate >= 90%"                                    # the check as first written is kept
    assert task.full_check == "hit rate >= 90%; also: stale reads = 0 on workload B (the agent's own)"
    assert "metric 1 added: stale reads = 0 on workload B (the agent's own)" in Repo(repo.root).task_text(task)
    text, err = call(repo, "task_metric", task="T1", none=True)
    assert not err and "no metric is missing" in text
    text, err = call(repo, "task_metric", task="T1")
    assert err and "Say the metric" in text


def test_the_persons_word_on_an_added_metric_clears_the_mark_or_drops_it(repo):
    call(repo, "task_start", parent="instrument", title="t", check="c", trials=1)
    call(repo, "task_metric", task="T1", metric="memory <= 1 GB")
    call(repo, "task_metric", task="T1", metric="p99 latency <= 2 ms")
    r = Repo(repo.root)
    task = r.set_metric("T1", 1, text="memory <= 1 GB per node")
    assert task.metrics[0] == {"text": "memory <= 1 GB per node", "own": False}
    task = r.set_metric("T1", 2, drop=True)
    assert [m["text"] for m in task.metrics] == ["memory <= 1 GB per node"]
    assert r.done_task("T1", "ok").status == "done"                          # nothing waits on a metric


def test_no_metric_added_lists_nothing_as_owed(repo):
    call(repo, "task_start", parent="instrument", title="t", check="c", trials=1)
    r = Repo(repo.root)
    assert r.to_verify() == [] or all(row["node"] != "instrument" for row in r.to_verify())
    text, err = call(repo, "task_done", task="T1", result="done")
    assert not err
