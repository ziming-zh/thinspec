"""Locating a ThinSpec repo and reading its configuration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

STATE_DIR = ".thinspec"
CONFIG_FILE = "config.json"

DEFAULTS = {
    # Folder holding the human-maintained abstraction (one Markdown file per node).
    "abstraction_dir": "abstraction",
    # What happens when an agent edits code with no active task:
    #   "strict": every edit is refused until a task is declared
    #   "nudge":  the first edit of a session is refused once, later ones are logged as untracked
    #   "off":    edits are only logged
    "gate": "nudge",
    # What happens when an agent changes the spec or sets a budget:
    #   "tell": it goes ahead and is recorded, and the agent tells the person when the turn ends
    #   "ask":  the person is asked first, in the agent's own permission prompt
    # The verdict on a task (extend, step back, ban) always goes to the person first.
    # A session the person set to bypass permissions is never asked anything.
    "approvals": "tell",
    # What "approvals" covers: a budget an agent sets, and an agent's edit to the abstraction folder.
    "confirm_budget": True,
    "protect_abstraction": True,
    # Gaps between agent actions longer than this many seconds are not counted as work time.
    "idle_cap_seconds": 300,
    # A session not heard from for this many minutes is shown as quiet, and it no
    # longer holds its task: another session with no task of its own may pick it up.
    "quiet_after_minutes": 15,
    # A budget is an estimate: a task that reaches it is not stopped. One that goes
    # this many times past it is paused, and a person decides what happens next.
    "alarm_ratio": 2.0,
    # Paused tasks in a row under one design (since its last revision) before
    # the design itself is flagged "step back".
    "stepback_alarms": 2,
    # Size caps that keep each view small enough for one person to read. A view is a node and the
    # nodes directly under it: what the person sees at one zoom level. The tree may go as deep as
    # its parts differ in what can be decided about them; no view may grow past this.
    "max_lines_view": 150,
    "max_lines_per_node": 30,
    # How many designs, and apart from them how many components, may sit directly under one node.
    # A wider layer usually means its nodes are modules of the code, not components of the design,
    # and `thinspec check` says so.
    "max_children": 5,
    # A Bash command matching any of these counts as one trial of the active
    # task, unless the task names its own check command.
    "trial_patterns": [
        r"\bpytest\b",
        r"\bpy\.test\b",
        r"\bpython3? -m (pytest|unittest)\b",
        r"\b(tox|nox)\b",
        r"\bgo test\b",
        r"\bcargo (test|nextest)\b",
        r"\bctest\b",
        r"\bmake (test|check)\b",
        r"\b(npm|pnpm|yarn|bun)( run)? test\b",
        r"\b(jest|vitest)\b",
        r"\bbazel test\b",
    ],
}


def find_root(start) -> Optional[Path]:
    """Walk up from `start` to the nearest directory that contains .thinspec/config.json."""
    p = Path(start).resolve()
    for d in [p] + list(p.parents):
        if (d / STATE_DIR / CONFIG_FILE).is_file():
            return d
    return None


def load_config(root: Path) -> dict:
    cfg = dict(DEFAULTS)
    path = Path(root) / STATE_DIR / CONFIG_FILE
    try:
        user = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(user, dict):
            cfg.update(user)
            # Earlier versions capped the whole spec. Such a setting is read as the cap of a view.
            if "max_lines_total" in user and "max_lines_view" not in user:
                cfg["max_lines_view"] = user["max_lines_total"]
    except (OSError, ValueError):
        pass
    return cfg
