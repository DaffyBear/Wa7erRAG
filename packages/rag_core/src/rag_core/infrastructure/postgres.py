from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, delete, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rag_core.models import ChatSession, Feedback, MessageTrace


class Base(DeclarativeBase):
    pass


class MessageRecord(Base):
    __tablename__ = "messages"
    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="system")
    query: Mapped[str] = mapped_column(Text)
    rewritten_query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    retrieved_documents: Mapped[list[dict]] = mapped_column(JSON)
    timings_ms: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatSessionRecord(Base):
    __tablename__ = "chat_sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True, default="system")
    title: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class FeedbackRecord(Base):
    __tablename__ = "feedback"
    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[int] = mapped_column(Integer)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    user_id: Mapped[str] = mapped_column(String(64), index=True, default="system")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PostgresTraceRepository:
    def __init__(self, dsn: str) -> None:
        self.engine: AsyncEngine = create_async_engine(dsn, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_schema(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await self._backfill_sessions()

    async def save_message(self, trace: MessageTrace) -> None:
        async with self.sessions() as session:
            await session.merge(MessageRecord(**asdict(trace)))
            existing = await session.get(
                ChatSessionRecord,
                (trace.session_id, trace.tenant_id, trace.user_id),
            )
            if existing is None:
                session.add(
                    ChatSessionRecord(
                        session_id=trace.session_id,
                        tenant_id=trace.tenant_id,
                        user_id=trace.user_id,
                        title=_session_title(trace.query),
                        created_at=trace.created_at,
                        updated_at=trace.created_at,
                    )
                )
            else:
                existing.updated_at = trace.created_at
            await session.commit()

    async def save_feedback(self, feedback: Feedback) -> None:
        async with self.sessions() as session:
            await session.merge(FeedbackRecord(**asdict(feedback)))
            await session.commit()

    async def get_message(self, message_id: str, tenant_id: str = "default") -> MessageTrace | None:
        async with self.sessions() as session:
            record = await session.scalar(
                select(MessageRecord).where(
                    MessageRecord.message_id == message_id,
                    MessageRecord.tenant_id == tenant_id,
                )
            )
        return _trace_from_record(record) if record is not None else None

    async def list_sessions(
        self, tenant_id: str, user_id: str, limit: int = 100
    ) -> list[ChatSession]:
        async with self.sessions() as session:
            counts = (
                select(
                    MessageRecord.session_id,
                    MessageRecord.tenant_id,
                    MessageRecord.user_id,
                    func.count(MessageRecord.message_id).label("message_count"),
                )
                .where(MessageRecord.tenant_id == tenant_id, MessageRecord.user_id == user_id)
                .group_by(
                    MessageRecord.session_id,
                    MessageRecord.tenant_id,
                    MessageRecord.user_id,
                )
                .subquery()
            )
            rows = (
                await session.execute(
                    select(ChatSessionRecord, counts.c.message_count)
                    .join(
                        counts,
                        (counts.c.session_id == ChatSessionRecord.session_id)
                        & (counts.c.tenant_id == ChatSessionRecord.tenant_id)
                        & (counts.c.user_id == ChatSessionRecord.user_id),
                    )
                    .where(
                        ChatSessionRecord.tenant_id == tenant_id,
                        ChatSessionRecord.user_id == user_id,
                    )
                    .order_by(ChatSessionRecord.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        return [
            ChatSession(
                session_id=record.session_id,
                title=record.title,
                message_count=message_count,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record, message_count in rows
        ]

    async def get_session_messages(
        self, session_id: str, tenant_id: str, user_id: str
    ) -> list[MessageTrace]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(MessageRecord)
                    .where(
                        MessageRecord.session_id == session_id,
                        MessageRecord.tenant_id == tenant_id,
                        MessageRecord.user_id == user_id,
                    )
                    .order_by(MessageRecord.created_at.asc())
                )
            ).all()
        return [_trace_from_record(record) for record in records]

    async def rename_session(
        self, session_id: str, title: str, tenant_id: str, user_id: str
    ) -> ChatSession | None:
        async with self.sessions() as session:
            record = await session.get(ChatSessionRecord, (session_id, tenant_id, user_id))
            if record is None:
                return None
            record.title = title
            await session.commit()
            await session.refresh(record)
            message_count = await session.scalar(
                select(func.count(MessageRecord.message_id)).where(
                    MessageRecord.session_id == session_id,
                    MessageRecord.tenant_id == tenant_id,
                    MessageRecord.user_id == user_id,
                )
            )
            return ChatSession(
                session_id=record.session_id,
                title=record.title,
                message_count=message_count or 0,
                tenant_id=record.tenant_id,
                user_id=record.user_id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

    async def delete_session(self, session_id: str, tenant_id: str, user_id: str) -> bool:
        async with self.sessions() as session:
            record = await session.get(ChatSessionRecord, (session_id, tenant_id, user_id))
            if record is None:
                return False
            message_ids = select(MessageRecord.message_id).where(
                MessageRecord.session_id == session_id,
                MessageRecord.tenant_id == tenant_id,
                MessageRecord.user_id == user_id,
            )
            await session.execute(
                delete(FeedbackRecord).where(FeedbackRecord.message_id.in_(message_ids))
            )
            await session.execute(
                delete(MessageRecord).where(
                    MessageRecord.session_id == session_id,
                    MessageRecord.tenant_id == tenant_id,
                    MessageRecord.user_id == user_id,
                )
            )
            await session.delete(record)
            await session.commit()
        return True

    async def _backfill_sessions(self) -> None:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(MessageRecord).order_by(MessageRecord.created_at.asc())
                )
            ).all()
            sessions: dict[tuple[str, str, str], ChatSessionRecord] = {}
            for record in records:
                key = (record.session_id, record.tenant_id, record.user_id)
                existing = sessions.get(key)
                if existing is None:
                    existing = await session.get(ChatSessionRecord, key)
                if existing is None:
                    existing = ChatSessionRecord(
                        session_id=record.session_id,
                        tenant_id=record.tenant_id,
                        user_id=record.user_id,
                        title=_session_title(record.query),
                        created_at=record.created_at,
                        updated_at=record.created_at,
                    )
                    session.add(existing)
                else:
                    existing.updated_at = max(existing.updated_at, record.created_at)
                sessions[key] = existing
            await session.commit()


def _session_title(query: str) -> str:
    compact = " ".join(query.split())
    return compact[:80] or "New chat"


def _trace_from_record(record: MessageRecord) -> MessageTrace:
    return MessageTrace(
        message_id=record.message_id,
        session_id=record.session_id,
        query=record.query,
        rewritten_query=record.rewritten_query,
        answer=record.answer,
        retrieved_documents=record.retrieved_documents,
        timings_ms=record.timings_ms,
        tenant_id=record.tenant_id,
        user_id=record.user_id,
        created_at=record.created_at,
    )