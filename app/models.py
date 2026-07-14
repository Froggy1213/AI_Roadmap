from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Roadmap.status
ROADMAP_STATUSES = ("building", "ready", "failed")
# Module.state — recomputed by graph.recompute_roadmap, never trusted from input
MODULE_STATES = ("locked", "available", "inprogress", "completed", "stuck")
# StudySession.status
SESSION_STATUSES = ("planned", "done", "skipped", "stuck")
# Resource.kind
RESOURCE_KINDS = ("video", "article", "course", "book", "audio", "practice")


class Roadmap(Base):
    __tablename__ = "roadmaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(200))
    goal: Mapped[Optional[str]] = mapped_column(String(300))
    level: Mapped[Optional[str]] = mapped_column(String(40))
    color: Mapped[str] = mapped_column(String(20), default="#9184d9")
    status: Mapped[str] = mapped_column(String(20), default="building")
    minutes_per_day: Mapped[int] = mapped_column(Integer, default=30)
    # ISO weekday numbers, comma-separated: "1,2,3,4,5" = Mon..Fri
    weekdays: Mapped[str] = mapped_column(String(20), default="1,2,3,4,5")
    target_date: Mapped[Optional[date]] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    modules: Mapped[list[Module]] = relationship(
        back_populates="roadmap", cascade="all, delete-orphan", order_by="Module.id"
    )
    runs: Mapped[list[AgentRun]] = relationship(
        back_populates="roadmap", cascade="all, delete-orphan", order_by="AgentRun.id"
    )
    insights: Mapped[list[Insight]] = relationship(
        back_populates="roadmap", cascade="all, delete-orphan", order_by="Insight.id"
    )


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("roadmaps.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20), default="")
    title: Mapped[str] = mapped_column(String(200))
    title_native: Mapped[Optional[str]] = mapped_column(String(200))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    est_sessions: Mapped[int] = mapped_column(Integer, default=0)
    est_minutes: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="locked")
    parent_module_id: Mapped[Optional[int]] = mapped_column(ForeignKey("modules.id"))
    layout_x: Mapped[int] = mapped_column(Integer, default=0)
    layout_y: Mapped[int] = mapped_column(Integer, default=0)

    roadmap: Mapped[Roadmap] = relationship(back_populates="modules")
    parent: Mapped[Optional[Module]] = relationship(
        back_populates="children", remote_side="Module.id"
    )
    children: Mapped[list[Module]] = relationship(
        back_populates="parent", order_by="Module.id"
    )
    resources: Mapped[list[Resource]] = relationship(
        back_populates="module", cascade="all, delete-orphan", order_by="Resource.id"
    )
    sessions: Mapped[list[StudySession]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="StudySession.planned_date",
    )

    __table_args__ = (Index("ix_modules_roadmap", "roadmap_id"),)


class ModuleDep(Base):
    """`module_id` cannot start before `prereq_module_id` is complete."""

    __tablename__ = "module_deps"

    module_id: Mapped[int] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )
    prereq_module_id: Mapped[int] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    url_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20), default="article")
    source_domain: Mapped[Optional[str]] = mapped_column(String(200))
    duration_min: Mapped[Optional[int]] = mapped_column(Integer)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    relevance: Mapped[float] = mapped_column(Float, default=0.0)

    module: Mapped[Module] = relationship(back_populates="resources")

    __table_args__ = (
        Index("ix_resources_module", "module_id"),
        Index("ix_resources_url_hash", "url_hash"),
    )


class StudySession(Base):
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    planned_date: Mapped[date] = mapped_column(Date)
    planned_minutes: Mapped[int] = mapped_column(Integer, default=30)
    actual_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    note: Mapped[Optional[str]] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_sessions_module", "module_id"),
        Index("ix_sessions_date", "planned_date"),
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("roadmaps.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # generate | replan
    status: Mapped[str] = mapped_column(String(20), default="queued")
    # list of {key, label, status: pending|running|done|failed, detail}
    steps: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    roadmap: Mapped[Roadmap] = relationship(back_populates="runs")


class Insight(Base):
    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    roadmap_id: Mapped[int] = mapped_column(ForeignKey("roadmaps.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30))  # replan | format | pace | stuck
    text: Mapped[str] = mapped_column(Text)
    action_kind: Mapped[Optional[str]] = mapped_column(String(30))
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    roadmap: Mapped[Roadmap] = relationship(back_populates="insights")
