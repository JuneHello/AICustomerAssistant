"""PostgreSQL 数据库基础组件 (db/postgres.py)"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config.settings import settings

logger = structlog.get_logger()


class PostgresDatabase:
    """PostgreSQL 异步连接池与 Session 工厂管理类"""

    def __init__(self) -> None:
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取 PostgreSQL AsyncSession 上下文管理器。"""
        if self.session_factory is None:
            raise RuntimeError("PostgreSQL 数据库尚未初始化，请先调用 initialize()")
        async with self.session_factory() as session:
            yield session

    async def initialize(self) -> None:
        """初始化 PostgreSQL 连接池引擎与 AsyncSession 工厂。"""
        if self.engine is not None:
            return

        logger.info("postgres.initializing_connection_pool")
        self.engine = create_async_engine(
            settings.POSTGRES_DSN,
            pool_size=settings.PG_POOL_SIZE,
            max_overflow=settings.PG_MAX_OVERFLOW,
            pool_pre_ping=True,
            echo=settings.SQL_ECHO,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        logger.info("postgres.initialized")

    async def close(self) -> None:
        """释放 PostgreSQL 连接池引擎。"""
        if self.engine is not None:
            logger.info("postgres.disposing_connection_pool")
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None
