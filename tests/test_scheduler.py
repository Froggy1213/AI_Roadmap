"""Tests for session scheduler: ordering, weekday filtering, target date."""

from datetime import date, timedelta

import pytest

from app.models import Module, ModuleDep, Roadmap, StudySession
from app.scheduler import schedule_roadmap


def _dummy_module(sa, roadmap, id_, **kw):
    m = Module(roadmap_id=roadmap.id, **kw)
    sa.add(m)
    sa.flush()
    return m


def _dummy_dep(sa, prereq, dep):
    sa.add(ModuleDep(module_id=dep.id, prereq_module_id=prereq.id))
    sa.flush()


def _dummy_done(sa, module, day, minutes=30):
    sa.add(StudySession(
        module_id=module.id, planned_date=day, planned_minutes=minutes,
        actual_minutes=minutes, status="done",
    ))
    sa.flush()


class TestScheduleRoadmap:
    def test_linear_schedule(self, db_session):
        rm = Roadmap(topic="Test", minutes_per_day=30, weekdays="1,2,3,4,5", status="ready")
        db_session.add(rm)
        db_session.flush()

        a = _dummy_module(db_session, rm, 1, title="A", est_minutes=60, est_sessions=2)
        b = _dummy_module(db_session, rm, 2, title="B", est_minutes=30, est_sessions=1)
        _dummy_dep(db_session, a, b)
        db_session.commit()

        today = date.today()
        target = schedule_roadmap(db_session, rm, start=today)
        assert target is not None
        assert target >= today

        sessions = (
            db_session.query(StudySession)
            .filter(StudySession.module_id.in_([a.id, b.id]))
            .order_by(StudySession.planned_date)
            .all()
        )
        # A: 60 min → 2 sessions; B: 30 min → 1 session
        assert len(sessions) == 3
        # All sessions should be on weekdays
        for s in sessions:
            assert s.planned_date.isoweekday() <= 5
        # A sessions should come before B (topological order)
        a_sessions = [s for s in sessions if s.module_id == a.id]
        b_sessions = [s for s in sessions if s.module_id == b.id]
        assert all(s.planned_date < bs.planned_date for s in a_sessions for bs in b_sessions)

    def test_already_completed_module_skipped(self, db_session):
        rm = Roadmap(topic="Test", minutes_per_day=30, weekdays="1,2,3,4,5", status="ready")
        db_session.add(rm)
        db_session.flush()

        a = _dummy_module(db_session, rm, 1, title="A", est_minutes=0, est_sessions=0)
        a.state = "completed"
        b = _dummy_module(db_session, rm, 2, title="B", est_minutes=30, est_sessions=1)
        _dummy_dep(db_session, a, b)
        db_session.commit()

        today = date.today()
        schedule_roadmap(db_session, rm, start=today)

        sessions = (
            db_session.query(StudySession)
            .filter(StudySession.module_id.in_([a.id, b.id]))
            .all()
        )
        # Module A is completed — no sessions
        a_sessions = [s for s in sessions if s.module_id == a.id]
        assert len(a_sessions) == 0
        # Module B still gets sessions
        b_sessions = [s for s in sessions if s.module_id == b.id]
        assert len(b_sessions) == 1

    def test_minutes_per_day_chunking(self, db_session):
        rm = Roadmap(topic="Test", minutes_per_day=45, weekdays="1,2,3,4,5", status="ready")
        db_session.add(rm)
        db_session.flush()

        a = _dummy_module(db_session, rm, 1, title="A", est_minutes=120, est_sessions=3, state="available")
        db_session.commit()

        today = date.today()
        schedule_roadmap(db_session, rm, start=today)

        sessions = (
            db_session.query(StudySession)
            .filter(StudySession.module_id == a.id)
            .order_by(StudySession.planned_date)
            .all()
        )
        # 120 min at 45 min/day = 3 sessions: 45 + 45 + 30
        assert len(sessions) == 3
        assert sum(s.planned_minutes for s in sessions) == 120

    def test_weekday_filter(self, db_session):
        rm = Roadmap(topic="Test", minutes_per_day=30, weekdays="2,4", status="ready")
        db_session.add(rm)
        db_session.flush()

        a = _dummy_module(db_session, rm, 1, title="A", est_minutes=60, est_sessions=2)
        db_session.commit()

        today = date.today()
        schedule_roadmap(db_session, rm, start=today)

        sessions = (
            db_session.query(StudySession)
            .filter(StudySession.module_id == a.id)
            .order_by(StudySession.planned_date)
            .all()
        )
        for s in sessions:
            assert s.planned_date.isoweekday() in (2, 4)  # Tue or Thu only

    def test_remaining_minutes_respects_done(self, db_session):
        rm = Roadmap(topic="Test", minutes_per_day=30, weekdays="1,2,3,4,5", status="ready")
        db_session.add(rm)
        db_session.flush()

        a = _dummy_module(db_session, rm, 1, title="A", est_minutes=90, est_sessions=3)
        db_session.commit()

        # Complete one session (30 min done)
        today = date.today()
        _dummy_done(db_session, a, today - timedelta(days=2), minutes=30)
        db_session.commit()

        schedule_roadmap(db_session, rm, start=today)

        sessions = (
            db_session.query(StudySession)
            .filter(StudySession.module_id == a.id)
            .order_by(StudySession.planned_date)
            .all()
        )
        # 90 total - 30 done = 60 remaining → 2 sessions
        planned = [s for s in sessions if s.status == "planned"]
        assert len(planned) == 2
        assert sum(s.planned_minutes for s in planned) == 60
