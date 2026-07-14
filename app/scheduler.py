"""Session scheduler. Pure Python, no LLM anywhere near it.

Walk the modules in topological order (children replace a split parent),
chunk each module's remaining minutes into sessions of `minutes_per_day`,
and place one session per active weekday. The projected finish date is
whatever day the last chunk lands on.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select

from .graph import topo_sort
from .models import Module, ModuleDep, StudySession
from .util import parse_weekdays


def _remaining_minutes(module: Module, cutoff: date) -> int:
    """Minutes of `module` not yet covered by done sessions or by planned
    sessions that survive the reschedule (anything before `cutoff`)."""
    kept = 0
    for s in module.sessions:
        if s.status == "done":
            kept += s.actual_minutes if s.actual_minutes is not None else s.planned_minutes
        elif s.status == "planned" and s.planned_date < cutoff:
            kept += s.planned_minutes
    return max(module.est_minutes - kept, 0)


def schedule_roadmap(sa, roadmap, start: date | None = None) -> date | None:
    """(Re)build the planned sessions of `roadmap` from `start` onward and
    set `roadmap.target_date`. Returns the projected finish date."""
    start = start or date.today()
    active = parse_weekdays(roadmap.weekdays)
    mpd = max(roadmap.minutes_per_day, 15)

    # autoflush is off; surface pending edges/modules before we read them.
    sa.flush()

    modules = list(
        sa.execute(
            select(Module).where(Module.roadmap_id == roadmap.id).order_by(Module.id)
        ).scalars()
    )
    if not modules:
        return None
    ids = [m.id for m in modules]
    deps = sa.execute(select(ModuleDep).where(ModuleDep.module_id.in_(ids))).scalars().all()
    edges = [(d.prereq_module_id, d.module_id) for d in deps]
    by_id = {m.id: m for m in modules}

    # Future planned sessions get rebuilt; history and today's row survive.
    sa.execute(
        delete(StudySession).where(
            StudySession.module_id.in_(ids),
            StudySession.status == "planned",
            StudySession.planned_date >= start,
        )
    )
    sa.flush()

    # Walk top-level modules in topological order; a split parent is replaced
    # in place by its children (in their own topological order).
    children: dict[int, list[int]] = {}
    for m in modules:
        if m.parent_module_id is not None:
            children.setdefault(m.parent_module_id, []).append(m.id)
    top_ids = [m.id for m in modules if m.parent_module_id is None]
    top_set = set(top_ids)
    top_edges = [(a, b) for a, b in edges if a in top_set and b in top_set]

    order: list[Module] = []
    for mid in topo_sort(top_ids, top_edges):
        kids = children.get(mid)
        if kids:
            kid_set = set(kids)
            kid_edges = [(a, b) for a, b in edges if a in kid_set and b in kid_set]
            order.extend(by_id[k] for k in topo_sort(kids, kid_edges))
        else:
            order.append(by_id[mid])

    day = start - timedelta(days=1)
    last_placed: date | None = None
    for m in order:
        if m.state == "completed" or m.est_minutes <= 0:
            continue
        remaining = _remaining_minutes(m, start)
        while remaining > 0:
            day = day + timedelta(days=1)
            while day.isoweekday() not in active:
                day += timedelta(days=1)
            chunk = min(mpd, remaining)
            sa.add(
                StudySession(
                    module_id=m.id,
                    planned_date=day,
                    planned_minutes=chunk,
                    status="planned",
                )
            )
            remaining -= chunk
            last_placed = day

    roadmap.target_date = last_placed or roadmap.target_date
    sa.flush()
    return roadmap.target_date
