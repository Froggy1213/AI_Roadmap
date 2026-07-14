from flask import abort, jsonify

from ..db import db_session
from ..models import AgentRun
from . import api_bp
from .serializers import run_payload


@api_bp.get("/runs/<int:run_id>")
def run_by_id(run_id: int):
    run = db_session.get(AgentRun, run_id)
    if run is None:
        abort(404, description=f"run {run_id} not found")
    return jsonify(run_payload(run))
