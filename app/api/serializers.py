"""Everything the UI displays is computed here, on the server: module states,
codes, coordinates, percentages, "stuck for N days", meta labels. The Vue app
renders these payloads and never derives anything itself."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from ..graph import EDGE_ANCHOR_Y, CANVAS_BOTTOM_PAD, MIN_CANVAS_H, MARGIN_X, NODE_W, edge_style
from ..models import Insight, Module, ModuleDep, Roadmap, StudySession
from ..util import humanize_ago, humanize_minutes, month_day, parse_weekdays

KIND_LABELS = {
    "video": "Video",
    "article": "Article",
    "course": "Course",
    "book": "Textbook",
    "audio": "Audio",
    "practice": "Practice",
}


def _iso(dt):
    return dt.isoformat() if dt else None


def _done_minutes_by_module(sa, module_ids):
    if not module_ids:
        return {}
    rows = sa.execute(
        select(
            StudySession.module_id,
            func.sum(func.coalesce(StudySession.actual_minutes, StudySession.planned_minutes)),
        )
        .where(StudySession.module_id.in_(module_ids), StudySession.status == "done")
        .group_by(StudySession.module_id)
    ).all()
    return {mid: int(total or 0) for mid, total in rows}


def _stuck_days(sa, module_id, today) -> int | None:
    last = sa.execute(
        select(func.max(StudySession.planned_date)).where(
            StudySession.module_id == module_id, StudySession.status == "stuck"
        )
    ).scalar()
    return (today - last).days if last else None


def _done_dates(sa, roadmap_id) -> set[date]:
    rows = sa.execute(
        select(StudySession.planned_date)
        .join(Module, Module.id == StudySession.module_id)
        .where(Module.roadmap_id == roadmap_id, StudySession.status == "done")
    ).all()
    return {r[0] for r in rows}


def _streak(done_dates: set[date], today: date) -> int:
    day = today if today in done_dates else today - timedelta(days=1)
    streak = 0
    while day in done_dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def _meta_label(module, done_q, est, stuck_days, stuck_prereq, is_capstone) -> str:
    state = module.state
    if state == "completed":
        return f"{est} / {est} sessions" if est else "complete"
    if state == "inprogress":
        return "ongoing" if not est else f"session {min(done_q + 1, est)} of {est}"
    if state == "available":
        return "ongoing · ready" if not est else f"{est} sessions · ready"
    if state == "stuck":
        return f"stuck {stuck_days} days" if stuck_days else "stuck"
    if stuck_prereq is not None:
        return f"needs {stuck_prereq.title}"
    return "capstone · locked" if is_capstone else "locked"


def _last_done_date(sa, roadmap_id) -> date | None:
    return sa.execute(
        select(func.max(StudySession.planned_date))
        .join(Module, Module.id == StudySession.module_id)
        .where(Module.roadmap_id == roadmap_id, StudySession.status == "done")
    ).scalar()


def _max_stuck_days(sa, rm, today) -> int | None:
    days = [
        d
        for m in rm.modules
        if m.state == "stuck"
        for d in [_stuck_days(sa, m.id, today)]
        if d is not None
    ]
    return max(days) if days else None


def roadmap_card(sa, rm: Roadmap, today: date) -> dict:
    top = [m for m in rm.modules if m.parent_module_id is None]
    total = len(top)
    done = sum(1 for m in top if m.state == "completed")
    percent = round(done / total * 100) if total else 0

    active_days = parse_weekdays(rm.weekdays)
    hours_per_week = round(rm.minutes_per_day * len(active_days) / 60, 1)
    last_done = _last_done_date(sa, rm.id)
    on_pace = last_done is not None and (today - last_done).days <= 2
    if on_pace:
        pace_label = f"on pace · {hours_per_week:g} hrs / week"
    elif active_days == {1, 2, 3, 4, 5}:
        pace_label = "weekday sessions"
    else:
        pace_label = f"{len(active_days)} days / week"

    stuck_days = _max_stuck_days(sa, rm, today)
    stuck = any(m.state == "stuck" for m in top)
    return {
        "id": rm.id,
        "name": rm.topic,
        "color": rm.color,
        "status": rm.status,
        "done_modules": done,
        "total_modules": total,
        "percent": percent,
        "count_label": f"{done} of {total} modules",
        "percent_label": f"{percent}%",
        "pace_label": pace_label,
        "on_pace": on_pace,
        "hours_per_week": hours_per_week,
        "streak_days": _streak(_done_dates(sa, rm.id), today),
        "last_session_label": (
            f"last session {humanize_ago(last_done, today)}" if last_done else "no sessions yet"
        ),
        "stuck": stuck,
        "stuck_label": (
            f"stuck on a module for {stuck_days} days" if stuck and stuck_days else None
        ),
    }


def _submodule_dict(sub, done_min, mpd):
    est = sub.est_sessions
    done_q = done_min.get(sub.id, 0) // mpd
    return {
        "id": sub.id,
        "code": sub.code,
        "title": sub.title,
        "state": sub.state,
        "est_sessions": est,
        "done_sessions": min(done_q, est) if est else done_q,
    }


def roadmap_detail(sa, rm: Roadmap, today: date) -> dict:
    mods = list(rm.modules)
    top = [m for m in mods if m.parent_module_id is None]
    all_ids = [m.id for m in mods]
    top_ids = {m.id for m in top}
    by_id = {m.id: m for m in mods}

    dep_rows = sa.execute(
        select(ModuleDep).where(ModuleDep.module_id.in_(all_ids))
    ).scalars().all() if all_ids else []
    top_edges = [
        (d.prereq_module_id, d.module_id)
        for d in dep_rows
        if d.prereq_module_id in top_ids and d.module_id in top_ids
    ]
    prereqs_of: dict[int, list[Module]] = {m.id: [] for m in top}
    has_dependents: set[int] = set()
    for prereq, dep in top_edges:
        prereqs_of[dep].append(by_id[prereq])
        has_dependents.add(prereq)

    done_min = _done_minutes_by_module(sa, all_ids)
    mpd = max(rm.minutes_per_day, 1)

    nodes = []
    for m in top:
        est = m.est_sessions
        done_q = done_min.get(m.id, 0) // mpd
        stuck_days = _stuck_days(sa, m.id, today) if m.state == "stuck" else None
        stuck_prereq = next((p for p in prereqs_of[m.id] if p.state == "stuck"), None)
        is_capstone = m.id not in has_dependents
        nodes.append({
            "id": m.id,
            "code": m.code,
            "title": m.title,
            "title_native": m.title_native,
            "summary": m.summary,
            "state": m.state,
            "est_sessions": est,
            "est_minutes": m.est_minutes,
            "done_sessions": min(done_q, est) if est else done_q,
            "x": m.layout_x,
            "y": m.layout_y,
            "meta_label": _meta_label(m, done_q, est, stuck_days, stuck_prereq, is_capstone),
            "is_capstone": is_capstone,
            "stuck_days": stuck_days,
            "submodules": [_submodule_dict(s, done_min, mpd) for s in m.children],
        })

    edges = []
    for prereq_id, dep_id in top_edges:
        a, b = by_id[prereq_id], by_id[dep_id]
        edges.append({
            "from": prereq_id,
            "to": dep_id,
            "style": edge_style(a.state, b.state),
            "points": {
                "x1": a.layout_x + NODE_W,
                "y1": a.layout_y + EDGE_ANCHOR_Y,
                "x2": b.layout_x,
                "y2": b.layout_y + EDGE_ANCHOR_Y,
            },
        })

    counts = {s: sum(1 for m in top if m.state == s)
              for s in ("completed", "inprogress", "available", "stuck", "locked")}
    counts["total"] = len(top)
    counts["percent"] = round(counts["completed"] / len(top) * 100) if top else 0

    adaptations = []
    for ins in rm.insights:
        if ins.kind != "replan" or not ins.payload:
            continue
        target = by_id.get(ins.payload.get("module_id"))
        if target is None:
            continue
        stuck_days = _stuck_days(sa, target.id, today)
        adaptations.append({
            "insight_id": ins.id,
            "module_id": target.id,
            "module_code": target.code,
            "title": (
                f"{target.title} — stuck {stuck_days} days" if stuck_days else target.title
            ),
            "body": ins.text,
            "steps": ins.payload.get("steps", []),
            "created_at": _iso(ins.created_at),
        })

    max_x = max((m.layout_x for m in top), default=0)
    max_y = max((m.layout_y for m in top), default=0)
    card = roadmap_card(sa, rm, today)
    days_left = (rm.target_date - today).days if rm.target_date else None
    module_word = "module" if len(top) == 1 else "modules"
    subtitle = f"{len(top)} {module_word} · the plan reshapes as you go"
    if rm.goal:
        subtitle = f"{rm.goal} · {subtitle}"
    return {
        "roadmap": {
            **card,
            "topic": rm.topic,
            "goal": rm.goal,
            "level": rm.level,
            "minutes_per_day": rm.minutes_per_day,
            "weekdays": sorted(parse_weekdays(rm.weekdays)),
            "created_at": _iso(rm.created_at),
            "target_date": _iso(rm.target_date),
            "days_left": days_left,
            "subtitle": subtitle,
            "header_stats": [
                f"{days_left} days left · {card['hours_per_week']:g} hrs / week"
                if days_left is not None else f"{card['hours_per_week']:g} hrs / week",
                f"{counts['completed']} of {counts['total']} modules complete",
            ],
        },
        "modules": nodes,
        "edges": edges,
        "counts": counts,
        "canvas": {
            "width": max_x + NODE_W + MARGIN_X,
            "height": max(max_y + CANVAS_BOTTOM_PAD, MIN_CANVAS_H),
        },
        "adaptations": adaptations,
    }


def resource_dict(r, today: date) -> dict:
    verified = r.http_status is not None and 200 <= r.http_status < 400
    if verified and r.verified_at:
        verified_label = f"verified {humanize_ago(r.verified_at.date(), today)}"
    else:
        verified_label = "unverified"
    return {
        "id": r.id,
        "title": r.title,
        "url": r.url,
        "kind": r.kind,
        "kind_label": KIND_LABELS.get(r.kind, r.kind.title()),
        "source_domain": r.source_domain,
        "duration_min": r.duration_min,
        "is_paid": r.is_paid,
        "relevance": r.relevance,
        "http_status": r.http_status,
        "verified": verified,
        "verified_at": _iso(r.verified_at),
        "verified_label": verified_label,
    }


def module_detail(sa, m: Module, today: date) -> dict:
    rm = m.roadmap
    mpd = max(rm.minutes_per_day, 1)
    done_min = _done_minutes_by_module(sa, [m.id] + [s.id for s in m.children])
    est = m.est_sessions
    done_q = done_min.get(m.id, 0) // mpd
    stuck_days = _stuck_days(sa, m.id, today) if m.state == "stuck" else None

    prereq_rows = sa.execute(
        select(Module)
        .join(ModuleDep, ModuleDep.prereq_module_id == Module.id)
        .where(ModuleDep.module_id == m.id)
    ).scalars().all()
    dependent_count = sa.execute(
        select(func.count()).select_from(ModuleDep).where(ModuleDep.prereq_module_id == m.id)
    ).scalar()
    stuck_prereq = next((p for p in prereq_rows if p.state == "stuck"), None)
    is_capstone = m.parent_module_id is None and not dependent_count

    today_minutes = sa.execute(
        select(func.sum(StudySession.planned_minutes)).where(
            StudySession.module_id == m.id,
            StudySession.planned_date == today,
            StudySession.status == "planned",
        )
    ).scalar() or 0

    last_verified = max(
        (r.verified_at for r in m.resources if r.verified_at), default=None
    )
    return {
        "id": m.id,
        "roadmap_id": rm.id,
        "roadmap_name": rm.topic,
        "color": rm.color,
        "code": m.code,
        "title": m.title,
        "title_native": m.title_native,
        "summary": m.summary,
        "state": m.state,
        "est_sessions": est,
        "est_minutes": m.est_minutes,
        "done_sessions": min(done_q, est) if est else done_q,
        "meta_label": _meta_label(m, done_q, est, stuck_days, stuck_prereq, is_capstone),
        "stuck_days": stuck_days,
        "is_capstone": is_capstone,
        "parent_module_id": m.parent_module_id,
        "today_planned_minutes": int(today_minutes),
        "verified_label": (
            f"resources verified {humanize_ago(last_verified.date(), today)}"
            if last_verified else "resources not verified yet"
        ),
        "prerequisites": [
            {"id": p.id, "code": p.code, "title": p.title, "state": p.state}
            for p in prereq_rows
        ],
        "submodules": [_submodule_dict(s, done_min, mpd) for s in m.children],
        "resources": [resource_dict(r, today) for r in m.resources],
    }


def _future_label(d: date, today: date) -> str:
    n = (d - today).days
    if n <= 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n < 7:
        return f"on {d:%A}"
    return f"on {month_day(d)}"


def today_payload(sa, today: date) -> dict:
    rows = sa.execute(
        select(StudySession, Module, Roadmap)
        .join(Module, Module.id == StudySession.module_id)
        .join(Roadmap, Roadmap.id == Module.roadmap_id)
        .where(StudySession.planned_date == today)
        .order_by(Roadmap.id, StudySession.id)
    ).all()

    sessions = []
    for s, m, rm in rows:
        sessions.append({
            "id": s.id,
            "module_id": m.id,
            "module_code": m.code,
            "module_title": m.title,
            "roadmap_id": rm.id,
            "roadmap_name": rm.topic,
            "color": rm.color,
            "minutes": s.planned_minutes,
            "actual_minutes": s.actual_minutes,
            "status": s.status,
            "label": s.note or m.title,
        })

    pending = [s for s in sessions if s["status"] == "planned"]
    total_planned = sum(s["minutes"] for s in sessions)
    next_date = sa.execute(
        select(func.min(StudySession.planned_date)).where(
            StudySession.status == "planned", StudySession.planned_date > today
        )
    ).scalar()

    return {
        "date": today.isoformat(),
        "sessions": sessions,
        "count": len(sessions),
        "total_minutes": total_planned,
        "sub_label": (
            f"{len(sessions)} session{'s' if len(sessions) != 1 else ''} · "
            f"about {humanize_minutes(total_planned)}"
            if sessions else "nothing scheduled today"
        ),
        "all_done": bool(sessions) and not pending,
        "next_session_date": _iso(next_date),
        "next_session_label": (
            f"next session {_future_label(next_date, today)}" if next_date else None
        ),
    }


def stats_payload(sa, rm: Roadmap, today: date) -> dict:
    top = [m for m in rm.modules if m.parent_module_id is None]
    done_dates = _done_dates(sa, rm.id)

    week_minutes = sa.execute(
        select(func.sum(func.coalesce(StudySession.actual_minutes, StudySession.planned_minutes)))
        .join(Module, Module.id == StudySession.module_id)
        .where(
            Module.roadmap_id == rm.id,
            StudySession.status == "done",
            StudySession.planned_date >= today - timedelta(days=6),
        )
    ).scalar() or 0

    stuck_modules = []
    for m in rm.modules:
        if m.state != "stuck":
            continue
        spent = sa.execute(
            select(func.sum(StudySession.actual_minutes)).where(
                StudySession.module_id == m.id,
                StudySession.status.in_(("done", "stuck")),
            )
        ).scalar() or 0
        last_note = sa.execute(
            select(StudySession.note)
            .where(StudySession.module_id == m.id, StudySession.status == "stuck")
            .order_by(StudySession.planned_date.desc())
            .limit(1)
        ).scalar()
        stuck_modules.append({
            "module_id": m.id,
            "code": m.code,
            "title": m.title,
            "stuck_days": _stuck_days(sa, m.id, today),
            "est_minutes": m.est_minutes,
            "actual_minutes": int(spent),
            "note": last_note,
        })

    heatmap = []
    minutes_by_day = dict(
        sa.execute(
            select(
                StudySession.planned_date,
                func.sum(func.coalesce(StudySession.actual_minutes, StudySession.planned_minutes)),
                )
            .join(Module, Module.id == StudySession.module_id)
            .where(
                Module.roadmap_id == rm.id,
                StudySession.status == "done",
                StudySession.planned_date > today - timedelta(days=56),
            )
            .group_by(StudySession.planned_date)
        ).all()
    )
    for i in range(55, -1, -1):
        d = today - timedelta(days=i)
        heatmap.append({"date": d.isoformat(), "minutes": int(minutes_by_day.get(d, 0) or 0)})

    insights = [
        {
            "id": ins.id,
            "kind": ins.kind,
            "text": ins.text,
            "action_kind": ins.action_kind,
            "action_label": (ins.payload or {}).get("action_label"),
            "created_at": _iso(ins.created_at),
            "ago_label": humanize_ago(ins.created_at.date(), today),
        }
        for ins in sorted(rm.insights, key=lambda i: i.created_at, reverse=True)
    ]

    return {
        "roadmap_id": rm.id,
        "metrics": {
            "streak_days": _streak(done_dates, today),
            "hours_this_week": round(int(week_minutes) / 60, 1),  # trailing 7 days
            "modules_done": sum(1 for m in top if m.state == "completed"),
            "modules_total": len(top),
            "projected_finish": _iso(rm.target_date),
            "projected_finish_label": month_day(rm.target_date) if rm.target_date else None,
            "days_left": (rm.target_date - today).days if rm.target_date else None,
        },
        "stuck_modules": stuck_modules,
        "insights": insights,
        "heatmap": heatmap,
    }


def run_payload(run) -> dict:
    return {
        "id": run.id,
        "roadmap_id": run.roadmap_id,
        "kind": run.kind,
        "status": run.status,
        "steps": run.steps or [],
        "error": run.error,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
    }
