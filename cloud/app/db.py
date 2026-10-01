"""Database models. SQLite for development, Postgres in production (same code, DATABASE_URL)."""

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_db(dt: datetime) -> datetime:
    """Store as naive UTC (SQLite has no time zones)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def from_db(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None else None


class Base(DeclarativeBase):
    pass


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(10), unique=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    visible_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # new tenant -> hide older photos
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Reading(Base):
    __tablename__ = "readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    meter_type: Mapped[str] = mapped_column(String(8))
    value: Mapped[str] = mapped_column(String(8))
    rollover: Mapped[bool] = mapped_column(Boolean, default=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    image_file: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(10), default="robot")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    room: Mapped[Room] = relationship()


class ReadingImage(Base):
    """Meter photo bytes. Kept in the database because free hosts wipe their disk on every restart."""
    __tablename__ = "reading_images"
    reading_id: Mapped[int] = mapped_column(ForeignKey("readings.id"), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class ReadingEdit(Base):
    """Audit trail: every change an admin makes to a reading."""
    __tablename__ = "reading_edits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_id: Mapped[int] = mapped_column(ForeignKey("readings.id"), index=True)
    action: Mapped[str] = mapped_column(String(10))  # edit | delete
    old_value: Mapped[str | None] = mapped_column(String(8), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(8), nullable=True)
    old_room: Mapped[str | None] = mapped_column(String(10), nullable=True)
    new_room: Mapped[str | None] = mapped_column(String(10), nullable=True)
    old_rollover: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    new_rollover: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Rate(Base):
    __tablename__ = "rates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meter_type: Mapped[str] = mapped_column(String(8))
    price: Mapped[str] = mapped_column(String(16))  # Decimal as text, exact
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Dispute(Base):
    __tablename__ = "disputes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open")
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    room: Mapped[Room] = relationship()


def make_session_factory(database_url: str):
    kwargs = {"connect_args": {"check_same_thread": False}} if database_url.startswith("sqlite") else {"pool_pre_ping": True}
    engine = create_engine(database_url, **kwargs)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
