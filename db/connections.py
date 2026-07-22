"""
Dual async database engines: PostgreSQL (read/write) and MySQL (read-only).

Provides:
    - pg_engine / pg_session_factory  — PostgreSQL async engine & session
    - mysql_engine / mysql_session_factory — MySQL async engine & session
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import settings

# ═══════════════════════════════════════════════════════════════════════
# PostgreSQL — Primary read/write store (pgvector, sessions, knowledge)
# ═══════════════════════════════════════════════════════════════════════
pg_engine: AsyncEngine = create_async_engine(
    settings.POSTGRES_DSN,
    echo=settings.debug,
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "jit": "off",                  # faster short queries
            "statement_timeout": "30000",  # 30 s hard limit
        },
        "command_timeout": 30,
    },
)

pg_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=pg_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

PgSession = pg_session_factory

# ═══════════════════════════════════════════════════════════════════════
# MySQL — Read-only e-commerce data (orders, products, users, payments)
# ═══════════════════════════════════════════════════════════════════════
mysql_engine: AsyncEngine = create_async_engine(
    settings.MYSQL_DSN,
    echo=settings.debug,
    pool_size=10,
    max_overflow=5,
    pool_timeout=20,
    pool_recycle=900,
    pool_pre_ping=True,
)

mysql_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=mysql_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

MysqlSession = mysql_session_factory



# Redis client setup
import redis.asyncio as aioredis

_redis_client = None

async def get_redis_client() -> aioredis.Redis:
    """Get or initialize the global Redis async client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL)
    return _redis_client


# ═══════════════════════════════════════════════════════════════════════
# Engine lifecycle
# ═══════════════════════════════════════════════════════════════════════
async def dispose_engines() -> None:
    """Gracefully close all connection pools (call on app shutdown)."""
    global _redis_client
    await pg_engine.dispose()
    await mysql_engine.dispose()
    if _redis_client is not None:
        await _redis_client.close()

