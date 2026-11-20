"""The abstraction store: one Markdown file per node, readable and editable by hand.

A node file looks like this:

    ---
    id: instrument
    title: Instrument
    kind: design
    parent: core
    version: 2
    ---

    One short paragraph saying what this design is.

    ## Invariants

    - One unique hook point per step.

    ## Bans

    - Stable node names across steps: they break on any model change.

`kind` is `core` for the root. Below it a node is a `design`, a decision that
sets the direction, or a `component`, a part of the system that carries
designs out and sits under the design it serves. Only the flat
`key: value` header and the two bullet lists are parsed. Any other section is
kept untouched for humans.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import ThinSpecError

SECTION_RE = re.compile(r"^##\s+(.*?)\s*$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
KINDS = ("core", "design", "component")
INVARIANT_NAMES = {"invariants", "invariant"}
BAN_NAMES = {"bans", "ban", "ban list", "banned"}
HISTORY_DIR = "history"


@dataclass
class Node:
    id: str
    title: str
    kind: str
    parent: Optional[str]
    version: int
    summary: str
    invariants: List[str] = field(default_factory=list)
    bans: List[str] = field(default_factory=list)
    path: Optional[Path] = None
    lines: int = 0  # non-empty body lines: what a human has to read
    order: Optional[int] = None  # its place among the nodes beside it, when the person gave one
    module: Optional[str] = None  # repo-relative implementation boundary
    comparison: Optional[str] = None  # command that compares the old and new implementations


def _split(text: str) -> Tuple[Dict[str, str], List[str]]:
    lines = text.splitlines()
    meta: Dict[str, str] = {}
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
            if ":" in lines[i]:
                key, value = lines[i].split(":", 1)
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                meta[key.strip()] = value
        else:
            meta, start = {}, 0  # no closing delimiter: treat as plain text
    return meta, lines[start:]


def _bullets(lines: List[str]) -> List[str]:
    items: List[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s[:2] in ("- ", "* "):
            items.append(s[2:].strip())
        elif items:
            items[-1] += " " + s
    return items


def parse_node(text: str, fallback_id: str = "node", path: Optional[Path] = None) -> Node:
    meta, body = _split(text)
    summary_lines: List[str] = []
    sections: List[Tuple[str, List[str]]] = []
    h1 = None
    for line in body:
        m = SECTION_RE.match(line)
        if m:
            sections.append((m.group(1).strip().lower(), []))
        elif sections:
            sections[-1][1].append(line)
        elif line.startswith("# ") and h1 is None:
            h1 = line[2:].strip()
        else:
            summary_lines.append(line)
    invariants: List[str] = []
    bans: List[str] = []
    # Any other section is not part of the spec: an old `## Proposed` list is left unread.
    for name, content in sections:
        if name in INVARIANT_NAMES:
            invariants += _bullets(content)
        elif name in BAN_NAMES:
            bans += _bullets(content)
    parent = meta.get("parent") or None
    if parent in ("null", "none", "None", "~"):
        parent = None
    try:
        version = int(meta.get("version", "1"))
    except ValueError:
        version = 1
    node_id = meta.get("id") or fallback_id
    return Node(
        id=node_id,
        title=meta.get("title") or h1 or node_id,
        kind=meta.get("kind") or ("design" if parent else "core"),
        parent=parent,
        version=version,
        summary=" ".join(s.strip() for s in summary_lines if s.strip()),
        invariants=invariants,
        bans=bans,
        path=path,
        lines=sum(1 for s in body if s.strip()),
        order=int(meta["order"]) if (meta.get("order") or "").strip().lstrip("-").isdigit() else None,
        module=meta.get("module") or None,
        comparison=meta.get("comparison") or None,
    )


def node_files(abs_dir: Path) -> List[Path]:
    if not abs_dir.is_dir():
        return []
    return sorted(
        p
        for p in abs_dir.glob("*.md")
        if p.name.lower() != "readme.md" and not p.name.startswith("_")
    )


def load_nodes(abs_dir: Path) -> Dict[str, Node]:
    """Read every node file. Later duplicates of an id are dropped (see `problems`)."""
    nodes: Dict[str, Node] = {}
    for p in node_files(abs_dir):
        node = parse_node(p.read_text(encoding="utf-8"), fallback_id=p.stem, path=p)
        nodes.setdefault(node.id, node)
    return nodes


def problems(abs_dir: Path, cfg: dict) -> List[str]:
    """Structural problems and size-cap warnings, as plain sentences."""
    out: List[str] = []
    seen: Dict[str, Path] = {}
    for p in node_files(abs_dir):
        node = parse_node(p.read_text(encoding="utf-8"), fallback_id=p.stem, path=p)
        if node.id in seen:
            out.append("Duplicate id '%s' in %s and %s." % (node.id, seen[node.id].name, p.name))
        seen.setdefault(node.id, p)
    nodes = load_nodes(abs_dir)
    roots = [n.id for n in nodes.values() if n.parent is None]
    if not nodes:
        out.append("No nodes yet: add a core node to %s/." % abs_dir.name)
    elif not roots:
        out.append("No root node: one node must have no parent.")
    elif len(roots) > 1:
        out.append("More than one root node (%s): a system has one core abstraction." % ", ".join(roots))
    for n in nodes.values():
        if n.module and not valid_module(n.module):
            out.append("Node '%s' needs a repo-relative module path without '..'." % n.id)
        if n.parent and n.parent not in nodes:
            out.append("Node '%s' names a parent '%s' that does not exist." % (n.id, n.parent))
        seen_ids = {n.id}
        cur = n
        while cur.parent and cur.parent in nodes:
            if cur.parent in seen_ids:
                out.append("Node '%s' is part of a parent cycle." % n.id)
                break
            seen_ids.add(cur.parent)
            cur = nodes[cur.parent]
        if n.lines > cfg["max_lines_per_node"]:
            out.append(
                "Node '%s' is %d lines; the cap is %d. Trim it or split it."
                % (n.id, n.lines, cfg["max_lines_per_node"])
            )
        if not n.invariants:
            out.append("Node '%s' states no invariant yet." % n.id)
        if n.kind not in KINDS:
            out.append(
                "Node '%s' has kind '%s'. A node is the core, a design (a decision that sets the direction) "
                "or a component (a part of the system that carries designs out)." % (n.id, n.kind)
            )
        above = nodes.get(n.parent or "")
        if above is not None and above.kind == "component" and n.kind == "design":
            out.append(
                "Design '%s' sits under the component '%s'. A decision is not part of what carries it out: "
                "put it under the core or under another design." % (n.id, above.id)
            )
        # Designs and components are counted apart: a core with three designs and four parts
        # that serve several of them is not a list of modules.
        cap = cfg.get("max_children")
        kids = children(nodes, n.id)
        for kind, plural in (("design", "designs"), ("component", "components")):
            under = sum(1 for k in kids if k.kind == kind)
            if cap and under > cap:
                out.append(
                    "Node '%s' has %d %s under it; the cap is %d. A layer this wide usually means its nodes "
                    "are modules of the code, not components of the design. Group them under fewer designs, or make some of them "
                    "tasks under a design." % (n.id, under, plural, cap)
                )
    cap = cfg.get("max_lines_view") or cfg.get("max_lines_total")
    for view in views(nodes):
        if cap and view["lines"] > cap:
            out.append(
                "The view of '%s', it and the %d nodes under it, is %d lines; the cap is %d. A person reads one "
                "view at a time: shorten these nodes, or move what is more concrete one level down."
                % (view["node"], view["under"], view["lines"], cap)
            )
    return out


def valid_module(name: str) -> bool:
    path = Path(name)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name


def views(nodes: Dict[str, Node]) -> List[dict]:
    """Each view of the tree, largest first: a node with nodes under it, and how many lines the two levels hold."""
    out = []
    for n in nodes.values():
        kids = children(nodes, n.id)
        if kids:
            out.append({"node": n.id, "under": len(kids), "lines": n.lines + sum(k.lines for k in kids)})
    return sorted(out, key=lambda v: -v["lines"])


def chain(nodes: Dict[str, Node], node_id: str) -> List[Node]:
    """The path from the root down to `node_id`, inclusive."""
    out: List[Node] = []
    seen = set()
    cur = nodes.get(node_id)
    while cur is not None and cur.id not in seen:
        out.append(cur)
        seen.add(cur.id)
        cur = nodes.get(cur.parent) if cur.parent else None
    return list(reversed(out))


def children(nodes: Dict[str, Node], node_id: Optional[str]) -> List[Node]:
    """The nodes directly under one: its designs first, then the components that carry them out.

    Within each kind, a node whose header gives an `order` comes at that place, so the tree can be
    read in the order of the story it tells. Nodes with none follow, in the order of their ids.
    """
    under = [n for n in nodes.values() if n.parent == node_id]
    # Stable: nodes that tie keep the order they were read in.
    return sorted(under, key=lambda n: (n.kind == "component", n.order is None, n.order or 0))


def roots(nodes: Dict[str, Node]) -> List[Node]:
    return [n for n in nodes.values() if n.parent is None or n.parent not in nodes]


def walk(nodes: Dict[str, Node]) -> List[Tuple[Node, int]]:
    """Every node in reading order, each with how deep it sits under the root."""
    out: List[Tuple[Node, int]] = []
    seen = set()

    def down(node: Node, depth: int) -> None:
        if node.id in seen:
            return
        seen.add(node.id)
        out.append((node, depth))
        for child in children(nodes, node.id):
            down(child, depth + 1)

    for root in roots(nodes):
        down(root, 0)
    out += [(n, 0) for n in nodes.values() if n.id not in seen]  # nodes caught in a parent cycle
    return out


def _set_meta(text: str, key: str, value: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "---\n%s: %s\n---\n\n%s" % (key, value, text)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            lines.insert(i, "%s: %s" % (key, value))
            break
        if lines[i].split(":", 1)[0].strip() == key:
            lines[i] = "%s: %s" % (key, value)
            break
    return "\n".join(lines) + "\n"


# File names this folder or a coding agent reads for something else. On a file
# system that ignores case, agents.md is AGENTS.md, and the agent loads it as instructions.
RESERVED_IDS = ("readme", "agents", "claude")


def check_id(node_id: str) -> None:
    if not ID_RE.match(node_id):
        raise ThinSpecError("Node ids use letters, digits, '-', '_' and '.': got '%s'." % node_id)
    if node_id.lower() in RESERVED_IDS:
        raise ThinSpecError(
            "'%s' cannot be a node id: %s.md is a name this folder or a coding agent reads for "
            "something else. Pick a name that says what the design is." % (node_id, node_id)
        )


def rename_node(abs_dir: Path, node: Node, new_id: str) -> Path:
    """Give a node a new id. Its file, the nodes under it and its kept versions follow."""
    assert node.path is not None
    check_id(new_id)
    nodes = load_nodes(abs_dir)
    target = abs_dir / ("%s.md" % new_id)
    if new_id in nodes or target.exists():
        raise ThinSpecError("A node with id '%s' already exists." % new_id)
    for child in children(nodes, node.id):
        child.path.write_text(_set_meta(child.path.read_text(encoding="utf-8"), "parent", new_id),
                              encoding="utf-8")
    hist = abs_dir / HISTORY_DIR
    pat = re.compile(r"^%s\.v(\d+(?:\.e\d+)?)\.md$" % re.escape(node.id))  # versions, and rewordings of one
    for p in (sorted(hist.iterdir()) if hist.is_dir() else []):
        m = pat.match(p.name)
        if m:  # a kept version is restored under the id it carries, so it carries the new one
            p.write_text(_set_meta(p.read_text(encoding="utf-8"), "id", new_id), encoding="utf-8")
            p.rename(hist / ("%s.v%s.md" % (new_id, m.group(1))))
    node.path.write_text(_set_meta(node.path.read_text(encoding="utf-8"), "id", new_id), encoding="utf-8")
    node.path.rename(target)
    return target


def move_node(abs_dir: Path, node: Node, under: str) -> None:
    """Put a node under another one. Only its place changes: its text, version and id stay."""
    assert node.path is not None
    nodes = load_nodes(abs_dir)
    if node.parent is None:
        raise ThinSpecError("'%s' is the core abstraction: nothing sits above it." % node.id)
    if under not in nodes:
        raise ThinSpecError("There is no node '%s' to move '%s' under." % (under, node.id))
    if under == node.parent:
        raise ThinSpecError("'%s' already sits under '%s'." % (node.id, under))
    cur: Optional[Node] = nodes[under]
    while cur is not None:                       # walking up from the new place must not meet the node
        if cur.id == node.id:
            raise ThinSpecError("'%s' cannot move under '%s', which is itself or sits under it." % (node.id, under))
        cur = nodes.get(cur.parent or "")
    if node.kind == "design" and nodes[under].kind == "component":
        raise ThinSpecError("Design '%s' cannot sit under the component '%s': a decision is not part of what "
                            "carries it out." % (node.id, under))
    node.path.write_text(_set_meta(node.path.read_text(encoding="utf-8"), "parent", under), encoding="utf-8")


def retire_node(abs_dir: Path, node: Node) -> Path:
    """Take a node out of the graph. Its text joins its kept versions. Returns where it went."""
    assert node.path is not None
    if node.parent is None:
        raise ThinSpecError("'%s' is the core abstraction: it can be revised, not retired." % node.id)
    under = children(load_nodes(abs_dir), node.id)
    if under:
        raise ThinSpecError(
            "Node '%s' still has nodes under it (%s). Move or retire them first."
            % (node.id, ", ".join(c.id for c in under))
        )
    hist = abs_dir / HISTORY_DIR
    hist.mkdir(parents=True, exist_ok=True)
    archived = hist / ("%s.v%d.md" % (node.id, node.version))
    shutil.move(str(node.path), str(archived))
    return archived


def create_node(abs_dir: Path, node_id: str, title: str, parent: Optional[str],
                summary: str = "", invariants: Optional[List[str]] = None,
                kind: Optional[str] = None) -> Path:
    check_id(node_id)
    nodes = load_nodes(abs_dir)
    if node_id in nodes:
        raise ThinSpecError("A node with id '%s' already exists." % node_id)
    if parent and parent not in nodes:
        raise ThinSpecError("Parent node '%s' does not exist." % parent)
    if not parent and roots(nodes):
        raise ThinSpecError("There is already a root node ('%s'); give this one a parent." % roots(nodes)[0].id)
    kind = kind or ("design" if parent else "core")
    if kind not in KINDS or (kind == "core") != (not parent):
        raise ThinSpecError(
            "A node under another is a design (a decision) or a component (a part of the system that "
            "carries designs out); got kind '%s'." % kind
        )
    if kind == "design" and nodes[parent].kind == "component":
        raise ThinSpecError(
            "'%s' is a component. A design is a decision, and it does not sit under what carries it out: "
            "put it under the core or under another design." % parent
        )
    hint = {
        "core": "(one or two sentences: the key insight this system is built on)",
        "design": "(one or two sentences: the decision, and the other way that was turned down)",
        "component": "(one or two sentences: what this part of the system is and what it does)",
    }[kind]
    inv = "\n".join("- %s" % i for i in (invariants or [])) or "- (state the rule that must always hold)"
    text = (
        "---\nid: %s\ntitle: %s\nkind: %s\nparent: %s\nversion: 1\n---\n\n%s\n\n## Invariants\n\n%s\n\n## Bans\n"
        % (node_id, title, kind, parent or "", summary or hint, inv)
    )
    abs_dir.mkdir(parents=True, exist_ok=True)
    path = abs_dir / ("%s.md" % node_id)
    if path.exists():
        raise ThinSpecError("%s already exists." % path.name)
    path.write_text(text, encoding="utf-8")
    return path


def add_ban(node: Node, text: str) -> None:
    """Append one bullet to the node's Bans section, creating the section if needed."""
    assert node.path is not None
    text = " ".join(text.split())
    lines = node.path.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line)
        if m and m.group(1).strip().lower() in BAN_NAMES:
            start = i
            break
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", "## Bans", "", "- %s" % text]
    else:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if SECTION_RE.match(lines[j]):
                end = j
                break
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        insert = ["- %s" % text] if end > start + 1 else ["", "- %s" % text]
        lines[end:end] = insert
    node.path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def archive_and_bump(abs_dir: Path, node: Node) -> Tuple[int, int, Path]:
    """Copy the current file to history/<id>.v<N>.md and bump the version in place."""
    assert node.path is not None
    hist = abs_dir / HISTORY_DIR
    hist.mkdir(parents=True, exist_ok=True)
    archived = hist / ("%s.v%d.md" % (node.id, node.version))
    shutil.copyfile(str(node.path), str(archived))
    new_version = node.version + 1
    node.path.write_text(
        _set_meta(node.path.read_text(encoding="utf-8"), "version", str(new_version)),
        encoding="utf-8",
    )
    return node.version, new_version, archived


