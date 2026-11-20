---
name: thinspec-rules
description: The rules for working in a repository whose design is tracked by ThinSpec (it has an abstraction/ folder and a .thinspec/ folder). Use before implementing anything under a design, when a task reaches or goes far past its estimate, and before changing anything in abstraction/.
user-invocable: false
---

# Working under ThinSpec

This repository separates two things. People own the abstraction: a small graph of design nodes in `abstraction/`, each with invariants and a ban list. Agents own the implementation: leaf tasks under those nodes. The people here read results, not code, so the abstraction and the task ledger are how they keep track of a system that is too large for anyone to hold in their head.

The failure this setup exists to prevent: an agent given a task under a wrong design will usually make it work anyway, with patches and special cases, and everything looks green. The cost shows up much later. So here, effort that runs past its estimate is treated as information about the design, and it goes to a person instead of being absorbed by more patching.

## Before implementing

1. Call `overview` to see the graph, then `context` for the node the work falls under. The invariants and bans of that node and of every node above it apply. A banned approach is not retried, even in a different layer or under a different name. If it looks like the only way forward, say so to the user.
2. Call `task_start` with the parent node, a title, the check and a budget.
   - The check is what makes the task delegatable: a command, or a measurable criterion (for example "per-op overhead under 0.5% on workload X"). If the user gave no check, propose one and ask.
   - The budget is your honest estimate, stated in what a person can judge: trials (how many runs of the check until the result is solid) and lines (how many lines of code change, tests included). Time is measured, never budgeted. The user sees the budget and can change it; you do not wait for a confirmation. Don't pad it. An estimate that turns out wrong is the signal the user wants.
   - When you cannot size the work with confidence (debugging a kernel or a training run, tuning, flaky behaviour, code you have not read), the user often knows better than you how many tries it takes. Start with your best numbers and `confidence: "low"`, and ask them in your message: about how many runs of the check until the result is solid, and about how much code they expect to change. Say what your numbers are. Do not wait: go on with the work. If they answer, record their numbers with `task_budget`; if they do not, yours stand.
   - If a planned task already exists for this work, start that one by id.
3. Small changes that belong to no design (a typo, a log line) need no task. They are logged as untracked.

## While implementing

The lines your edits change and the runs of the check are counted for you. Every line an edit touches counts, so reworking the same lines counts them again: that is the effort the budget is about.

A budget is an estimate, not a limit. Reaching it stops nothing, and you do not stop either. You get one note per metric when it is reached. Take it as the moment to look at why the work costs more than expected:

- If it is ordinary work (more files than you counted, a slow test), carry on, and say so when you report.
- If the work keeps needing special cases the design did not anticipate, or an invariant does not hold, tell the user now. That observation is worth more to them than a passing check.

## When the work goes far past the estimate

At a set multiple of the estimate (twice it, unless the project changed `alarm_ratio`) the task is paused: edits and check runs for it are refused. Do not look for another way to keep going, such as shell edits or a new task for the same work. Give the user a short report:

- what was tried, in order
- what keeps failing, with the numbers
- whether the failures point at the parent design, and which invariant or assumption looks wrong

Then ask them to choose, and record the choice with `task_decide`:

- **extend**: the approach is right and needs more room
- **step_back**: the design above is wrong or incomplete; this closes the task and opens a new version of the parent node
- **ban**: this approach is not worth taking again; it goes on the parent's ban list
- **abandon**: drop the task

## Other sessions

Other sessions may be working in this project at the same time, in this agent or in another. The overview lists them: who, on which task, how far into the budget, and whether the session is working, waiting for its person or quiet.

- A task another session holds is not yours. Declare your own task. Only when you are continuing that very work, join it by name: `task_start` with the task's id. Joining does not change its budget.
- After an edit to a file that another session's open task has edited, you are told once. Read what that session changed before you go on, keep both tasks working, and tell the user if the two tasks pull the file in different directions.
- None of this stops you. It is there so that sessions do not undo each other's work without anyone knowing.

