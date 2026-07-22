"""Redis 缓存基础组件 (db/redis.py)"""

from __future__ import annotations

from typing import Optional
import redis.asyncio as aioredis
import structlog

from config.settings import settings

logger = structlog.get_logger()


class RedisCache:
    """Redis 异步客户端管理类"""

    def __init__(self) -> None:
        self.client: Optional[aioredis.Redis] = None

    async def initialize(self) -> None:
        """初始化 Redis 异步连接客户端。"""
        if self.client is not None:
            return

        logger.info("redis.initializing_client")
        self.client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("redis.initialized")

    async def close(self) -> None:
        """释放 Redis 异步连接客户端。"""
        if self.client is not None:
            logger.info("redis.closing_client")
            if hasattr(self.client, "aclose"):
                await self.client.aclose()
            else:
                await self.client.close()
            self.client = None
