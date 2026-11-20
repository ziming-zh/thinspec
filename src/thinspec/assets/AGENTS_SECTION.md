<!-- thinspec:start -->
## Working under ThinSpec

This repository tracks its design in `abstraction/` (a small graph of nodes with invariants and bans) and tracks implementation tasks against budgets with the `thinspec` MCP server. People maintain the abstraction and read results. Agents implement leaf tasks under it.

- Before implementing, call `overview`, then `context` for the node the work falls under. Its invariants and bans, and those of every node above it, apply. A banned approach is not retried.
- Declare the work with `task_start`: the parent node, a title, the check that verifies it, and your honest estimate as the budget, in what a person can judge: trials (how many runs of the check until the result is solid) and lines (how many lines of code change). Time is not budgeted. Tell the user the budget you set.
- When you cannot size the work with confidence (debugging, tuning, flaky behaviour), start with your best numbers and `confidence: "low"`, ask the user for theirs in your message, and go on without waiting. If they answer, record it with `task_budget`; if not, your numbers stand.
- Then read the check once: is a metric missing, so that the check could pass while the goal is not met? Add one with `task_metric` only when it clearly lowers the chance of reward hacking; otherwise record `none: true`. Corner cases are not a reason.
- If `task_start` lists checks that earlier work under the design passed, run each again before closing (`thinspec run <task> -- <command>` records the run), or drop one in `task_done` with the reason it no longer applies.
- Nothing counts your work automatically in this agent, so call `task_report` after each run of the check with the trials and the lines changed since your last report.
- A budget is an estimate, not a limit. When `task_report` says the estimate is reached, nothing stops: look at why the work costs more than expected, and tell the user if the cause is the design.
- When `task_report` says the task is far past its estimate, stop. Report what was tried, what keeps failing, and whether the failures point at the parent design. The user chooses: extend, step back and revise the design, or ban the approach. Record the choice with `task_decide`.
- Other sessions may be working here at the same time, in this agent or another; `overview` lists them with their tasks. A task another session holds is not yours: declare your own, or join theirs by name (`task_start` with its id) when you are continuing that very work.
- Close with `task_done` and the measured result, stated for someone who reads results and not code.
- Never write under `.thinspec/`. A change to `abstraction/` does not wait for the user's approval, but tell them at the end of the turn what you changed and why. To change a design, call `node_revise` first, then rewrite the node file: the earlier text is kept, so they can switch back.
- The spec is verified as the work goes on. When a task closes with a result, or after you changed code or ran the check under a node, read that node against it: record with `node_verify` why it still fits, revise it if the evidence overturns it or taught something new, or move what holds more generally up a level. After a revision, do the same for the node above it and the nodes under it. Go on until the overview lists no node to verify.
<!-- thinspec:end -->