## Finishing

Call `task_done` with the measured result, stated so that someone who never opens the code can judge it: what was measured, on what, and the number.

## The digest of a node

The person does not read tasks: under a node they read its digest, a few lines in four parts. `features`: what the node can do now. `as_built`: where what is built departs from the node's story, and why. `reverts`: what was tried and turned back, and why. `positive` and `negative`: what runs of experiments came to, for and against. An ordinary check that passes is not a result.

- When a task closes, or a direction is turned back, rewrite the section it touches with `node_digest`. If nothing a person would decide from changed, leave it.
- A line is one short sentence in the person's terms: no task id, no file name, no count of tests.
- A section holds five lines at most, and what you give replaces it. Merge lines that say one thing and drop what no longer matters: never only append.
- A new leaf has only its story, and its approach is a plan until work under it has shown it. After you rewrite a digest, read the node's approach against it: what was turned back leaves the approach (revise the node), so the story and the digest never say different things.

## Verifying the spec

The spec is kept true by checking it as the work goes on. ThinSpec keeps count of which nodes are owed a verification and against what, in the overview under "To verify" and in `thinspec check`. The reading is yours.

- A node is owed a verification when a round of work under it ends: a task closes with a result (the answer to `task_done` says so), or your turn ends having changed code or run the check under it (you are told at your next tool call).
- A node is also owed one when the node above it and the nodes under it change: a revision is not finished at the node you revised.
- To verify a node, read it and the rules above it against what it is owed: the result, the change to the code, or the new text of the node next to it. Then settle which of four holds:
  - It still fits. Record why with `node_verify`, naming what you read it against.
  - The evidence overturns it. Revise it with `node_revise`, and say what the result showed that the node had wrong. When what the node should say instead is the user's to know, do not guess it: ask them, and go on with what does not depend on the answer.
  - Something new was learned that the node does not say: a rule, a ban, a missing component. Revise the node to add the rule, add the ban with `ban_add`, or tell the user in a line which component is missing.
  - It, or a rule in it, holds more generally than this node. Move it up a level. For a rule, revise the node above to take it and this node to drop it. For the whole node, call `node_move` with the node it should sit under and what showed it. Never edit a node's `parent:` line by hand: the nodes next to it would not be put up to be verified.
- A node you change is carried on to the nodes next to it. Go on until nothing is left to verify, and tell the user every node you revised or recorded.
- Never record "still fits" to clear the list. A node you have not read against the evidence stays owed, and the user sees that it is.

## Changing the abstraction

The files in `abstraction/` are short on purpose. A change there, like a budget you set, does not wait for the user's approval: you go on. In return, when the turn ends, tell them every such change you made in it: what changed and why. A revision keeps the earlier text, so they can switch a change back. (A project can ask to approve these first; then you are simply asked.)

