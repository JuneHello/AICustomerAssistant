"""请求追踪中间件 — 基于 ContextVar 串联 HTTP、LangGraph、数据库与日志 (api/middleware/request_id.py)"""

import uuid
from contextvars import ContextVar
from typing import Optional

import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_current_request_id() -> str:
    """获取当前协程上下文关联的 Request-ID"""
    return request_id_var.get() or "unknown_req"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """请求追踪中间件"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:8]}"
        token = request_id_var.set(req_id)
        structlog.contextvars.bind_contextvars(request_id=req_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_var.reset(token)
