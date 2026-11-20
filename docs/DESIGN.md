# Design notes

## Where ThinSpec sits

ThinSpec is an extension of the coding agent, not an application that drives one. It never calls a model. It touches the agent in three places, and each uses a surface the agent already has:

| What | In Claude Code | In other agents |
|---|---|---|
| What the agent reads: the graph, the rules that bind a task | MCP tools, a skill, context at session start | MCP tools, a section in `AGENTS.md` |
| What gates the agent: the pause far past an estimate, and the verdict on a task | settings hooks, and the normal permission prompt for a verdict | the agent reports its own work; no gate yet |
| What you see: the graph, the budget, what needs a decision | a pane beside the transcript, a line above the prompt, and one command, `/thinspec`, that opens the pane (a plugin with a hooks module) | text in the conversation, `thinspec status` |

All logic and all state live in the `thinspec` command and the two folders in the repo. The Claude Code plugin only draws: it runs `thinspec state --json` after each edit or check run, at the end of each turn and every 15 seconds, and renders what it gets. Its decision buttons write nothing; they put the start of a sentence in the prompt box, so a decision always passes through the person's own words and the agent's `task_decide` call.

## From the idea to the mechanism

| Idea | Mechanism |
|---|---|
| No one holds the whole system; maintain a short, curated abstraction set | `abstraction/*.md`, one node per file, with line caps, and a cap on how many nodes sit under one, checked by `thinspec check` |
| Invariants a human can state in a line | `## Invariants` bullets on each node; shown to the agent at task start and when it is stopped |
| Ban list: paths never to take again, at any layer | `## Bans` bullets; a node's bans apply to everything under it (`context` returns the whole chain) |
| A wrong abstraction is a silent failure: agents patch it until it is green | Budgets on every task, as estimates; when work goes far past one, edits and check runs are refused and a person decides |
| Leaf tasks: estimate vs. actual; longer than expected → revisit the design above | The ledger records budget and actuals per task; a run of over-budget tasks flags the parent design |
| Downstream work can be delegated when it has a verifiable metric | A task cannot exist without a check; planned tasks with a check show as "ready to delegate" |
| The human reads results, not code | `task_done` requires a result statement; the viewer shows results and numbers, never diffs |
| The abstraction stays sound: each round of work is checked against the node it sits under, and a change to one node is carried to the node above it and the nodes under it | `task done` and the end of a turn of work record `verify_due` for the task's node; `thinspec revise` puts the nodes next to the one revised up as well. `thinspec check` lists every node owed a verification until it is revised or recorded as still fitting (`thinspec verify`, `node_verify`) |
| The abstraction evolves (v1 … v7); keep the reasons | `thinspec revise` archives the node to `abstraction/history/<id>.v<N>.md` and logs the reason |
| Agents may write into the abstraction, people accept | An agent edit under `abstraction/` goes ahead and is logged, and the agent is told to report it when the turn ends. A revision keeps the earlier text to switch back to. A project can set `approvals` to be asked first |
| Honest numbers when agents both write and review | Counting is done by hooks, outside the agent; the ledger is append-only and cannot be edited by the agent |

## Data model

**Nodes** are Markdown files with a flat header (`id`, `title`, `kind`, `parent`, `version`). `kind` is `core` for the root. Below it a node is a `design`, a decision that sets the direction, or a `component`, a part of the system that carries designs out; a component sits under the design it carries out (one that would serve every design is a stage of the code and is split into the parts that carry each; only a part carrying no design of its own sits under the core), and a design never sits under a component (`thinspec check` reports one that does). Wherever the tree is listed, a node's designs come before its components. Within each kind an optional `order: N` in the header places a node among those beside it, so the tree reads in the order of its story; nodes with no `order` follow, by id. Only the header, the summary paragraph and the `Invariants` and `Bans` lists are parsed. Everything else in the file is left alone.

**The ledger** (`.thinspec/ledger.jsonl`) is the only store of task state. Current state is recomputed by replaying it (`ledger.replay`). Event types:

