"""
Read-only SQLAlchemy 2.0 models mapped to the e-commerce MySQL database.

These models are intentionally read-only — the Agent queries order, product,
user, payment, and inventory data but never writes back to the business DB.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class MysqlBase(DeclarativeBase):
    """Base class for all MySQL read-only models."""
    pass


# ═══════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════

class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDING = "refunding"
    REFUNDED = "refunded"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    ALIPAY = "alipay"
    WECHAT_PAY = "wechat_pay"
    CREDIT_CARD = "credit_card"
    BANK_TRANSFER = "bank_transfer"


# ═══════════════════════════════════════════════════════════════════════
# Order
# ═══════════════════════════════════════════════════════════════════════

class Order(MysqlBase):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(256), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False
    )
    shipping_address: Mapped[Optional[str]] = mapped_column(Text)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(128))
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_created_at", "created_at"),
    )


# ═══════════════════════════════════════════════════════════════════════
# Product
# ═══════════════════════════════════════════════════════════════════════

class Product(MysqlBase):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    brand: Mapped[Optional[str]] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_products_category", "category"),
        Index("ix_products_name", "name"),
    )


# ═══════════════════════════════════════════════════════════════════════
# User (e-commerce customer, NOT the admin user)
# ═══════════════════════════════════════════════════════════════════════

class User(MysqlBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(256))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    nickname: Mapped[Optional[str]] = mapped_column(String(128))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512))
    is_vip: Mapped[bool] = mapped_column(default=False)
    vip_level: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_users_phone", "phone"),
        Index("ix_users_email", "email"),
    )


# ═══════════════════════════════════════════════════════════════════════
# Payment
# ═══════════════════════════════════════════════════════════════════════

class Payment(MysqlBase):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus), default=PaymentStatus.PENDING, nullable=False
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_payments_user_status", "user_id", "status"),
    )


# ═══════════════════════════════════════════════════════════════════════
# Inventory
# ═══════════════════════════════════════════════════════════════════════

class Inventory(MysqlBase):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    total_stock: Mapped[int] = mapped_column(Integer, default=0)
    reserved_stock: Mapped[int] = mapped_column(Integer, default=0)
    available_stock: Mapped[int] = mapped_column(Integer, default=0)
    warehouse: Mapped[Optional[str]] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_inventory_warehouse", "warehouse"),
    )
