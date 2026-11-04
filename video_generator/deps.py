"""Dependency graph between clip leaves: validation, ordering, staleness."""
from __future__ import annotations

from collections import defaultdict, deque

from .models import Dependency, DependencyType, NodeStatus, Project
from .tree import find, leaves, walk


class CycleError(ValueError):
    pass


def _leaf_ids(project: Project) -> set[str]:
    return {n.id for n in leaves(project)}


def upstream(project: Project, node_id: str) -> list[Dependency]:
    return [d for d in project.dependencies if d.to_id == node_id]


def downstream(project: Project, node_id: str) -> list[Dependency]:
    return [d for d in project.dependencies if d.from_id == node_id]


def add_dependency(project: Project, dep: Dependency) -> Dependency:
    ids = _leaf_ids(project)
    if dep.from_id not in ids or dep.to_id not in ids:
        raise ValueError("dependencies connect clips (leaf nodes) only")
    if dep.from_id == dep.to_id:
        raise ValueError("a clip cannot depend on itself")
    for d in project.dependencies:
        if d.from_id == dep.from_id and d.to_id == dep.to_id and d.type == dep.type:
            return d
    project.dependencies.append(dep)
    try:
        topo_order(project)
    except CycleError:
        project.dependencies.remove(dep)
        raise
    return dep


def topo_order(project: Project) -> list[str]:
    """Leaves ordered so every dependency comes first; ties keep story order."""
    order = [n.id for n in leaves(project)]
    rank = {nid: i for i, nid in enumerate(order)}
    indeg = {nid: 0 for nid in order}
    edges = defaultdict(list)
    for d in project.dependencies:
        if d.from_id in indeg and d.to_id in indeg:
            edges[d.from_id].append(d.to_id)
            indeg[d.to_id] += 1
    ready = sorted([n for n, k in indeg.items() if k == 0], key=rank.get)
    queue = deque(ready)
    out: list[str] = []
    while queue:
        n = queue.popleft()
        out.append(n)
        for m in sorted(edges[n], key=rank.get):
            indeg[m] -= 1
            if indeg[m] == 0:
                # insert keeping story order among ready nodes
                queue.append(m)
                queue = deque(sorted(queue, key=rank.get))
    if len(out) != len(order):
        raise CycleError("dependency loop detected")
    return out


def required_upstream(project: Project, node_id: str) -> list[str]:
    """All transitive upstream clips (excluding order_only), nearest last."""
    seen: list[str] = []

    def _visit(nid: str) -> None:
        for d in upstream(project, nid):
            if d.type == DependencyType.order_only:
                continue
            if d.from_id not in seen:
                _visit(d.from_id)
                seen.append(d.from_id)

    _visit(node_id)
    return seen


def mark_downstream_stale(project: Project, node_id: str) -> list[str]:
    """When a clip's chosen take changes, everything that uses it is stale."""
    stale: list[str] = []
    queue = deque([node_id])
    while queue:
        nid = queue.popleft()
        for d in downstream(project, nid):
            if d.type == DependencyType.order_only:
                continue
            n = find(project, d.to_id)
            if n.status in (NodeStatus.done, NodeStatus.needs_pick) and d.to_id not in stale:
                n.status = NodeStatus.stale
                stale.append(d.to_id)
                queue.append(d.to_id)
    return stale


def rule_based_dependencies(project: Project) -> list[Dependency]:
    """Obvious links: siblings split from one long leaf ("part 2/3") continue
    from each other; consecutive clips sharing a location set same_location."""
    from .context import effective_context

    found: list[Dependency] = []
    for n, _ in walk(project.root):
        kids = [c for c in n.children if c.is_leaf]
        for a, b in zip(kids, kids[1:]):
            if "(part" in a.title.lower() and "(part" in b.title.lower():
                found.append(Dependency(from_id=a.id, to_id=b.id, type=DependencyType.continues_from,
                                        source="rule", note="split from one long clip"))
                continue
            la = {e.item.id for e in effective_context(project, a.id) if e.item.type.value == "location" and e.origin == "this"}
            lb = {e.item.id for e in effective_context(project, b.id) if e.item.type.value == "location" and e.origin == "this"}
            if la & lb:
                found.append(Dependency(from_id=a.id, to_id=b.id, type=DependencyType.same_location,
                                        source="rule", note="same location"))
    return found