| Event | Fields | Effect |
|---|---|---|
| `task_planned` | task, parent, title, check, check_cmd?, budget?, set_by? | creates a task |
| `task_started` | task, budget?, set_by? | planned → active |
| `budget_confirmed` | task | a person approved the agent's budget |
| `patch` | task or null, file, lines | one file edit (null task = untracked) |
| `trial` | task, cmd, passed (true, false or null) | one run of the check |
| `time` | task, seconds | active time |
| `report` | task, trials, patches, minutes | self-reported work (agents without hooks) |
| `alarm` | task, node, exhausted, usage | far past the estimate: active → blocked (`exhausted` names the metrics past the line) |
| `decision` | task, choice, note, extend? | extend → active; step_back / ban / abandon → closed |
| `task_done` | task, result | closed as done |
| `node_added`, `node_revised`, `ban_added`, `abstraction_edited` | node, … | design-level history. A restore is a `node_revised` that also carries `restored`, the version whose text came back |
| `verify_due` | node, task, after | a round of work under the node ended: `after` is `result` (the task closed with one) or `work` (a turn ended having changed code or run the check). The node is owed a verification |
| `node_verified` | node, version, note | the node was verified and still fits. A node is owed a verification while its latest `verify_due`, or a `node_revised` of the node above it or of a node under it, is later than its own latest `node_added`, `node_revised` or `node_verified` |
| `node_moved` | node, from, to, reason | the node sits under another one: only its `parent` changes. It counts as a change to the node, so the nodes now next to it are owed a verification, and so is the node it left |
| `node_renamed` | from, to | the same node under a new id: its tasks and its earlier events follow it |
| `node_retired` | node, into?, version, reason | the node leaves the graph; its text is archived and its tasks move to `into` |
| `session` | session, agent, host, dir | who a session is: its agent, its machine and its checkout. Written once, the first time the session works |
| `task_joined` | task, session | a session works on a task another one started; the budget is unchanged |

Task ids are `T1`, `T2`, … in creation order.

Every event a session causes carries its id in `session`: the hooks sign what they count, and the MCP server and the command line sign what they record. From these the replay knows, for each task, the session that started it and the sessions that worked on it, and for each session its latest work. An event with no `session` came from a person's terminal.

**Session files** (`.thinspec/sessions/<id>.json`, not committed) hold what only matters within one agent session: which task it is bound to, unflushed time, which warnings were already given, and where its turn stands (in a tool call, between two, or ended). They are not part of the record: they say what a session in this checkout is doing right now, which the record cannot.

## Budgets

A budget is any of `trials`, `patches`, `minutes`, and it is an estimate, not a limit. Two points on each metric matter:

- **The estimate** (`actual >= budget`). Nothing stops. The agent gets one note per metric telling it to look at why the work costs more than expected, and to tell the person if the cause is the design. The design shows *watch* while such a task is active.
- **The alarm line** (`actual >= alarm_ratio × budget`, twice the estimate by default). The task is paused and a person decides. The alarm is raised at the moment the agent tries the next unit of work past the line, not when it reaches the line, so a task whose last trial before it passes can still close as done.

For self-reported work the note comes with the report that reaches the estimate, and the alarm is raised when a report takes a metric strictly past the line.

## Hook rules (Claude Code)

All hooks call `thinspec hook`, which reads the event on stdin, prints at most one JSON decision, and always exits 0. Errors go to `.thinspec/hook-errors.log`.

**SessionStart** adds the protocol and the current graph as context.

**One command for the person, one skill for the agent.** `/thinspec` is the person's and only opens the pane; the plugin registers it. The rules the agent works by are a skill of their own name, `thinspec-rules`, which `thinspec init` writes to `.claude/skills/` with `user-invocable: false`, so it is the agent that loads it and it is not in the person's command menu. Earlier versions wrote the rules as the skill `thinspec`, which answered `/thinspec` by loading them into the conversation; `thinspec init` removes that file when it is the one it wrote.

**PreToolUse**

In this table "ask" means: put to the person first where the project sets `approvals` to `"ask"`. By default (`"tell"`) the call goes ahead, and the agent gets a note, once a turn, to report it to the person when the turn ends. Two things hold in either setting: a `task_decide`, from the tool or the shell, always asks, and nothing asks in a session the person set to bypass permissions.

| Tool call | Condition | Decision |
|---|---|---|
| `Edit`/`Write`/… under `.thinspec/` | always | deny |
| `Edit`/`Write`/… under `abstraction/` | `protect_abstraction` | ask |
| `Edit`/`Write`/… on code | no task, gate applies | deny (with how to declare a task) |
| `Edit`/`Write`/… on code | task paused, or past the alarm line | raise alarm, deny (with what to report) |
| `Bash` writing to `.thinspec/` | always | deny |
| `Bash` running `thinspec task start/add/decide`, `node add/rename/retire/move`, `revise`, `verify <node>`, `restore`, `ban` | always | ask |
| `Bash` that is a run of the check | task paused, or past the alarm line | raise alarm, deny |
| `task_start` (MCP) | `confirm_budget`, unless the person already set the budget | ask |
| `task_decide`, `ban_add`, `node_revise`, `node_verify`, `node_move` (MCP) | always | ask |
| anything else | | no decision |

