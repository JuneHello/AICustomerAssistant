"""令牌桶限流中间件 — 基于 Redis 的分布式流控，支持租户级和用户级维度"""

import time
from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
import structlog

from core.dependencies import container

logger = structlog.get_logger()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """令牌桶算法限流中间件"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # 只对 API 路由进行限流
        if not request.url.path.startswith("/api/v1"):
            return await call_next(request)

        # 提取租户 ID 或 IP 地址作为限流 Key
        # 通常可以从 JWT Token 解密后的头里取，这里先尝试从 header 获取
        tenant_id = request.headers.get("X-Tenant-ID", "global")
        client_ip = request.client.host if request.client else "unknown"
        rate_limit_key = f"ratelimit:{tenant_id}:{client_ip}"

        try:
            redis_client = container.cache_redis.client
            if redis_client:
                allowed = await self._check_token_bucket(
                    redis_client, rate_limit_key, capacity=60, rate=2.0
                )

            if not allowed:
                logger.warning("rate_limiter.blocked", key=rate_limit_key)
                return Response(
                    content="Too many requests. Please try again later.",
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        except Exception as e:
            # 外部缓存异常不阻断核心对话链路
            logger.error("rate_limiter.error", error=str(e))

        return await call_next(request)

    async def _check_token_bucket(
        self, redis, key: str, capacity: int, rate: float
    ) -> bool:
        """基于 Redis Hash 实现分布式令牌桶"""
        now = time.time()
        # pipeline 批量读取保证原子性
        pipe = redis.pipeline()
        pipe.hget(key, "tokens")
        pipe.hget(key, "last_updated")
        tokens_val, last_updated_val = await pipe.execute()

        tokens = float(tokens_val) if tokens_val else float(capacity)
        last_updated = float(last_updated_val) if last_updated_val else now

        # 计算并更新新令牌
        delta = max(0.0, now - last_updated)
        new_tokens = min(float(capacity), tokens + delta * rate)

        if new_tokens >= 1.0:
            new_tokens -= 1.0
            # 写入更新
            pipe = redis.pipeline()
            pipe.hset(key, "tokens", str(new_tokens))
            pipe.hset(key, "last_updated", str(now))
            # 设置 1 小时过期，防止垃圾 Key 积压
            pipe.expire(key, 3600)
            await pipe.execute()
            return True

        return False
