"""MySQL 数据库基础组件 (db/mysql.py)"""

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


class MySQLDatabase:
    """MySQL 只读业务库异步连接池与 Session 工厂管理类"""

    def __init__(self) -> None:
        self.engine: Optional[AsyncEngine] = None
        self.session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """获取 MySQL AsyncSession 上下文管理器。"""
        if self.session_factory is None:
            raise RuntimeError("MySQL 数据库尚未初始化，请先调用 initialize()")
        async with self.session_factory() as session:
            yield session

    async def initialize(self) -> None:
        """初始化 MySQL 连接池引擎与 AsyncSession 工厂。"""
        if self.engine is not None:
            return

        logger.info("mysql.initializing_connection_pool")
        self.engine = create_async_engine(
            settings.MYSQL_DSN,
            pool_size=settings.MYSQL_POOL_SIZE,
            max_overflow=settings.MYSQL_MAX_OVERFLOW,
            pool_pre_ping=True,
            echo=settings.SQL_ECHO,
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        logger.info("mysql.initialized")

    async def close(self) -> None:
        """释放 MySQL 连接池引擎。"""
        if self.engine is not None:
            logger.info("mysql.disposing_connection_pool")
            await self.engine.dispose()
            self.engine = None
            self.session_factory = None