**PostToolUse / PostToolUseFailure**

- `Edit`/`Write`/… on code → `patch` (against the task, or untracked)
- `Edit`/`Write`/… under `abstraction/` → `abstraction_edited`
- `Bash` that is a run of the check → `trial` (`passed: false` on the failure event)
- `task_start` → bind the session to the task; record `budget_confirmed` if the person was asked
- after any tool: a one-time note for each metric that has reached its estimate
- after a call that went ahead unasked: a note, once a turn, that the person is owed a report of it when the turn ends (`Stop` clears it)

**Stop** flushes the time counted during the turn. If the turn changed code or ran the check under a task, and the task's node has not been verified since, it records `verify_due` for that node; the agent is told at its next tool call.

**Time.** A tool's run time (PreToolUse → PostToolUse of the same step) counts in full, up to four hours. Other gaps count up to `idle_cap_seconds`. The gap after a `Stop`, while the agent waits for the next prompt, is not counted. The wait after ThinSpec asked the person something counts up to the idle cap, not as a tool run.

**Which task a session works on.** The task it started or joined through `task_start`; otherwise, if exactly one task is open in the repo and no other session holds it, that one; otherwise none.

## Parallel sessions

Several sessions can work in one project at once: in one agent or in several, and each on its own task. They share one record, so they share one picture.

**Who a session is.** Its id is the agent's own: Claude Code gives the same id to its hooks (`session_id`) and to the processes it starts (`CLAUDE_CODE_SESSION_ID`), so the hooks, the MCP server and a `thinspec` command run by the agent all sign alike. An agent with no such variable gets an id from the MCP server process, one per connection, and `THINSPEC_SESSION` sets one outright. The agent's name comes from the hook command (`thinspec hook --agent <name>`, `claude-code` by default) or from what the MCP client calls itself (`codex-mcp-client` is recorded as `codex`). A session is shown as the agent and the first four characters of its id, such as `codex 60b8`.

**What a session is doing.** `Repo.sessions()` lists every session that has an open task or was heard from in the last `quiet_after_minutes` (15 by default):

| State | Meaning | Known from |
|---|---|---|
| working | in a turn | a recent event in the record, or its session file |
| waiting | its turn ended, or it asked its person something | its session file (this checkout only) |
| quiet | not heard from for `quiet_after_minutes` | the time of its last event |

A session whose task is closed and that has gone quiet leaves the list. `thinspec state --json` carries the list as `sessions`, with `me` set on the one that asks (`--session <id>`, or the id in the environment). `thinspec status`, the overview tool and the context at session start print it.

**Holding a task.** A session holds a task while its latest work is on it and it is not quiet. A session with no task of its own never counts its edits against a task another session holds: they are untracked, and the nudge names the other sessions and their tasks. To work on the same task, a session names it in `task_start`, which records `task_joined` and leaves the budget alone. Once every holder is quiet, the only open task is picked up by default again, as before.

**What the agent is told.** The other sessions and their tasks: in the context at session start, in the overview, in the answer to `task_start`, and in the nudge. And once per file and task, after an edit to a file that another session's open task has edited: which task, which session, and when. Nothing is refused on these grounds.

**A picture, and names to press.** Where the surface has `Svg` the tree is one picture, built as markup from the state: the node in view across the top, a spine down from it, a branch over each row of the nodes under it, and under each box its open tasks by name and its finished ones counted. In the plugin API (Claude Code 2.1.325) only a `Button` takes a press, a `Button` holds only text, and an `Svg` is an image with no press. So the nodes of the next level are `Button`s by name under the picture, in a row that says what they are, and a press sets the node zoomed into. Two versions gave the picture up to get the press onto the box itself, one in loose boxes and one in boxes joined by lines made of empty bordered boxes; the person found both more cluttered than the picture, and it came back.

**In a terminal.** A terminal has no `Svg`. There the same tree is drawn with `Box` and `Text`: the node in view in a box across the top, each node under it in a box whose name is a `plain` `Button`, joined by `Text`s of line glyphs. The rows a join has to span are counted from what hangs there, and how many boxes sit side by side comes from the pane's width (`bodyColumns`).

