from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rag_core.models import Feedback, MessageTrace


class Base(DeclarativeBase):
    pass


class MessageRecord(Base):
    __tablename__ = "messages"
    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    query: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    retrieved_documents: Mapped[list[dict]] = mapped_column(JSON)
    timings_ms: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FeedbackRecord(Base):
    __tablename__ = "feedback"
    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PostgresTraceRepository:
    def __init__(self, dsn: str) -> None:
        self.engine: AsyncEngine = create_async_engine(dsn, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def save_message(self, trace: MessageTrace) -> None:
        async with self.sessions() as session:
            await session.merge(MessageRecord(**asdict(trace)))
            await session.commit()

    async def save_feedback(self, feedback: Feedback) -> None:
        async with self.sessions() as session:
            await session.merge(FeedbackRecord(**asdict(feedback)))
            await session.commit()

    async def get_message(self, message_id: str) -> MessageTrace | None:
        async with self.sessions() as session:
            record = await session.scalar(
                select(MessageRecord).where(MessageRecord.message_id == message_id)
            )
        if record is None:
            return None
        return MessageTrace(
            record.message_id,
            record.session_id,
            record.query,
            record.rewritten_query,
            record.answer,
            record.retrieved_documents,
            record.timings_ms,
            record.created_at,
        )