- Under the core there are two kinds of node, and both would survive a rewrite of the code. A design is a decision that sets the direction of the system: a choice with another way that was turned down. A component (`kind: component`) is a part of the system that carries designs out; it sits under the design it carries out. A part that would serve every design is a stage of the code, such as a driver hook or a compiler: split it into the parts that carry each design. Only a part that carries no design of its own and serves them all, such as how the system plugs in or a view built on the rest, sits under the core. Something that has to be built but would not change the direction if built another way is a component, not a design.
- Before you propose a new node, check that it is not a code module or a file: that is work under a node that exists, so declare it as a task there. A graph that grows with the code is drawn at the wrong level.
- Name a design by its decision, in a plain sentence ("Step back, don't patch"). Name a component for what it is, as a noun phrase ("Budget monitor"). A person who reads only the tree should know what each node is. A slogan or a phrase about an idea ("Effort as a signal") is neither.
- To change a node, call `node_revise` with the reason first (it keeps the current text), then rewrite the node file. A version is a decision: pass `decision: true` only when a rule of the node is added, dropped or reversed, or the user stepped back. A clearer sentence, a new name or text moved from one place to another is a rewording, and takes no new number.
- When the user asks to go back on a change to a design, call `node_restore`: by default it brings back the version before the current one. It is a new version, so the text it replaces is kept as well.
- To rename or drop a node, run `thinspec node rename <id> <new-id>` or `thinspec node retire <id> --reason "..." --into <node>` in the shell. Never move or delete a node file by hand: its tasks hang on its id.
- When a change breaks an invariant, fix the code, or tell the user the invariant is wrong. Don't quietly weaken the invariant.
- When a rule you learned under one node holds more generally, propose moving it up to the parent.
- Write a node as one level of a story, in three short paragraphs: `**Motivation.**` why this level is needed, `**Challenge.**` what makes it hard, `**Approach.**` how it is done (`**Insight.**` for the core). Then the few invariants of that level, six at most, and the bans. Write only what belongs to the level: the core says nothing of components, a design names its components and stops, and a component holds the concrete reasons. When a node needs more, the rest belongs to a node under it; do not add to a long list.
- Write nothing into the spec that is not there yet: no list of components a design might have. When you see that a design is carried out by less than it needs, tell the user in your message, in a line, what it lacks and why that follows from the design's story. When the user asks you to propose a component under a design (the pane's `+ Propose a component` button starts that sentence), answer in your message, or take what they wrote as the component. Add a component under that design, with its own short file, only once the user has said which one.

## When to split a node, and when it is a leaf

The tree has no fixed depth. Behind every test below is one question: if an agent built this part another way tomorrow, would the person have to agree? A person holds decisions and rules; how a part is done is the agents'. If another way would change what the system delivers (what it catches, what it costs, what its result can be trusted for), the part carries a decision and gets a node. If another way would break a guarantee, the person holds the rule but not the part: it is an invariant of the node it serves. If neither, it is a line in the digest, and tasks. Before you split a node, or when you wonder whether a leaf is one, ask of each part:

1. Has it a rule of its own about what it does or guarantees: one a result can be checked against, that the node does not already state? What has to be traced or stored for it does not count: that is a rule of the part that traces.
2. Has it evidence of its own: does the paper, an experiment or the digest report it apart from the others?
3. Is there a choice about it alone with another way on record: the paper, the repository or a past decision names an alternative for this part and not its siblings? That it could be swapped out is not enough: every function can be. And it has to be a part that does something its siblings do not: a setting of the node, or a property of the whole node, is not a part.
4. Does the node's digest overflow its five lines with lines about different parts? That is the plainest sign.
5. Later, do overruns gather on one part? That is evidence it needs its own node.

A part that passes the third gets a node of its own. A part that passes only the first gives its node a rule, not a child: write the rule among the node's invariants. It gets a node only once such rules about it no longer fit in its node, or it comes to need a story of its own, a challenge its node's approach does not answer. The second, fourth and fifth are signs to look. When in doubt, do not split: a part folded into its node loses nothing, while a node per mechanism grows back into the code. A part whose rule is a rule its node already states, or whose alternative on record is another way for the node to apply that rule, is not a part of its own: the choice is the node's. A part that passes none stays inside its node, and the work on it is tasks. The cap is on a view, a node and the nodes directly under it (150 lines by default), not on the whole spec: a deep tree is fine when each view reads in one sitting. Propose a split to the user in a line, as with any new component, and make it once they agree.

## Taking on a system that is already written

A project that comes with a paper and its code is adapted, not developed from nothing. The tree is taken from the paper, and the code is read against it.

