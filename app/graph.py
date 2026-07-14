"""Graph logic for roadmap DAGs: topological sort, validation, module-state
derivation and the layered layout.

Everything above `recompute_roadmap` is pure — plain ids, tuples and dicts —
so the algorithms can be unit-tested without a database. Edges are always
(prereq_id, dependent_id): the edge points in the direction of study.
"""

from __future__ import annotations

import heapq

# Layout constants, matching the design bundle (Roadmap Agent App.dc.html):
# 170px-wide node cards on a 208px horizontal pitch, layers spread vertically
# on a 138px pitch around the y=288 midline; edges anchor 31px into the card.
NODE_W = 170
PITCH_X = 208
MARGIN_X = 24
CENTER_Y = 288
PITCH_Y = 138
EDGE_ANCHOR_Y = 31
CANVAS_BOTTOM_PAD = 178
MIN_CANVAS_H = 466


class GraphError(ValueError):
    """Raised when a proposed graph is not a usable DAG. `problems` holds
    human-readable messages that stage 2 feeds back to the LLM on retry."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _adjacency(node_ids, edges):
    order = {n: i for i, n in enumerate(node_ids)}
    dependents: dict = {n: [] for n in node_ids}
    indegree = {n: 0 for n in node_ids}
    for prereq, dep in edges:
        if prereq not in order or dep not in order:
            raise GraphError([f"edge ({prereq} -> {dep}) references an unknown module"])
        dependents[prereq].append(dep)
        indegree[dep] += 1
    return order, dependents, indegree


def topo_sort(node_ids, edges) -> list:
    """Deterministic Kahn topological sort (ties resolved by input order).
    Raises GraphError naming the cycle members if the graph is not a DAG."""
    order, dependents, indegree = _adjacency(node_ids, edges)
    ready = [(order[n], n) for n in node_ids if indegree[n] == 0]
    heapq.heapify(ready)
    result = []
    while ready:
        _, node = heapq.heappop(ready)
        result.append(node)
        for dep in dependents[node]:
            indegree[dep] -= 1
            if indegree[dep] == 0:
                heapq.heappush(ready, (order[dep], dep))
    if len(result) != len(node_ids):
        stuck_in_cycle = [n for n in node_ids if n not in set(result)]
        raise GraphError([f"cycle detected among modules: {stuck_in_cycle}"])
    return result


def validate_graph(node_ids, edges, min_nodes=8, max_nodes=24) -> list[str]:
    """Structural checks for a proposed roadmap graph. Returns a list of
    problems (empty = valid): size bounds, self-loops, dangling prerequisite
    references, cycles, exactly one root and exactly one capstone leaf."""
    problems = []
    known = set(node_ids)
    if len(node_ids) < min_nodes:
        problems.append(f"only {len(node_ids)} modules — need at least {min_nodes}")
    if len(node_ids) > max_nodes:
        problems.append(f"{len(node_ids)} modules — keep it to {max_nodes} or fewer")
    for prereq, dep in edges:
        if prereq == dep:
            problems.append(f"module {prereq} lists itself as a prerequisite")
        if prereq not in known:
            problems.append(f"prerequisite {prereq} (needed by {dep}) does not exist")
        if dep not in known:
            problems.append(f"module {dep} (depending on {prereq}) does not exist")
    if problems:
        return problems

    try:
        topo_sort(node_ids, edges)
    except GraphError as exc:
        problems.extend(exc.problems)
        return problems

    has_prereq = {dep for _, dep in edges}
    has_dependent = {prereq for prereq, _ in edges}
    roots = [n for n in node_ids if n not in has_prereq]
    leaves = [n for n in node_ids if n not in has_dependent]
    if len(roots) != 1:
        problems.append(f"expected exactly one starting module, found {len(roots)}: {roots}")
    if len(leaves) != 1:
        problems.append(f"expected exactly one capstone module, found {len(leaves)}: {leaves}")
    return problems


def layers_by_longest_path(node_ids, edges) -> dict:
    """layer(n) = length of the longest prerequisite chain leading to n."""
    _, dependents, _ = _adjacency(node_ids, edges)
    layer = {n: 0 for n in node_ids}
    for node in topo_sort(node_ids, edges):
        for dep in dependents[node]:
            layer[dep] = max(layer[dep], layer[node] + 1)
    return layer


def compute_layout(node_ids, edges) -> tuple[dict, dict]:
    """Layered layout. Returns ({id: (x, y)}, {"width", "height"}).

    x comes from the longest-path layer on a fixed pitch; nodes inside a
    layer keep input order and spread vertically around the midline."""
    if not node_ids:
        return {}, {"width": NODE_W + 2 * MARGIN_X, "height": MIN_CANVAS_H}
    layer = layers_by_longest_path(node_ids, edges)
    columns: dict[int, list] = {}
    for n in node_ids:  # input order == vertical order inside a column
        columns.setdefault(layer[n], []).append(n)

    pos = {}
    for col, members in columns.items():
        x = MARGIN_X + col * PITCH_X
        top = CENTER_Y - (len(members) - 1) * PITCH_Y // 2
        for i, n in enumerate(members):
            pos[n] = (x, top + i * PITCH_Y)

    width = MARGIN_X * 2 + max(layer.values()) * PITCH_X + NODE_W
    height = max(max(y for _, y in pos.values()) + CANVAS_BOTTOM_PAD, MIN_CANVAS_H)
    return pos, {"width": width, "height": height}


def derive_states(node_ids, edges, info) -> dict:
    """Derive every module's state from facts, in topological order.

    info[id] = {est_sessions, done_sessions, sticky_stuck, manual_completed,
                children_total, children_completed}

    Rules (first match wins):
      * all children of a split module completed  -> completed
      * flagged stuck                             -> stuck (until resolved)
      * marked done / all estimated sessions done -> completed
      * any session done                          -> inprogress
      * every prereq completed or inprogress      -> available
      * otherwise                                 -> locked
    """
    prereqs: dict = {n: [] for n in node_ids}
    for prereq, dep in edges:
        prereqs[dep].append(prereq)

    state = {}
    for n in topo_sort(node_ids, edges):
        i = info[n]
        if i.get("children_total") and i["children_completed"] >= i["children_total"]:
            state[n] = "completed"
        elif i.get("sticky_stuck"):
            state[n] = "stuck"
        elif i.get("manual_completed") or (
            i["est_sessions"] > 0 and i["done_sessions"] >= i["est_sessions"]
        ):
            state[n] = "completed"
        elif i["done_sessions"] > 0:
            state[n] = "inprogress"
        elif all(state[p] in ("completed", "inprogress") for p in prereqs[n]):
            state[n] = "available"
        else:
            state[n] = "locked"
    return state


def edge_style(from_state: str, to_state: str) -> str:
    """Edge style per the design: stuck targets win, then done/active flows
    out of completed/in-progress modules, everything else is locked."""
    if to_state == "stuck":
        return "stuck"
    if from_state == "completed":
        return "done"
    if from_state == "inprogress":
        return "active"
    return "locked"


# --- database-aware entry point -------------------------------------------


def recompute_roadmap(sa, roadmap) -> None:
    """Recompute persisted module states and layout coordinates for one
    roadmap. Call after any mutation (sessions, splits, new modules)."""
    from sqlalchemy import func, select

    from .models import Module, ModuleDep, StudySession

    # The session runs with autoflush=False, so make pending inserts (new
    # modules and edges added by the caller) visible to the queries below.
    sa.flush()

    modules = list(
        sa.execute(select(Module).where(Module.roadmap_id == roadmap.id).order_by(Module.id))
        .scalars()
        .all()
    )
    if not modules:
        return
    ids = [m.id for m in modules]
    deps = sa.execute(select(ModuleDep).where(ModuleDep.module_id.in_(ids))).scalars().all()
    edges = [(d.prereq_module_id, d.module_id) for d in deps]

    mpd = max(roadmap.minutes_per_day, 1)
    done_minutes = dict(
        sa.execute(
            select(
                StudySession.module_id,
                func.sum(
                    func.coalesce(StudySession.actual_minutes, StudySession.planned_minutes)
                ),
            )
            .where(StudySession.module_id.in_(ids), StudySession.status == "done")
            .group_by(StudySession.module_id)
        ).all()
    )

    children: dict[int, list] = {}
    for m in modules:
        if m.parent_module_id:
            children.setdefault(m.parent_module_id, []).append(m.id)

    info = {}
    for m in modules:
        info[m.id] = {
            "est_sessions": m.est_sessions,
            # sessions are day-quota units: minutes done divided by the daily quota
            "done_sessions": (done_minutes.get(m.id, 0) or 0) // mpd,
            "sticky_stuck": m.state == "stuck",
            "manual_completed": m.state == "completed",
            "children_total": len(children.get(m.id, [])),
            "children_completed": 0,  # filled below, needs two passes
        }

    # children_completed must reflect *derived* child states, so derive twice:
    # once raw, then again with children counts in place.
    first = derive_states(ids, edges, info)
    for parent_id, kid_ids in children.items():
        info[parent_id]["children_completed"] = sum(
            1 for k in kid_ids if first[k] == "completed"
        )
    state = derive_states(ids, edges, info)

    top_ids = [m.id for m in modules if m.parent_module_id is None]
    top_set = set(top_ids)
    top_edges = [(a, b) for a, b in edges if a in top_set and b in top_set]
    pos, _canvas = compute_layout(top_ids, top_edges)

    for m in modules:
        m.state = state[m.id]
        if m.id in pos:
            m.layout_x, m.layout_y = pos[m.id]