def archive_edit(abs_dir: Path, node: Node) -> Tuple[int, Path]:
    """Keep the current text as history/<id>.v<N>.e<k>.md and leave the version as it is.

    For a rewording: the decision the node states is the same, so it takes no new number.
    Returns (which rewording of this version it is, where the text was kept).
    """
    assert node.path is not None
    hist = abs_dir / HISTORY_DIR
    hist.mkdir(parents=True, exist_ok=True)
    k = 1
    while (hist / ("%s.v%d.e%d.md" % (node.id, node.version, k))).exists():
        k += 1
    kept = hist / ("%s.v%d.e%d.md" % (node.id, node.version, k))
    shutil.copyfile(str(node.path), str(kept))
    return k, kept


def restore(abs_dir: Path, node: Node, to_version: Optional[int] = None) -> Tuple[int, int, int]:
    """Bring an earlier version's text back, as a new version.

    The current text is archived first, as in any revision, so the switch can
    itself be switched back. Without `to_version` it is the version before the
    current one. Returns (the version left, the version restored, the new version).
    """
    assert node.path is not None
    kept = [v for v, _ in history(abs_dir, node.id)]
    if to_version is None:
        if not kept:
            raise ThinSpecError("Node '%s' has no earlier version to switch back to." % node.id)
        to_version = max(kept)
    source = abs_dir / HISTORY_DIR / ("%s.v%d.md" % (node.id, to_version))
    if to_version not in kept or not source.is_file():
        raise ThinSpecError(
            "Node '%s' has no archived version %d. Kept versions: %s."
            % (node.id, to_version, ", ".join("v%d" % v for v in kept) or "none")
        )
    text = source.read_text(encoding="utf-8")
    left, new, _ = archive_and_bump(abs_dir, node)
    text = _set_meta(text, "version", str(new))
    # The text comes back; the node's place does not. Where it sits and its order among the nodes
    # beside it stay as they are now: a place changes by a move, which is recorded and verified.
    if node.parent is not None:
        text = _set_meta(text, "parent", node.parent)
    if node.order is not None:
        text = _set_meta(text, "order", str(node.order))
    node.path.write_text(text, encoding="utf-8")
    return left, to_version, new


def history(abs_dir: Path, node_id: str) -> List[Tuple[int, Node]]:
    """Archived earlier versions of a node, oldest first."""
    out: List[Tuple[int, Node]] = []
    hist = abs_dir / HISTORY_DIR
    if not hist.is_dir():
        return out
    pat = re.compile(r"^%s\.v(\d+)\.md$" % re.escape(node_id))
    for p in hist.iterdir():
        m = pat.match(p.name)
        if m:
            out.append((int(m.group(1)), parse_node(p.read_text(encoding="utf-8"), node_id, p)))
    return sorted(out, key=lambda t: t[0])
