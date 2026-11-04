"""Goal-tree helpers: find, walk, number, add, move, remove, inherit style."""
from __future__ import annotations

from typing import Iterator, Optional

from .models import Node, NodeKind, Project


def walk(node: Node, parent: Optional[Node] = None) -> Iterator[tuple[Node, Optional[Node]]]:
    yield node, parent
    for child in node.children:
        yield from walk(child, node)


def find(project: Project, node_id: str) -> Node:
    for n, _ in walk(project.root):
        if n.id == node_id:
            return n
    raise KeyError(f"node not found: {node_id}")


def parent_of(project: Project, node_id: str) -> Optional[Node]:
    for n, p in walk(project.root):
        if n.id == node_id:
            return p
    raise KeyError(node_id)


def ancestors(project: Project, node_id: str) -> list[Node]:
    """Root first, excluding the node itself."""
    path: list[Node] = []

    def _dfs(n: Node, trail: list[Node]) -> bool:
        if n.id == node_id:
            path.extend(trail)
            return True
        return any(_dfs(c, trail + [n]) for c in n.children)

    _dfs(project.root, [])
    return path


def leaves(project: Project) -> list[Node]:
    """Leaves in story (depth-first) order."""
    return [n for n, _ in walk(project.root) if n.is_leaf]


def numbering(project: Project) -> dict[str, str]:
    """Display numbers like '1', '1.2', '2.1.3' (root has '')."""
    out: dict[str, str] = {project.root.id: ""}

    def _num(n: Node, prefix: str) -> None:
        for i, c in enumerate(n.children, start=1):
            label = f"{prefix}.{i}" if prefix else f"{i}"
            out[c.id] = label
            _num(c, label)

    _num(project.root, "")
    return out


def add_child(project: Project, parent_id: str, node: Node, index: Optional[int] = None) -> Node:
    parent = find(project, parent_id)
    if parent.is_leaf:
        # turning a leaf into a goal node keeps its goal text
        parent.kind = NodeKind.goal
        parent.script = None
    if index is None or index >= len(parent.children):
        parent.children.append(node)
    else:
        parent.children.insert(max(index, 0), node)
    return node


def remove(project: Project, node_id: str) -> Node:
    if node_id == project.root.id:
        raise ValueError("cannot remove the root")
    parent = parent_of(project, node_id)
    assert parent is not None
    node = find(project, node_id)
    parent.children = [c for c in parent.children if c.id != node_id]
    gone = {n.id for n, _ in walk(node)}
    project.dependencies = [d for d in project.dependencies if d.from_id not in gone and d.to_id not in gone]
    return node


def move(project: Project, node_id: str, new_parent_id: str, index: int) -> None:
    if node_id == new_parent_id or any(a.id == node_id for a in ancestors(project, new_parent_id)):
        raise ValueError("cannot move a node inside itself")
    parent = parent_of(project, node_id)
    assert parent is not None
    node = find(project, node_id)
    parent.children = [c for c in parent.children if c.id != node_id]
    target = find(project, new_parent_id)
    if target.is_leaf:
        target.kind = NodeKind.goal
        target.script = None
    target.children.insert(max(0, min(index, len(target.children))), node)


def effective_style(project: Project, node_id: str) -> dict[str, str]:
    """Project style, then each ancestor's overrides, then the node's own."""
    style = {k: v for k, v in project.style.model_dump().items() if v}
    for n in ancestors(project, node_id) + [find(project, node_id)]:
        style.update({k: v for k, v in n.style_overrides.items() if v})
    return style


def outline(project: Project, max_depth: int = 6) -> str:
    """Human/LLM-readable outline of the whole tree."""
    nums = numbering(project)
    lines: list[str] = []
    for n, _ in walk(project.root):
        if n.id == project.root.id:
            lines.append(f"PROJECT GOAL: {project.goal}")
            continue
        depth = nums[n.id].count(".")
        if depth >= max_depth:
            continue
        secs = f" ~{n.duration.likely_s:.0f}s" if n.duration.likely_s else ""
        lines.append(f"{'  ' * (depth + 1)}{nums[n.id]} [{n.kind.value}] {n.title}: {n.goal}{secs}")
    return "\n".join(lines)
