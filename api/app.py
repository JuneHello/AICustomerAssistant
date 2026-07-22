"""FastAPI 应用工厂 (app.py)"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.rate_limit import RateLimitMiddleware
from api.routes import admin, chat
from db.connections import mysql_engine, pg_engine

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """在应用启动和关闭时管理连接池与底层生命周期"""
    logger.info("Initializing AICustomerAssistant...")
    # 此时如果服务启动，说明引擎已经完成 create_async_engine

    yield

    # 优雅关闭连接池
    logger.info("Disposing database connections...")
    await mysql_engine.dispose()
    await pg_engine.dispose()
    logger.info("AICustomerAssistant shut down successfully.")


def create_app() -> FastAPI:
    """初始化配置与应用挂载"""
    app = FastAPI(
        title="商城智能客服 Agent API",
        description="智能客服大脑",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 跨域设置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 挂载限流中间件
    app.add_middleware(RateLimitMiddleware)

    # 挂载路由模块
    app.include_router(chat.router, prefix="/api/v1/chat", tags=["聊天通道"])
    app.include_router(
        admin.router, prefix="/api/v1/admin", tags=["后台管理(审批/接管)"]
    )

    return app


app = create_app()
