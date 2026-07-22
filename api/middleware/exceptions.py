"""全局未捕获与业务领域异常统一拦截包装器 (api/middleware/exceptions.py)"""

import traceback
import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from api.middleware.request_id import get_current_request_id
from core.exceptions import AppException

logger = structlog.get_logger()


def setup_exception_handlers(app: FastAPI) -> None:
    """为 FastAPI 应用挂载全局异常拦截器"""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """处理声明的领域业务异常"""
        logger.warning(
            "api.app_exception",
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": get_current_request_id(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """处理未捕获的全局 500 兜底异常"""
        logger.error(
            "api.unhandled_exception",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": 50000,
                "message": "服务器内部错误，请稍后再试",
                "details": str(exc),
                "request_id": get_current_request_id(),
            },
        )
