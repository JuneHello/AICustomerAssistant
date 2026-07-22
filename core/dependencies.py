"""全局依赖注入容器 (core/dependencies.py)"""

from __future__ import annotations

import asyncio
import structlog

from db.mysql import MySQLDatabase
from db.postgres import PostgresDatabase
from db.redis import RedisCache
from db.session_manager import SessionManager

logger = structlog.get_logger()


class DIContainer:
    """系统全局依赖注入 (Dependency Injection) 容器。

    管理 PostgreSQL, MySQL, Redis 连接池及 SessionManager 检查点的生命周期。
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._initialized = False

        # ===== 核心数据库与缓存单例 =====
        self.db_postgres = PostgresDatabase()
        self.db_mysql = MySQLDatabase()
        self.cache_redis = RedisCache()

        # ===== 会话状态检查点管理器 =====
        self.session_manager = SessionManager()

    async def initialize(self) -> None:
        """服务启动时触发组件的异步初始化与连接池预热。"""
        async with self._lock:
            if self._initialized:
                return

            logger.info("container.initializing_components")

            # 1. 核心数据库与缓存
            await self.db_postgres.initialize()
            await self.db_mysql.initialize()
            await self.cache_redis.initialize()

            # 2. 会话状态 checkpointer
            await self.session_manager.get_checkpointer()

            self._initialized = True
            logger.info("container.initialized_successfully")

    async def close(self) -> None:
        """服务关闭时安全释放所有底层连接池。"""
        async with self._lock:
            if not self._initialized:
                return

            logger.info("container.closing_components")

            if self.session_manager:
                await self.session_manager.close()
            if self.cache_redis:
                await self.cache_redis.close()
            if self.db_mysql:
                await self.db_mysql.close()
            if self.db_postgres:
                await self.db_postgres.close()

            self._initialized = False
            logger.info("container.closed_successfully")


# 全局唯一依赖注入容器单例
container = DIContainer()
