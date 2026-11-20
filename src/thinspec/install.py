"""`thinspec init`: scaffold a repo and wire ThinSpec into Claude Code."""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from . import ThinSpecError
from .config import CONFIG_FILE, DEFAULTS, STATE_DIR

ASSETS = Path(__file__).parent / "assets"

# Quiet when thinspec is not installed, so a teammate without it is not interrupted.
HOOK_COMMAND = "if command -v thinspec >/dev/null 2>&1; then thinspec hook; fi"
PRE_MATCHER = "^(Edit|Write|MultiEdit|NotebookEdit|Bash|mcp__.*thinspec.*)$"
# Codex runs shell commands as "Bash" and edits files with "apply_patch", and has no failure event of its
# own: a failed command still gets PostToolUse, with its exit code in the response.
CODEX_HOOK_COMMAND = "if command -v thinspec >/dev/null 2>&1; then thinspec hook --agent codex; fi"
CODEX_PRE_MATCHER = "^(Bash|apply_patch|mcp__.*thinspec.*)$"
CODEX_MCP = (
    "# thinspec:start\n"
    "[mcp_servers.thinspec]\n"
    "command = \"thinspec\"\n"
    "args = [\"mcp\"]\n"
    "env = { THINSPEC_AGENT = \"codex\" }\n"
    "# thinspec:end\n"
)

# The agent's rules are a skill of their own name: /thinspec belongs to the person and opens
# the graph. Earlier versions wrote the rules as the skill "thinspec".
SKILL_NAME = "thinspec-rules"
OLD_SKILL_NAMES = ("thinspec",)

CONFIG_KEYS = (
    "abstraction_dir", "gate", "approvals", "confirm_budget", "protect_abstraction",
    "idle_cap_seconds", "quiet_after_minutes", "alarm_ratio", "stepback_alarms", "max_lines_view", "max_lines_per_node",
    "max_children",
)

CORE_TEMPLATE = """---
id: core
title: Core abstraction
kind: core
parent:
version: 1
---

(One or two sentences: the key insight this system is built on.)

## Invariants

- (A rule that must always hold, written so a result can be checked against it.)

## Bans
"""


def _hook_groups() -> dict:
    handler = {"type": "command", "command": HOOK_COMMAND, "timeout": 15}
    return {
        "SessionStart": [{"hooks": [handler]}],
        "PreToolUse": [{"matcher": PRE_MATCHER, "hooks": [handler]}],
        "PostToolUse": [{"matcher": "*", "hooks": [handler]}],
        "PostToolUseFailure": [{"matcher": "*", "hooks": [handler]}],
        "Stop": [{"hooks": [handler]}],
    }


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise ThinSpecError("%s is not valid JSON. Fix it, then run init again." % path) from None
    if not isinstance(data, dict):
        raise ThinSpecError("%s should hold a JSON object." % path)
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _is_ours(group) -> bool:
    return isinstance(group, dict) and any(
        "thinspec hook" in str(h.get("command", "")) for h in group.get("hooks") or [] if isinstance(h, dict)
    )


