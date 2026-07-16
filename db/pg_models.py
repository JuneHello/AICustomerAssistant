"""
PostgreSQL ORM models (SQLAlchemy 2.0 Mapped style).

Tables:
    - tenants           Multi-tenant configuration
    - sessions          Chat sessions per tenant
    - messages          Conversation messages (user / assistant / tool)
    - knowledge_bases   RAG knowledge chunks with pgvector embeddings
    - pending_refunds   Refund requests awaiting approval
    - saga_logs         Saga transaction log for distributed operations
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class PgBase(DeclarativeBase):
    """Base class for all PostgreSQL models."""

    type_annotation_map = {
        dict: JSONB,
    }


# ═══════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════

class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class RefundStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SagaStepStatus(str, enum.Enum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


# ═══════════════════════════════════════════════════════════════════════
# Tenant
# ═══════════════════════════════════════════════════════════════════════

class Tenant(PgBase):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(256))
    api_key_hash: Mapped[Optional[str]] = mapped_column(String(128))
    config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # relationships
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )
    knowledge_bases: Mapped[list["KnowledgeBase"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_tenants_name", "name"),
        Index("ix_tenants_is_active", "is_active"),
    )


# ═══════════════════════════════════════════════════════════════════════
# Session
# ═══════════════════════════════════════════════════════════════════════

class Session(PgBase):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(512))
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default=dict)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="Message.sequence_number",
    )

    __table_args__ = (
        Index("ix_sessions_tenant_user", "tenant_id", "user_id"),
        Index("ix_sessions_created_at", "created_at"),
    )


# ═══════════════════════════════════════════════════════════════════════
# Message
# ═══════════════════════════════════════════════════════════════════════

class Message(PgBase):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, name="message_role", create_constraint=True),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(128))
    tool_name: Mapped[Optional[str]] = mapped_column(String(128))
    tool_args: Mapped[Optional[dict]] = mapped_column(JSONB)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # relationships
    session: Mapped["Session"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_session_seq", "session_id", "sequence_number"),
        Index("ix_messages_created_at", "created_at"),
        UniqueConstraint("session_id", "sequence_number", name="uq_session_sequence"),
    )


# ═══════════════════════════════════════════════════════════════════════
# KnowledgeBase (RAG embeddings via pgvector)
# ═══════════════════════════════════════════════════════════════════════

class KnowledgeBase(PgBase):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(1024))
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    embedding = mapped_column(Vector(1024), nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="knowledge_bases")

    __table_args__ = (
        Index("ix_kb_tenant_id", "tenant_id"),
        Index("ix_kb_source", "source"),
        Index(
            "ix_kb_embedding_cosine",
            embedding,
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


# ═══════════════════════════════════════════════════════════════════════
# PendingRefund
# ═══════════════════════════════════════════════════════════════════════

class PendingRefund(PgBase):
    __tablename__ = "pending_refunds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        Enum(RefundStatus, name="refund_status", create_constraint=True),
        default=RefundStatus.PENDING,
    )
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(128))
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_refunds_tenant_status", "tenant_id", "status"),
        Index("ix_refunds_order_id", "order_id"),
        Index("ix_refunds_user_id", "user_id"),
        Index("ix_refunds_created_at", "created_at"),
    )


# ═══════════════════════════════════════════════════════════════════════
# SagaLog (distributed transaction tracking)
# ═══════════════════════════════════════════════════════════════════════

class SagaLog(PgBase):
    __tablename__ = "saga_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    saga_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[SagaStepStatus] = mapped_column(
        Enum(SagaStepStatus, name="saga_step_status", create_constraint=True),
        default=SagaStepStatus.STARTED,
    )
    input_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    output_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    compensation_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_saga_logs_saga_id_order", "saga_id", "step_order"),
        Index("ix_saga_logs_tenant_status", "tenant_id", "status"),
        Index("ix_saga_logs_created_at", "created_at"),
    )
