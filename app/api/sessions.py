"""Session lifecycle endpoints: complete a session or skip it."""

from datetime import datetime, timezone

from flask import jsonify, request

from ..db import db_session
from ..graph import recompute_roadmap
from ..models import StudySession
from . import api_bp


def _get_session_or_404(sid: int) -> StudySession:
    session = db_session.get(StudySession, sid)
    if session is None:
        from flask import abort
        abort(404, description=f"session {sid} not found")
    return session


@api_bp.post("/sessions/<int:sid>/complete")
def complete_session(sid: int):
    """Mark a study session as done and recompute module states."""
    session = _get_session_or_404(sid)
    data = request.get_json(force=True) or {}

    session.status = "done"
    session.actual_minutes = data.get(
        "actual_minutes", session.planned_minutes
    )
    session.note = data.get("note", session.note)
    session.completed_at = datetime.now(timezone.utc)

    recompute_roadmap(db_session, session.module.roadmap)
    db_session.commit()

    return jsonify({"ok": True})


@api_bp.post("/sessions/<int:sid>/skip")
def skip_session(sid: int):
    """Mark a study session as skipped and recompute module states."""
    session = _get_session_or_404(sid)

    session.status = "skipped"
    recompute_roadmap(db_session, session.module.roadmap)
    db_session.commit()

    return jsonify({"ok": True})
