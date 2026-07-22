"""统一转人工决策与触发引擎 (escalation.py)"""

import json
import structlog

from core.dependencies import container

logger = structlog.get_logger()


class EscalationEngine:
    """提供统一的转人工判定与通知引擎"""

    @classmethod
    async def publish_escalation_event(cls, session_id: str, tenant_id: str, reason: str, payload: dict):
        """发布转人工事件到 Redis Pub/Sub"""
        logger.info("escalation.publishing", session_id=session_id, reason=reason)
        
        event_data = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "escalation_reason": reason,
            "payload": payload
        }
        
        redis_client = container.cache_redis.client
        if not redis_client:
            raise RuntimeError("Redis 客户端未初始化")
        
        # 1. 写入会话挂起队列
        await redis_client.hset(f"escalated_sessions:{tenant_id}", session_id, json.dumps(event_data, ensure_ascii=False))  # type: ignore[misc]
        
        # 2. 发布事件到通道，通知监听中的前端/排队系统
        await redis_client.publish(  # type: ignore[misc]
            f"session:{session_id}",
            json.dumps({"event": "escalated", "data": f"已触发转人工服务。原因: {reason}"}, ensure_ascii=False)
        )
        
        logger.info("escalation.published", session_id=session_id)
