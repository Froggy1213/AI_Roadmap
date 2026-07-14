"""Insight action endpoints: apply a suggested action from an insight."""

import threading

from flask import abort, current_app, jsonify

from ..db import db_session
from ..models import AgentRun, Insight, Module
from . import api_bp


@api_bp.post("/insights/<int:iid>/apply")
def apply_insight(iid: int):
    """Apply an insight action.  `split_module` spawns the replanner."""
    insight = db_session.get(Insight, iid)
    if insight is None:
        abort(404, description=f"insight {iid} not found")

    action = insight.action_kind
    payload = insight.payload or {}

    if action == "split_module":
        module_id = payload.get("module_id")
        if not module_id:
            return jsonify(error="insight payload missing module_id"), 400

        module = db_session.get(Module, module_id)
        if module is None:
            return jsonify(error=f"module {module_id} not found"), 404

        # Mark the module stuck if it isn't already
        if module.state != "stuck":
            module.state = "stuck"

        run = AgentRun(
            roadmap_id=insight.roadmap_id,
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
            args=(insight.roadmap_id, run.id, module_id, app),
            daemon=True,
        )
        thread.start()

        return jsonify({"run_id": run.id}), 202

    elif action in ("prefer_format", "shift_slot"):
        # Future: update roadmap preferences based on insight
        return jsonify({
            "ok": True,
            "note": f"action '{action}' acknowledged (preferences not yet persisted)",
        })

    return jsonify(error=f"unknown action kind: '{action}'"), 400
