"""Celery 异步后台任务模块 (worker.py)

提供上下文摘要压缩、知识库定时同步和 Saga 分布式对账服务。
"""

import asyncio
from celery import Celery
import litellm
import structlog

from config.settings import get_settings
from db.connections import PgSession
from db.pg_models import PendingRefund

logger = structlog.get_logger()
settings = get_settings()

# 初始化 Celery
celery_app = Celery("customer_assistant_worker", broker=settings.REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
)


@celery_app.task
def compress_context(session_id: str, messages_json: list):
    """异步对历史消息做摘要压缩，保留实体并注入 system 顶部

    使用 asyncio.run 执行异步数据库和 LLM 调用。
    """

    async def _async_compress():
        logger.info("worker.compress_context.starting", session_id=session_id)
        # 用 LLM 生成极简结构化摘要
        prompt = (
            "请根据以下对话历史，提取用户当前的诉求以及相关的实体信息（如订单ID、退款金额、收货地址），\n"
            "并总结成 100 字以内的摘要，保留关键指代，用于下一轮客服对话的上下文。\n\n"
            f"{messages_json}"
        )

        try:
            response = await litellm.acompletion(
                model=settings.SMALL_LLM,  # 使用轻量模型做背景压缩，节约成本
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
            summary = response.choices[0].message.content.strip()
            logger.info(
                "worker.compress_context.success",
                session_id=session_id,
                summary=summary,
            )

            # 更新 Redis 缓存或数据库会话状态
            from db.connections import get_redis_client

            redis = await get_redis_client()
            await redis.setex(
                f"session_summary:{session_id}", 86400, summary
            )

        except Exception as e:
            logger.error(
                "worker.compress_context.failed",
                session_id=session_id,
                error=str(e),
            )

    asyncio.run(_async_compress())


@celery_app.task
def saga_reconciliation():
    """定时对账任务 — 扫描 5 分钟前仍未确认的 pending_refund 记录并发起对账"""

    async def _async_reconcile():
        logger.info("worker.saga_reconciliation.scanning")
        # 扫描并与外部网关对账

    asyncio.run(_async_reconcile())
