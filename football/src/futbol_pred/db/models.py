"""Modelos de base de datos (SQLAlchemy). Portable SQLite <-> Postgres."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    api_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    league: Mapped[str | None] = mapped_column(String(32), index=True)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("api_id", name="uq_match_api"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    api_id: Mapped[int | None] = mapped_column(Integer, index=True)
    league: Mapped[str] = mapped_column(String(32), index=True)
    season: Mapped[int] = mapped_column(Integer, index=True)
    kickoff: Mapped[datetime] = mapped_column(DateTime, index=True)
    home_team: Mapped[str] = mapped_column(String(128), index=True)
    away_team: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(16), default="scheduled")
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    # Métricas avanzadas (xG) para el modelo híbrido.
    home_xg: Mapped[float | None] = mapped_column(Float)
    away_xg: Mapped[float | None] = mapped_column(Float)

    odds: Mapped[list["Odds"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )
    predictions: Mapped[list["Prediction"]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )


class Odds(Base):
    __tablename__ = "odds"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    bookmaker: Mapped[str] = mapped_column(String(64), index=True)
    market: Mapped[str] = mapped_column(String(64), index=True)  # 1x2, ou_2.5...
    selection: Mapped[str] = mapped_column(String(32))           # 1/X/2/over...
    odds: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    match: Mapped[Match] = relationship(back_populates="odds")


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"), index=True)
    market: Mapped[str] = mapped_column(String(64), index=True)
    selection: Mapped[str] = mapped_column(String(32))
    model_prob: Mapped[float] = mapped_column(Float)
    fair_odds: Mapped[float] = mapped_column(Float)
    best_odds: Mapped[float | None] = mapped_column(Float)
    edge: Mapped[float | None] = mapped_column(Float)
    stake: Mapped[float | None] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(32), default="dc-0.1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    match: Mapped[Match] = relationship(back_populates="predictions")