1. Read the whole paper first, and take from it only its high-level structure: the core from its problem and insight, the designs from the decisions its design section argues for (each with the way it turned down), the components from the mechanisms its design section gives for carrying out each decision, not from the boxes of its implementation section or its architecture figure, which are usually stages of the code that serve every decision. Never make a node for a code module.
2. Then read the code against that tree, each part of it under the component it carries out. Write a leaf's `features` from what the code does, not from what the paper claims.
3. Where the code departs from the paper, do not pick a side and do not leave the two to contradict each other. Put the departure under the node it belongs to as an `as_built` line (step 5 says how high): what departs, and why. What the part does now is already in `features`: do not say it twice. Work the reason out from what is there: only part of the system was released, a change made for practical use, a redesign after the paper. Write "likely" when the reason is your reading and the repository does not state it, and ask the user about the few that change what a node means.
4. Keep a node's story and its rules at the level where the paper and the code agree. A rule the release does not keep is not a rule of the node: say it in the `as_built` line.
5. Place each difference as high as what it changes, whichever side it came from. Where it came from, the paper or only the release, decides how its line is worded, never where it goes:
   - It changes what the system claims, the result it reports or what that result can be trusted for: an `as_built` line on the design whose decision it contradicts, never only on a leaf under it, and a question for the user.
   - It carries a choice of its own with another way on record, as the split test asks: a node. A part the paper gives a node and the release lacks entirely keeps it, with the paper's story and rules and one `as_built` line saying it is not released and why. A part only the release has gets one on the same terms, proposed to the user like any split. A choice that is a setting of a node, such as a mode that covers more or less, is that node's own decision: its approach says it, or its `as_built` line when the release lacks it.
   - It adds a guarantee and no choice, such as leaving the user's files as they were: an invariant of the node it serves.
   - It only changes how something is done: a line in that node's digest.
6. Put a result of the paper's evaluation on the node it is evidence about: the whole system's on the core, an ablation's on its design or component. What the paper considered and turned down belongs in the design's approach; `reverts` is for what was built and turned back.
7. Code that fits no node is a question for the user, not a new node. Invent no tasks and no history: work is recorded from this point on.
8. When the project keeps a changelog, release notes or a roadmap, read them next, before any commit history: they are the project's own distillation of what changed since the paper. They only enrich the nodes already there. They add no section, no node and no move, and the tree stays the paper's.
   - Skip fixes, packaging, install and release mechanics, CI, docs and formatting: a person decides nothing from them. A fix that changes what a node's results can be trusted for is the exception.
   - A new way of doing a node's work that replaces the old one: rewrite that node's `features` line, not add a second one. Say the old way in `reverts` only when the project says it was dropped and why, and in `as_built` when it departs from the paper.
   - A new capability or idea: one `features` line on the node it extends. One that carries a decision of its own is a question for the user (step 7).
   - A result the project measured: `positive` or `negative` on the node it is evidence about, with what was measured and its stated limits.
   - A roadmap item is not built, so it is never a feature. It may give the reason in an `as_built` line (the release lacks it and plans it); otherwise leave it.
   - A section is full at five lines: merge and drop, never append.
   - Then the commit history, top down, never commit by commit. Take the code at the paper (its submission tag, or the first commit whose layout matches the paper's parts) and compare it with now, file by file through renames, counted per node. That count alone says what is new since the paper, which nodes were rewritten and which were left alone. Read commits only for what is new or rewritten: the largest few per node, by their messages, and a diff only where a message does not say. A node left alone says nothing. A dated line (when a part arrived, what it replaced) goes on the node it is about, like any other line.

## Seeing the graph

The user sees the graph and the budgets in the ThinSpec pane, which their one command, `/thinspec`, opens, and in the line above the prompt. Its Extend, Step back and Ban buttons only start a sentence in the prompt box; when the user sends it, record their choice with `task_decide`. A planned task has a Hand to a subagent button of the same kind. When the user sends that sentence, start a subagent and give it the task id, the check and the node the task falls under; the subagent starts the task with `task_start`, using the budget the user named, and works under these same rules. In a terminal, `thinspec status` prints the same graph.
