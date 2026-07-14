import threading
from datetime import date, datetime, timezone

from flask import abort, current_app, jsonify, request

from ..db import db_session
from ..models import AgentRun, Module, StudySession
from . import api_bp
from .serializers import module_detail


@api_bp.get("/modules/<int:mid>")
def module_by_id(mid: int):
    module = db_session.get(Module, mid)
    if module is None:
        abort(404, description=f"module {mid} not found")
    return jsonify(module_detail(db_session, module, date.today()))


@api_bp.post("/modules/<int:mid>/stuck")
def mark_stuck(mid: int):
    """Mark a module as stuck and trigger the replanner in the background."""
    module = db_session.get(Module, mid)
    if module is None:
        abort(404, description=f"module {mid} not found")

    data = request.get_json(force=True) or {}
    reason = data.get("reason", "")
    note = data.get("note", reason)

    module.state = "stuck"

    # Record a stuck session — this is what _stuck_days() in serializers counts
    stuck_session = StudySession(
        module_id=module.id,
        planned_date=date.today(),
        planned_minutes=module.roadmap.minutes_per_day,
        actual_minutes=data.get("actual_minutes"),
        status="stuck",
        note=note,
    )
    db_session.add(stuck_session)

    run = AgentRun(
        roadmap_id=module.roadmap_id,
        kind="replan",
        status="queued",
        steps=[
            {"key": "diagnose", "label": "Diagnose the block",
             "status": "pending", "detail": ""},
            {"key": "split", "label": "Split the module",
             "status": "pending", "detail": ""},
            {"key": "sourcing", "label": "Source gentler resources",
             "status": "pending", "detail": ""},
            {"key": "verify", "label": "Verify links",
             "status": "pending", "detail": ""},
            {"key": "schedule", "label": "Reschedule the plan",
             "status": "pending", "detail": ""},
        ],
    )
    db_session.add(run)
    db_session.commit()

    from agent.runner import run_replan

    app = current_app._get_current_object()
    thread = threading.Thread(
        target=run_replan,
        args=(module.roadmap_id, run.id, module.id, app),
        daemon=True,
    )
    thread.start()

    return jsonify({"run_id": run.id}), 202
