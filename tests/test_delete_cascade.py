"""Deleting a roadmap must remove everything under it and nothing else.

The subtle case is a split module: a child Module points at its parent via
the self-referential parent_module_id FK. SQLAlchemy's unit of work orders
those deletes (children first), so a single delete of the roadmap cascades
cleanly — this mirrors DELETE /api/roadmaps/<id>.
"""

from datetime import date

from app.models import (
    AgentRun,
    Insight,
    Module,
    ModuleDep,
    Resource,
    Roadmap,
    StudySession,
)


def _delete_roadmap(sa, rm):
    """Same operation the DELETE /api/roadmaps/<id> endpoint performs."""
    sa.delete(rm)
    sa.flush()


def _seed_two_roadmaps(sa):
    rm = Roadmap(topic="Learn Arabic", minutes_per_day=40, weekdays="1,2,3,4,5")
    other = Roadmap(topic="Go for Backend", minutes_per_day=30, weekdays="1,2,3,4,5")
    sa.add_all([rm, other])
    sa.flush()

    a = Module(roadmap_id=rm.id, code="AR-01", title="Root", est_sessions=2, est_minutes=80)
    b = Module(roadmap_id=rm.id, code="AR-02", title="Stuck one", est_sessions=2, est_minutes=80)
    sa.add_all([a, b])
    sa.flush()
    # b was split into a child sub-module (self-referential parent FK)
    child = Module(
        roadmap_id=rm.id, parent_module_id=b.id, code="AR-02.1",
        title="Gentler step", est_sessions=1, est_minutes=40,
    )
    sa.add(child)
    sa.flush()

    sa.add_all([
        ModuleDep(module_id=b.id, prereq_module_id=a.id),
        ModuleDep(module_id=child.id, prereq_module_id=a.id),
        Resource(module_id=a.id, title="R", url="https://x.dev/a", url_hash="h1"),
        Resource(module_id=child.id, title="R2", url="https://x.dev/c", url_hash="h2"),
        StudySession(module_id=a.id, planned_date=date(2026, 7, 14),
                     planned_minutes=40, status="done"),
        AgentRun(roadmap_id=rm.id, kind="generate", status="done", steps=[]),
        Insight(roadmap_id=rm.id, kind="replan", text="split", payload={"module_id": b.id}),
    ])

    # the untouched neighbour
    om = Module(roadmap_id=other.id, code="GO-01", title="Keep me", est_sessions=1, est_minutes=30)
    sa.add(om)
    sa.flush()
    return rm, other


def test_delete_removes_all_rows_including_split_children(db_session):
    sa = db_session
    rm, other = _seed_two_roadmaps(sa)
    rm_id, other_id = rm.id, other.id
    module_ids = [m.id for m in rm.modules]

    _delete_roadmap(sa, rm)

    assert sa.query(Roadmap).filter_by(id=rm_id).count() == 0
    assert sa.query(Module).filter_by(roadmap_id=rm_id).count() == 0
    assert sa.query(Resource).filter(Resource.module_id.in_(module_ids)).count() == 0
    assert sa.query(StudySession).filter(StudySession.module_id.in_(module_ids)).count() == 0
    assert sa.query(ModuleDep).filter(ModuleDep.module_id.in_(module_ids)).count() == 0
    assert sa.query(AgentRun).filter_by(roadmap_id=rm_id).count() == 0
    assert sa.query(Insight).filter_by(roadmap_id=rm_id).count() == 0


def test_delete_leaves_other_roadmaps_intact(db_session):
    sa = db_session
    rm, other = _seed_two_roadmaps(sa)
    other_id = other.id

    _delete_roadmap(sa, rm)

    assert sa.query(Roadmap).filter_by(id=other_id).count() == 1
    assert sa.query(Module).filter_by(roadmap_id=other_id).count() == 1