**Told short, and a digest for the work.** Under the tree a level is one sentence a part, its rules counted, and each part opens on its own press (the parts opened are kept in the session's state, per node). A node's finished tasks are counted and never listed. In their place is the node's digest, four short lists kept in the record by `node_digest` events (`features`, `reverts`, `positive`, `negative`), each capped at five lines of 160 characters and rewritten whole, so that an agent adding to a full section has to merge or drop. ThinSpec calls no model: the agent that did the work writes it. A version number goes up only on a revision marked as a decision; a rewording is kept as `history/<id>.v<N>.e<k>.md`. Neither versions nor task ids are drawn.

**Citing a point.** Every point under the tree is drawn as plain `Button`s, one a line: the desktop app draws a button on one line and cuts what does not fit, so a point is laid out in lines to the pane's width (`bodyColumns`, with room left for a proportional font), each line citing the whole point, all lit together by a hover `scope`. A press reads the prompt box and puts `> <node> · <point>: <text>` on a line of its own (`$.prompt.fill`, mode `replace`, the caret on the line after it). The box holds one such quote: the quote last written is kept in the session's state, and a press puts the new one where that line stands, leaving every other line; if the person edited it, it is no longer found and the new quote goes after what they typed. A press reaches a plugin with no modifier keys (2.1.325), so a Command-press that adds a second quote cannot be told from a plain one. The plugin API of Claude Code 2.1.325 has no call that starts dictation, so a press cannot start voice input; the app's own dictation shortcut works on the box afterwards.

**Only what is there.** Nothing is drawn or listed that the person did not put there: under a design, proposing a component is one button that starts their sentence. Under the whole tree only a task that waits for their call is listed, with its measures and Extend, Step back and Ban; a planned task has its Hand to a subagent button on one line where its node is zoomed into, and a check's text stays in the record.

**What is drawn.** The plugin asks for the state with its own session id (`$.session.id()`), so `me` is set and that session reads as "you". In the graph a task that is open is a row under its node: its name, and under it who is on it, the metric it is furthest into and its id, which is the first to go where the row is narrow. Finished tasks are a count by outcome. No mark carries an id alone: an id is a handle for the record, and a reader of the graph has no use for it. Under the graph each session has a row, and a press on it shows the design its task is under. The line above the prompt leads with a task that waits for a verdict, then this session's task, then the others with their sessions' names. Besides the tool calls and turn ends of its own session, the plugin reads the state every 15 seconds, which is how the other sessions' work reaches a pane whose own session is idle.

**When a read fails.** A read of the state can fail for a moment: a timeout, or a node file caught halfway through a rename. That says nothing about the repo, so the pane keeps what it read before, adds one line with the reason (the last line `thinspec` wrote), and reads again at the next trigger. Only `thinspec`'s own answer that there is no repo here empties the pane and stops the reading. A first read that fails for any other reason shows that reason, not the advice to run `thinspec init`.

**Not built yet.** The record is one file in one checkout. Sessions that share a folder share it at once; sessions in separate worktrees or on separate machines each have their own copy, and their copies collide when merged. The design calls for one log per checkout, merged on reading.

## Design health

For each node, take the tasks started since its last revision, newest first, and count how many in a row were paused. A task that finished without a pause ends the count. `stepback_alarms` or more → *step back*; one → *watch*; an active task past its estimate → *watch*. A parent with `stepback_alarms` flagged children is flagged too, and a parent with one is *watch*. A node with no tasks of its own since its last revision, which is the usual state of a design whose work is done by its components, takes its level from the nodes under it: *watch* if one of them is, otherwise *on budget* if one of them has work within budget.

## Code map

| File | Role |
|---|---|
| `store.py` | node files: parse, validate, add a ban, archive and bump |
| `ledger.py` | append-only log, `Task`, `replay` |
| `core.py` | `Repo`: every operation, health, text for terminals and agents |
| `hooks.py` | Claude Code hook handlers |
| `mcp_server.py` | stdio MCP server (JSON-RPC, no SDK) |
| `viewer.py`, `assets/viewer.html` | the state as JSON (`thinspec state`), the optional HTML page, the local server |
| `install.py` | `thinspec init` |
| `cli.py` | the command line |
| `claude-plugin/hooks/register.tsx` | the Claude Code pane, the line above the prompt and the `/thinspec` command |
| `claude-plugin/tests/` | tests for the plugin, run with `claude plugin test ./claude-plugin` |
| `.claude-plugin/marketplace.json` | makes this repository installable as a Claude Code marketplace |
