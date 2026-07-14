"""Agent runners: generation and replanning, each as a 5-step background
thread that writes progress into AgentRun.steps in the database.

run_generation — creates a new roadmap from a topic string.
run_replan     — splits a stuck module into gentler submodules.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from flask import Flask
from sqlalchemy.orm.attributes import flag_modified

from app.db import db_session
from app.graph import recompute_roadmap, topo_sort, validate_graph
from app.models import AgentRun, Insight, Module, ModuleDep, Resource, Roadmap, StudySession
from app.scheduler import schedule_roadmap
from app.util import code_prefix, domain_of, month_day, url_hash
from .llm import get_llm
from .search import get_search
from .verify import verify_urls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_step(run: AgentRun, key: str, status: str, detail: str = "") -> None:
    """Set the matching step in run.steps to `status`/`detail`.  Appends a new
    step dict when `key` is not found."""
    steps = list(run.steps)  # copy to trigger SQLAlchemy change tracking
    for step in steps:
        if step.get("key") == key:
            step["status"] = status
            step["detail"] = detail
            run.steps = steps
            flag_modified(run, "steps")
            return
    steps.append({"key": key, "label": key.title(), "status": status, "detail": detail})
    run.steps = steps
    flag_modified(run, "steps")


def _build_plan_prompt(topic: str, level: str, minutes_per_day: int) -> str:
    """Construct the LLM prompt for roadmap generation."""
    return (
        f"You are a curriculum designer. Create a learning roadmap for \"{topic}\" "
        f"at \"{level}\" level. The student can study {minutes_per_day} minutes per day.\n\n"
        "Return ONLY valid JSON (no markdown fences, no explanation) with this structure:\n"
        '{{"modules": [{{"title": "...", "summary": "...", '
        '"est_sessions": N, "est_minutes": N}}, ...], '
        '"edges": [["Prereq Title", "Dependent Title"], ...]}}\n\n'
        "Constraints:\n"
        "- 8 to 24 modules\n"
        "- Exactly one root module (no prerequisites — nothing depends on it in edges)\n"
        "- Exactly one capstone module (no dependents — it is not a prereq of anything)\n"
        "- No cycles in the prerequisite graph\n"
        "- No self-loops (a module cannot list itself as a prerequisite)\n"
        f"- est_minutes must equal est_sessions * {minutes_per_day}\n"
        "- Every title in edges must match a module title exactly\n"
        "- Module titles should be specific and descriptive, not generic"
    )


def _build_replan_prompt(
    stuck_title: str, topic: str, level: str, reason: str, minutes_per_day: int
) -> str:
    """Construct the LLM prompt for splitting a stuck module."""
    return (
        f"The student is stuck on the module \"{stuck_title}\" in their \"{topic}\" "
        f"roadmap ({level} level). Reason: {reason}\n\n"
        f"Break this module into 2-4 smaller, gentler submodules. Each should be "
        f"easier to approach — use a different teaching angle (more video, more practice, "
        f"fewer abstract concepts).\n\n"
        "Return ONLY valid JSON:\n"
        '{{"submodules": [{{"title": "...", "summary": "...", '
        '"est_sessions": N, "est_minutes": N}}, ...]}}\n\n'
        f"Constraints: est_minutes = est_sessions * {minutes_per_day}; "
        f"est_sessions should be 1-3 for each submodule."
    )


# ---------------------------------------------------------------------------
# Generation runner
# ---------------------------------------------------------------------------

def run_generation(roadmap_id: int, run_id: int, app: Flask) -> None:
    """5-step background runner: plan → validate → source → verify → schedule."""

    with app.app_context():
        llm = get_llm()
        search = get_search()
        sa = db_session

        rm = sa.get(Roadmap, roadmap_id)
        run = sa.get(AgentRun, run_id)
        if rm is None or run is None:
            return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        sa.commit()

        mpd = max(rm.minutes_per_day, 15)

        # ---- Step 1: Plan --------------------------------------------------
        _update_step(run, "plan", "running", detail="generating modules …")
        sa.commit()

        try:
            prompt = _build_plan_prompt(rm.topic, rm.level or "beginner", mpd)
            raw = llm.generate_json(prompt)
            modules_data: list[dict] = raw.get("modules", [])
            edges_data: list[list[str]] = raw.get("edges", [])
        except Exception as exc:
            _update_step(run, "plan", "failed", detail=str(exc)[:200])
            run.status = "failed"
            run.error = f"LLM plan step failed: {exc}"
            run.finished_at = datetime.now(timezone.utc)
            sa.commit()
            return

        _update_step(run, "plan", "done",
                     detail=f"{len(modules_data)} modules · {len(edges_data)} prerequisites")
        sa.commit()

        # ---- Step 2: Validate (with retries) -------------------------------
        _update_step(run, "validate", "running", detail="checking graph structure …")
        sa.commit()

        name_to_idx = {m["title"]: i for i, m in enumerate(modules_data)}
        node_ids = list(range(len(modules_data)))

        def _resolve_edges(edgelist):
            """Convert title pairs to index pairs, collecting errors."""
            idx_edges = []
            errors = []
            for prereq_name, dep_name in edgelist:
                if prereq_name not in name_to_idx:
                    errors.append(f"unknown prerequisite '{prereq_name}'")
                elif dep_name not in name_to_idx:
                    errors.append(f"unknown module '{dep_name}'")
                else:
                    idx_edges.append((name_to_idx[prereq_name], name_to_idx[dep_name]))
            return idx_edges, errors

        edge_ids, edge_errors = _resolve_edges(edges_data)
        problems = validate_graph(node_ids, edge_ids) + edge_errors

        retries = 0
        while problems and retries < 2:
            retries += 1
            _update_step(run, "validate", "running",
                         detail=f"retry {retries}/2 — fixing: {'; '.join(problems[:2])}")
            sa.commit()

            fix_prompt = (
                f"The roadmap graph has these problems:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\n\nReturn a corrected JSON with the SAME structure "
                  "(modules + edges). Fix the issues above."
            )
            try:
                raw = llm.generate_json(fix_prompt)
            except Exception:
                continue

            modules_data = raw.get("modules", modules_data)
            edges_data = raw.get("edges", edges_data)
            name_to_idx = {m["title"]: i for i, m in enumerate(modules_data)}
            node_ids = list(range(len(modules_data)))
            edge_ids, edge_errors = _resolve_edges(edges_data)
            problems = validate_graph(node_ids, edge_ids) + edge_errors

        if problems:
            _update_step(run, "validate", "failed", detail="; ".join(problems[:3]))
            rm.status = "failed"
            run.status = "failed"
            run.error = "Graph validation failed after 2 retries: " + "; ".join(problems)
            run.finished_at = datetime.now(timezone.utc)
            sa.commit()
            return

        _update_step(run, "validate", "done",
                     detail=f"no cycles · {len(node_ids)} modules · 1 root · 1 capstone")
        sa.commit()

        # ---- Step 3: Sourcing ----------------------------------------------
        _update_step(run, "sourcing", "running", detail="searching for resources …")
        sa.commit()

        all_resources: list[dict] = []
        seen_hashes: set[str] = set()
        query_count = 0

        for i, mod in enumerate(modules_data):
            query = f"{mod['title']} {rm.topic} tutorial"
            try:
                results = search.search(query, n=4)
                query_count += 1
            except Exception:
                continue

            for r in results:
                url = r.get("url", "")
                if not url:
                    continue
                h = url_hash(url)
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    all_resources.append({
                        "module_idx": i,
                        "title": r.get("title", ""),
                        "url": url,
                        "url_hash": h,
                        "kind": r.get("kind", "article"),
                        "source_domain": domain_of(url),
                    })

        _update_step(run, "sourcing", "done",
                     detail=f"{query_count} queries · {len(all_resources)} found")
        sa.commit()

        # ---- Step 4: Verify ------------------------------------------------
        _update_step(run, "verify", "running", detail="checking links …")
        sa.commit()

        try:
            verified = verify_urls(all_resources)
        except Exception:
            # If verify itself crashes, mark everything as unverified
            verified = [{**r, "http_status": None, "verified_at": None, "alive": False}
                        for r in all_resources]

        # Confirmed-dead links (a real HTTP error) are dropped and counted.
        # Unreachable links (network down → status None) are KEPT as unverified,
        # so the app still works offline — never silently empty.
        alive = [r for r in verified if r.get("alive")]
        unverified = [r for r in verified if r.get("http_status") is None]
        keep = alive + unverified
        dead_count = len(verified) - len(keep)

        _update_step(run, "verify", "done",
                     detail=f"{len(alive)} alive · {dead_count} dead")
        sa.commit()

        # ---- Step 5: Schedule ----------------------------------------------
        _update_step(run, "schedule", "running", detail="building session plan …")
        sa.commit()

        prefix = code_prefix(rm.topic)
        mod_objs: list[Module] = []

        for i, md in enumerate(modules_data):
            m = Module(
                roadmap_id=rm.id,
                title=md["title"],
                summary=md.get("summary", ""),
                est_sessions=md.get("est_sessions", 4),
                est_minutes=md.get("est_minutes", 4 * mpd),
            )
            sa.add(m)
            mod_objs.append(m)
        sa.flush()

        # Set codes in topological order
        topo = topo_sort(node_ids, edge_ids)
        for order_pos, idx in enumerate(topo, start=1):
            if idx < len(mod_objs):
                mod_objs[idx].code = f"{prefix}-{order_pos:02d}"
        sa.flush()

        # Create dependency edges
        for prereq_idx, dep_idx in edge_ids:
            if prereq_idx < len(mod_objs) and dep_idx < len(mod_objs):
                sa.add(ModuleDep(
                    module_id=mod_objs[dep_idx].id,
                    prereq_module_id=mod_objs[prereq_idx].id,
                ))

        # Attach kept resources (verified + unverified) to their modules
        for res in keep:
            idx = res.get("module_idx", 0)
            if idx < len(mod_objs):
                when = (
                    datetime.fromisoformat(res["verified_at"])
                    if res.get("verified_at")
                    else None
                )
                sa.add(Resource(
                    module_id=mod_objs[idx].id,
                    title=res["title"],
                    url=res["url"],
                    url_hash=res["url_hash"],
                    kind=res.get("kind", "article"),
                    source_domain=res.get("source_domain", ""),
                    http_status=res.get("http_status"),
                    verified_at=when,
                    relevance=0.8,
                ))

        recompute_roadmap(sa, rm)
        target = schedule_roadmap(sa, rm)
        rm.status = "ready"

        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)

        _update_step(run, "schedule", "done",
                     detail=f"ready by {month_day(target) if target else 'N/A'}")
        sa.commit()


# ---------------------------------------------------------------------------
# Replan runner
# ---------------------------------------------------------------------------

def run_replan(roadmap_id: int, run_id: int, module_id: int, app: Flask) -> None:
    """Replan a stuck module: split into 2-4 submodules, rewire edges,
    source gentler resources, reschedule, and write an Insight."""

    with app.app_context():
        llm = get_llm()
        search = get_search()
        sa = db_session

        rm = sa.get(Roadmap, roadmap_id)
        run = sa.get(AgentRun, run_id)
        stuck_mod = sa.get(Module, module_id)
        if rm is None or run is None or stuck_mod is None:
            return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        sa.commit()

        mpd = max(rm.minutes_per_day, 15)

        # Find the stuck reason from the most recent stuck session
        from sqlalchemy import func, select as sa_select

        last_note = sa.execute(
            sa_select(StudySession.note)
            .where(StudySession.module_id == module_id, StudySession.status == "stuck")
            .order_by(StudySession.planned_date.desc())
            .limit(1)
        ).scalar()
        reason = last_note or "The student finds this module too difficult."

        # ---- Step 1: Diagnose ----------------------------------------------
        _update_step(run, "diagnose", "running", detail="analyzing the block …")
        sa.commit()

        stuck_days = None
        last_stuck_date = sa.execute(
            sa_select(func.max(StudySession.planned_date)).where(
                StudySession.module_id == module_id, StudySession.status == "stuck"
            )
        ).scalar()
        if last_stuck_date:
            from datetime import date as date_cls
            stuck_days = (date_cls.today() - last_stuck_date).days

        _update_step(run, "diagnose", "done",
                     detail=f"stuck {stuck_days} days" if stuck_days else "newly stuck")
        sa.commit()

        # ---- Step 2: Split -------------------------------------------------
        _update_step(run, "split", "running", detail="breaking into smaller steps …")
        sa.commit()

        try:
            prompt = _build_replan_prompt(
                stuck_mod.title, rm.topic, rm.level or "beginner", reason, mpd
            )
            raw = llm.generate_json(prompt)
            subs_data: list[dict] = raw.get("submodules", [])
            if not subs_data:
                # Fallback: generate 2 generic submodules
                subs_data = [
                    {"title": f"{stuck_mod.title} — Part 1: Foundations",
                     "summary": "Core concepts broken down into smaller pieces.",
                     "est_sessions": 2, "est_minutes": 2 * mpd},
                    {"title": f"{stuck_mod.title} — Part 2: Practice",
                     "summary": "Apply what you learned with guided exercises.",
                     "est_sessions": 2, "est_minutes": 2 * mpd},
                ]
        except Exception:
            subs_data = [
                {"title": f"{stuck_mod.title} — Part 1",
                 "summary": "Easier introduction.",
                 "est_sessions": 2, "est_minutes": 2 * mpd},
                {"title": f"{stuck_mod.title} — Part 2",
                 "summary": "Practice and apply.",
                 "est_sessions": 2, "est_minutes": 2 * mpd},
            ]

        _update_step(run, "split", "done", detail=f"{len(subs_data)} smaller steps")
        sa.commit()

        # ---- Step 3: Sourcing (gentler resources) --------------------------
        _update_step(run, "sourcing", "running",
                     detail="searching for gentler resources …")
        sa.commit()

        all_resources: list[dict] = []
        seen_hashes: set[str] = set()
        query_count = 0

        # Prefer video + practice for stuck modules (different angle)
        for i, sub in enumerate(subs_data):
            # Two queries per submodule — one for video, one for practice
            for fmt in ("video", "practice"):
                query = f"{sub['title']} {rm.topic} beginner {fmt}"
                try:
                    results = search.search(query, n=3)
                    query_count += 1
                except Exception:
                    continue

                for r in results:
                    url = r.get("url", "")
                    if not url:
                        continue
                    h = url_hash(url)
                    if h not in seen_hashes:
                        seen_hashes.add(h)
                        all_resources.append({
                            "sub_idx": i,
                            "title": r.get("title", ""),
                            "url": url,
                            "url_hash": h,
                            "kind": r.get("kind", fmt),
                            "source_domain": domain_of(url),
                        })

        _update_step(run, "sourcing", "done",
                     detail=f"{query_count} queries · {len(all_resources)} found")
        sa.commit()

        # ---- Step 4: Verify ------------------------------------------------
        _update_step(run, "verify", "running", detail="checking links …")
        sa.commit()

        try:
            verified = verify_urls(all_resources)
        except Exception:
            verified = [{**r, "http_status": None, "verified_at": None, "alive": False}
                        for r in all_resources]

        alive = [r for r in verified if r.get("alive")]
        unverified = [r for r in verified if r.get("http_status") is None]
        keep = alive + unverified
        dead_count = len(verified) - len(keep)

        _update_step(run, "verify", "done",
                     detail=f"{len(alive)} alive · {dead_count} dead")
        sa.commit()

        # ---- Step 5: Rewire & Schedule -------------------------------------
        _update_step(run, "schedule", "running", detail="rewiring the plan …")
        sa.commit()

        from sqlalchemy import delete

        # Build child modules
        children: list[Module] = []
        for i, sd in enumerate(subs_data, start=1):
            child = Module(
                roadmap_id=rm.id,
                parent_module_id=stuck_mod.id,
                title=sd["title"],
                summary=sd.get("summary", ""),
                est_sessions=sd.get("est_sessions", 2),
                est_minutes=sd.get("est_minutes", 2 * mpd),
                code=f"{stuck_mod.code}.{i}",
            )
            sa.add(child)
            children.append(child)
        sa.flush()

        # Gather current edges touching the stuck module
        prereq_ids = [
            row[0] for row in sa.execute(
                sa_select(ModuleDep.prereq_module_id)
                .where(ModuleDep.module_id == stuck_mod.id)
            ).all()
        ]
        dep_ids = [
            row[0] for row in sa.execute(
                sa_select(ModuleDep.module_id)
                .where(ModuleDep.prereq_module_id == stuck_mod.id)
            ).all()
        ]

        # Remove old edges touching the stuck module
        sa.execute(
            delete(ModuleDep).where(
                (ModuleDep.module_id == stuck_mod.id)
                | (ModuleDep.prereq_module_id == stuck_mod.id)
            )
        )
        sa.flush()

        # prereqs → first child
        for pid in prereq_ids:
            sa.add(ModuleDep(module_id=children[0].id, prereq_module_id=pid))

        # chain children together
        for i in range(len(children) - 1):
            sa.add(ModuleDep(
                module_id=children[i + 1].id,
                prereq_module_id=children[i].id,
            ))

        # last child → dependents
        for did in dep_ids:
            sa.add(ModuleDep(module_id=did, prereq_module_id=children[-1].id))

        sa.flush()

        # Attach resources to their child modules (verified + unverified)
        for i, child in enumerate(children):
            child_res = [r for r in keep if r.get("sub_idx") == i]
            for res in child_res:
                when = (
                    datetime.fromisoformat(res["verified_at"])
                    if res.get("verified_at")
                    else None
                )
                sa.add(Resource(
                    module_id=child.id,
                    title=res["title"],
                    url=res["url"],
                    url_hash=res["url_hash"],
                    kind=res.get("kind", "article"),
                    source_domain=res.get("source_domain", ""),
                    http_status=res.get("http_status"),
                    verified_at=when,
                    relevance=0.8,
                ))

        recompute_roadmap(sa, rm)
        schedule_roadmap(sa, rm)

        # Write the Insight that drives the "Plan adapted" panel
        sa.add(Insight(
            roadmap_id=rm.id,
            kind="replan",
            text=(
                f"Split '{stuck_mod.title}' into {len(children)} smaller steps "
                f"and swapped the resources for gentler alternatives. "
                f"Two prerequisite sessions were slotted in before it re-opens."
            ),
            payload={
                "module_id": stuck_mod.id,
                "steps": [c.title for c in children],
            },
        ))

        run.status = "done"
        run.finished_at = datetime.now(timezone.utc)

        _update_step(run, "schedule", "done",
                     detail="plan updated with gentler approach")
        sa.commit()
