import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

from . import db
from .db import Base, db_session, init_engine


def create_app() -> Flask:
    load_dotenv()
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="../static",
        static_url_path="/static",
        template_folder="../templates",
    )
    os.makedirs(app.instance_path, exist_ok=True)

    default_db = "sqlite:///" + os.path.join(app.instance_path, "roadmap.sqlite3")
    app.config.update(
        DATABASE_URL=os.environ.get("DATABASE_URL", default_db),
        LLM_PROVIDER=os.environ.get("LLM_PROVIDER", "mock"),
        SEARCH_PROVIDER=os.environ.get("SEARCH_PROVIDER", "mock"),
        AUTO_SEED=os.environ.get("AUTO_SEED", "1").lower() not in ("0", "false", "no"),
    )

    init_engine(app.config["DATABASE_URL"])
    from . import models  # noqa: F401  (register mappings)
    Base.metadata.create_all(bind=db.engine)

    # Vue templates use {{ }} — switch Jinja delimiters to avoid conflicts
    app.jinja_env.variable_start_string = "{$ "
    app.jinja_env.variable_end_string = " $}"

    from .api import api_bp
    app.register_blueprint(api_bp)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.errorhandler(404)
    def not_found(err):
        return jsonify(error=getattr(err, "description", "not found")), 404

    @app.errorhandler(500)
    def server_error(err):
        return jsonify(error="internal server error"), 500

    @app.teardown_appcontext
    def cleanup(_exc=None):
        db_session.remove()

    @app.cli.command("seed")
    def seed_command():
        """Drop everything and rebuild the demo database."""
        from .seed import seed
        seed(reset=True)

    if app.config["AUTO_SEED"]:
        _seed_if_empty()

    return app


def _seed_if_empty() -> None:
    from sqlalchemy import func, select

    from .models import Roadmap
    from .seed import seed

    try:
        empty = not db_session.execute(select(func.count(Roadmap.id))).scalar()
        if empty:
            seed(reset=False)
    finally:
        db_session.remove()
