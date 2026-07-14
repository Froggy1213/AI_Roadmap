import threading
from datetime import date, datetime, timezone

from flask import abort, current_app, jsonify, request
from sqlalchemy import select

from ..db import db_session
from ..models import AgentRun, Roadmap
from . import api_bp
from .serializers import roadmap_card, roadmap_detail, stats_payload


def get_roadmap_or_404(rid: int) -> Roadmap:
    rm = db_session.get(Roadmap, rid)
    if rm is None:
        abort(404, description=f"roadmap {rid} not found")
    return rm


@api_bp.get("/roadmaps")
def list_roadmaps():
    today = date.today()
    roadmaps = db_session.execute(select(Roadmap).order_by(Roadmap.id)).scalars().all()
    cards = [roadmap_card(db_session, rm, today) for rm in roadmaps]
    return jsonify({
        "roadmaps": cards,
        "active_count": sum(1 for c in cards if c["status"] in ("ready", "building")),
    })


@api_bp.get("/roadmaps/<int:rid>")
def roadmap_by_id(rid: int):
    return jsonify(roadmap_detail(db_session, get_roadmap_or_404(rid), date.today()))


@api_bp.get("/roadmaps/<int:rid>/stats")
def roadmap_stats(rid: int):
    return jsonify(stats_payload(db_session, get_roadmap_or_404(rid), date.today()))


@api_bp.delete("/roadmaps/<int:rid>")
def delete_roadmap(rid: int):
    """Delete a roadmap and everything under it (modules, deps, resources,
    sessions, runs, insights). SQLAlchemy's unit of work orders the
    self-referential module deletes (split children before their parent)
    from the mapped relationship, and ModuleDep rows go via ON DELETE CASCADE.
    Any in-flight agent thread is harmless: its final commit is a no-op once
    the rows are gone."""
    rm = get_roadmap_or_404(rid)
    db_session.delete(rm)
    db_session.commit()
    return jsonify({"ok": True, "deleted": rid})


@api_bp.post("/roadmaps")
def create_roadmap():
    """Accept a topic and spawn the 5-step agent in a background thread."""
    data = request.get_json(force=True) or {}
    topic = data.get("topic", "").strip()
    if not topic:
        return jsonify(error="topic is required"), 400

    roadmap = Roadmap(
        topic=topic,
        goal=data.get("goal"),
        level=data.get("level", "beginner"),
        color=data.get("color", "#9184d9"),
        minutes_per_day=int(data.get("minutes_per_day", 30)),
        weekdays=data.get("weekdays", "1,2,3,4,5"),
        status="building",
    )
    db_session.add(roadmap)
    db_session.flush()

    run = AgentRun(
        roadmap_id=roadmap.id,
        kind="generate",
        status="queued",
        steps=[
            {"key": "plan", "label": "Plan the roadmap",
             "status": "pending", "detail": ""},
            {"key": "validate", "label": "Validate the graph",
             "status": "pending", "detail": ""},
            {"key": "sourcing", "label": "Source resources",
             "status": "pending", "detail": ""},
            {"key": "verify", "label": "Verify links",
             "status": "pending", "detail": ""},
            {"key": "schedule", "label": "Schedule sessions",
             "status": "pending", "detail": ""},
        ],
    )
    db_session.add(run)
    db_session.commit()

    # Import here to avoid circular imports at module level
    from agent.runner import run_generation

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=run_generation,
        args=(roadmap.id, run.id, app),
        daemon=True,
    )
    thread.start()

    return jsonify({"roadmap_id": roadmap.id, "run_id": run.id}), 202
