# abstraction/

This folder is the part of the system a person maintains. The code is too large to hold in your head; this is not.

Each `.md` file is one node of the design graph: the core abstraction at the root, the designs under it, and under each design the components that carry it out. A node has a short summary, its **invariants** (rules that must always hold) and its **bans** (approaches that were tried, cost too much, and are never to be taken again under this node).

**What is a node.** Under the core there are two kinds of node, and both would survive a rewrite of the code.

A **design** is a decision that sets the direction of the system: a choice with another way that was turned down. It is what a paper about the system argues for. A system has a few of them. Three questions for a candidate design:

- Was there another way to go, and was it turned down?
- Would the system be heading somewhere else had it gone the other way?
- Does its invariant constrain results and behaviour, or only how something is built?

A **component** is a part of the system that carries a design out: the mechanism the paper's design section gives for it, not a box of its implementation figure, which is usually a stage of the code serving every design. It has to be built, but building it another way would not change the direction. Mark it `kind: component`, and put it under the design it carries out. A part that would serve every design is a stage of the code: split it into the parts that carry each design. Only a part that carries no design of its own and serves them all (how the system plugs in, a view built on the rest) sits under the core.

A code module or a file is neither. It is work under a node, and it shows up there as tasks. So this graph grows only when the system gains a decision or a component, and it stays narrow while the code grows.

**How to name one.** Name a design by its decision, in a plain sentence: `Step back, don't patch`. Name a component for what it is, as a noun phrase: `Budget monitor`. Someone who reads only the tree should know what each node is. A slogan or a phrase about an idea (`Effort as a signal`) is neither.

**How to write one.** A node tells one level of the system as a short line of story, in three paragraphs: why this level is needed, what makes it hard, how it is done. Then the few invariants that hold at that level, six at most. Write only what belongs to the level. The core says nothing of components. A design names the components that carry it out and stops there. A component is where the concrete reasons go: why the tool behaves as it does. When a node needs more than that, the rest belongs to a node under it. Reading down the tree is then zooming in, the way a paper is read a section at a time.

**How deep it goes.** There is no fixed number of levels. A part of a node gets a node of its own when it carries a decision of its own: a choice about it alone, with another way on record, that changes what the system delivers. A part with only a rule of its own adds that rule to its node instead. Where the parts would differ only in how they are coded, the node is a leaf, and the rest is tasks under it. What is kept small is each view, a node with the nodes directly under it, which you read in one sitting.

**A system that is already written.** When the system comes with a paper and its code, the tree is taken from the paper's high-level structure: its insight for the core, the decisions of its design section for the designs, the mechanisms that carry out each decision for the components, not the boxes of its implementation section, which are usually stages of the code that serve every decision. The code is then read against that tree. Where it departs from the paper, the departure is written with the reason (only part was released, a change for practical use, a later redesign), and as high as what it changes, whichever side it came from: on the design it contradicts when it changes what the system claims, asked of the author; as a node when it carries a choice of its own, even if the release lacks it; as a rule of the node it serves when it adds a guarantee; else as a line. The spec says how the system is and why, not only how it was described.

**What a design lacks.** Nothing is listed ahead of time. When a design needs a component it does not have, say so: press `+ Propose a component` under the design in the pane, which starts the sentence, or tell the agent. It becomes a component, with its own short file, once you have said what it is.

```
---
id: instrument
title: Instrument
kind: design
parent: core
version: 2
---

**Motivation.** Every step has to be seen before it can be moved.

**Challenge.** A step has no stable name: the same operation appears under a new one whenever the model changes.

**Approach.** Hook each step where it runs, not by what it is called. (For the core this paragraph is the **Insight.**)

## Invariants

- One unique hook point per step.

## Bans

- Stable node names across steps — they break on any model change.
```

Rules of the folder:

- Keep each view small. `thinspec check` warns when a node is over 30 lines, or a view, a node with the nodes directly under it, is over 150.
- Keep it narrow. `thinspec check` also warns when more than five designs, or more than five components, sit under one node: a layer that wide is usually a list of modules. The two kinds are counted apart, so a core with three designs and four parts they share is not too wide. Group them under fewer designs, or make some of them tasks.
- An invariant is something you can check a result against. If you can't, it's a wish.
- Bans apply to the node and everything under it.
- To change a design, run `thinspec revise <node> --reason "..."` first. It archives the current text in `history/` and bumps the version, so the graph shows how the abstraction evolved and why.
- Keep it in the order of the story. Nodes under one node are listed designs first, then components, each by id. Add `order: 1`, `order: 2`, … to their headers to list them in the order they should be read.
- Keep it sound. A node is owed a verification when a round of work under it ends (a task closes with a result, or an agent's turn changed code or ran the check), and when the node above it and the nodes under it change. `thinspec check` lists it until it is verified: revise it if it no longer fits, which carries the change on from there, or run `thinspec verify <node> --note "..."` to record why it still does.
- To switch back, run `thinspec restore <node>`. The previous version's text returns as a new version, and the text it replaces is archived too.
- To rename a node, run `thinspec node rename <id> <new-id>`. To drop one, run `thinspec node retire <id> --reason "..."`, with `--into <node>` to hand its tasks to another. Its tasks and its kept versions follow, which they do not when a file is moved or deleted by hand.
- Agents may edit here without waiting for you. They tell you at the end of the turn what they changed and why, and a revision keeps the earlier text in `history/` for you to switch back to. To be asked first, set `"approvals": "ask"` in `.thinspec/config.json`.

Tasks, budgets and what actually happened are recorded in `.thinspec/ledger.jsonl`. Run `thinspec status` or `thinspec view --open` to see them against this graph.