def wire_claude_code(root: Path) -> List[str]:
    """Add hooks, the MCP server and the skill at project level. Safe to run twice."""
    done: List[str] = []

    settings_path = root / ".claude" / "settings.json"
    settings = _read_json(settings_path)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ThinSpecError("%s: 'hooks' should be an object." % settings_path)
    for event, groups in _hook_groups().items():
        existing = [g for g in hooks.get(event) or [] if not _is_ours(g)]
        hooks[event] = existing + groups
    _write_json(settings_path, settings)
    done.append(".claude/settings.json  hooks that count work and enforce budgets")

    mcp_path = root / ".mcp.json"
    mcp = _read_json(mcp_path)
    servers = mcp.setdefault("mcpServers", {})
    servers["thinspec"] = {"command": "thinspec", "args": ["mcp"]}
    _write_json(mcp_path, mcp)
    done.append(".mcp.json              the thinspec MCP server")

    skills = root / ".claude" / "skills"
    for old in OLD_SKILL_NAMES:
        # /thinspec is the person's command now. The rules init wrote under that name would
        # answer it instead, so they go; a skill of that name somebody else wrote stays.
        old_path = skills / old / "SKILL.md"
        try:
            text = old_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if text.startswith("---\nname: %s\n" % old) and "# Working under ThinSpec" in text:
            old_path.unlink()
            try:
                old_path.parent.rmdir()  # only when nothing else was put in it
            except OSError:
                pass
            done.append("removed .claude/skills/%s/SKILL.md  the agent's rules are now the skill %s, and "
                        "/thinspec opens the graph" % (old, SKILL_NAME))
    skill_path = skills / SKILL_NAME / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text((ASSETS / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    done.append(".claude/skills/%s/SKILL.md  the rules the agent works by" % SKILL_NAME)
    return done


def wire_codex(root: Path) -> List[str]:
    """Wire ThinSpec into Codex at project level: hooks that count work, the MCP server, the rules.
    Safe to run twice. Codex runs a project's hooks and config once the person trusts the project."""
    done: List[str] = []
    handler = {"type": "command", "command": CODEX_HOOK_COMMAND, "timeout": 15}
    hooks_path = root / ".codex" / "hooks.json"
    data = _read_json(hooks_path)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ThinSpecError("%s: 'hooks' should be an object." % hooks_path)
    ours = {
        "SessionStart": [{"hooks": [handler]}],
        "PreToolUse": [{"matcher": CODEX_PRE_MATCHER, "hooks": [handler]}],
        "PostToolUse": [{"matcher": "*", "hooks": [handler]}],
        "Stop": [{"hooks": [handler]}],
    }
    for event, groups in ours.items():
        hooks[event] = [g for g in hooks.get(event) or [] if not _is_ours(g)] + groups
    _write_json(hooks_path, data)
    done.append(".codex/hooks.json      hooks that count Codex's work and enforce budgets")

    cfg_path = root / ".codex" / "config.toml"
    text = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    start, end = "# thinspec:start\n", "# thinspec:end\n"
    if start in text and end in text:
        head, rest = text.split(start, 1)
        text = head + CODEX_MCP + rest.split(end, 1)[1]
    elif "[mcp_servers.thinspec]" in text:
        raise ThinSpecError("%s already has an [mcp_servers.thinspec] table that init did not write. Remove it, "
                            "then run init again." % cfg_path)
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + CODEX_MCP
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(text, encoding="utf-8")
    done.append(".codex/config.toml     the thinspec MCP server")

    skill_path = root / ".codex" / "skills" / SKILL_NAME / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text((ASSETS / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    done.append(".codex/skills/%s/SKILL.md  the rules the agent works by" % SKILL_NAME)
    return done


def wire_agents_md(root: Path) -> List[str]:
    """Add (or refresh) the ThinSpec section of AGENTS.md, for agents that have no hooks."""
    section = (ASSETS / "AGENTS_SECTION.md").read_text(encoding="utf-8").strip()
    path = root / "AGENTS.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    start, end = "<!-- thinspec:start -->", "<!-- thinspec:end -->"
    if start in text and end in text:
        head, rest = text.split(start, 1)
        text = head + section + rest.split(end, 1)[1]
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + section + "\n"
    path.write_text(text, encoding="utf-8")
    return ["AGENTS.md              the protocol for agents without hooks (Codex, Cursor, ...)"]


def init(root: Path, claude: bool = True, agents_md: bool = False, codex: bool = False) -> List[str]:
    root = Path(root)
    done: List[str] = []
    state = root / STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    config_path = state / CONFIG_FILE
    if not config_path.exists():
        _write_json(config_path, {k: DEFAULTS[k] for k in CONFIG_KEYS})
        done.append(".thinspec/config.json  settings")
    (state / ".gitignore").write_text("sessions/\nview.html\nhook-errors.log\n.lock\n", encoding="utf-8")
    ledger = state / "ledger.jsonl"
    if not ledger.exists():
        ledger.write_text("", encoding="utf-8")
        done.append(".thinspec/ledger.jsonl append-only record of tasks, budgets and decisions")

    cfg = _read_json(config_path)
    abs_dir = root / str(cfg.get("abstraction_dir") or DEFAULTS["abstraction_dir"])
    abs_dir.mkdir(parents=True, exist_ok=True)
    readme = abs_dir / "README.md"
    if not readme.exists():
        readme.write_text((ASSETS / "ABSTRACTION_README.md").read_text(encoding="utf-8"), encoding="utf-8")
        done.append("%s/README.md  how the folder works" % abs_dir.name)
    has_nodes = any(p.name.lower() != "readme.md" for p in abs_dir.glob("*.md"))
    if not has_nodes:
        (abs_dir / "core.md").write_text(CORE_TEMPLATE, encoding="utf-8")
        done.append("%s/core.md    the root node, for you to fill in" % abs_dir.name)

    if claude:
        done += wire_claude_code(root)
    if codex:
        done += wire_codex(root)
    if agents_md:
        done += wire_agents_md(root)
    return done
