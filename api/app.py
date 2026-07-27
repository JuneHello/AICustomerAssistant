"""FastAPI 应用工厂 (app.py)"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.exceptions import setup_exception_handlers
from api.middleware.rate_limit import RateLimitMiddleware
from api.middleware.request_id import RequestIDMiddleware
from api.routes import admin, chat
from core.dependencies import container

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """在应用启动和关闭时统一管理 DI 依赖注入容器生命周期"""
    logger.info("FastAPI 启动中：初始化全局 DI 容器单例组件...")
    await container.initialize()

    yield

    logger.info("FastAPI 关闭中：释放全局依赖连接池资源...")
    await container.close()
    logger.info("AICustomerAssistant 应用已成功优雅关闭。")


def create_app() -> FastAPI:
    """初始化配置与应用挂载"""
    app = FastAPI(
        title="商城智能客服 Agent API",
        description="智能客服大脑",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 1. 注册中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RateLimitMiddleware)

    # 2. 挂载全局异常拦截器
    setup_exception_handlers(app)

    # 3. 挂载路由模块
    app.include_router(chat.router, prefix="/api/v1/chat", tags=["聊天通道"])
    app.include_router(
        admin.router, prefix="/api/v1/admin", tags=["后台管理(审批/接管)"]
    )

    # 4. 健康检查端点（供 Docker HEALTHCHECK / K8s Liveness Probe 使用）
    @app.get("/health", tags=["系统"])
    async def healthcheck():
        return {"status": "ok"}

    return app


app = create_app()
