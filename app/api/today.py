from datetime import date

from flask import jsonify

from ..db import db_session
from . import api_bp
from .serializers import today_payload


@api_bp.get("/today")
def today_view():
    return jsonify(today_payload(db_session, date.today()))
