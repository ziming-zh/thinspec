# ThinSpec for Claude Code

The ThinSpec design graph and task budgets, drawn inside Claude Code. It needs the `thinspec` command on your PATH and a project set up with `thinspec init`; see the [main README](../README.md).

- `/thinspec` opens a pane beside the transcript. It is the only command. It draws the tree as one picture, one level to a view: the node in view across the top, a spine down from it, and on a branch each node under it, with its open work hanging under its box. A picture cannot be pressed, so the nodes of the next level are buttons by name under it, and a press zooms into that node; the path above leads back. A terminal draws no picture: there the same tree is boxes joined by lines, and the name in a box is the button. Under a design there is one `+ Propose a component` button, which starts your sentence; nothing is proposed ahead of time. Under the whole tree only a task that waits for your call is listed.
- While a task is open, one line above the prompt shows its budget as it is spent, this session's task first and then the other sessions' tasks by name.
- The graph reads with no key: a task that is open is a row with its name, who is on it and how far into the budget it is, and finished tasks are a count (`4 done · 1 banned`).
- With several sessions at work, each session has a row under the graph. The pane reads the state again every 15 seconds, so it follows sessions other than its own.
- When a task goes far past its estimate and is paused, the pane shows Extend, Step back and Ban. A button starts the sentence in the prompt box; you finish it and send it, and Claude records the decision.
- Where its node is zoomed into, a planned task shows Hand to a subagent on its line. It starts the sentence that hands the task over, with the planned budget, or stopping at `Budget: ` when none was planned.

The pane only draws. Every fact comes from `thinspec state --json`.

Develop it with `claude --plugin-dir ./claude-plugin`, check it with `claude plugin validate ./claude-plugin`, and run its tests with `claude plugin test ./claude-plugin`.
