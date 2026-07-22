"""StateGraph 会话与持久化 Checkpointer 管理器 (session_manager.py)"""

from __future__ import annotations

from typing import Optional
import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from config.settings import settings

logger = structlog.get_logger()


class SessionManager:
    """PostgreSQL 状态检查点管理器 (懒加载单例模式)"""

    def __init__(self) -> None:
        self.checkpointer: Optional[BaseCheckpointSaver] = None
        self._context_manager = None

    async def get_checkpointer(self) -> BaseCheckpointSaver:
        """获取并创建 AsyncPostgresSaver 实例，自动建表与维护连接生命周期。"""
        if self.checkpointer is not None:
            return self.checkpointer

        try:
            dsn = settings.POSTGRES_DSN.replace("postgresql+asyncpg://", "postgresql://")
            self._context_manager = AsyncPostgresSaver.from_conn_string(dsn)
            saver = await self._context_manager.__aenter__()
            await saver.setup()
            self.checkpointer = saver
            logger.info("session_manager.postgres_checkpointer_initialized")
        except Exception as e:
            from langgraph.checkpoint.memory import MemorySaver

            logger.warning(
                "session_manager.postgres_checkpointer_failed_fallback_to_memory",
                error=str(e),
            )
            self.checkpointer = MemorySaver()

        return self.checkpointer

    async def close(self) -> None:
        """应用关闭时安全释放 Checkpointer 连接资源。"""
        if self._context_manager is not None:
            try:
                await self._context_manager.__aexit__(None, None, None)
            except Exception as e:
                logger.warning("session_manager.close_error", error=str(e))
            self._context_manager = None
            self.checkpointer = None


# 全局单例管理器
session_manager = SessionManager()
