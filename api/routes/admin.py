"""后台管理路由 (admin.py) — 退款审批、人工接管和状态监控

处理需要人工介入的流程，控制 LangGraph 挂起的状态节点继续运行。
"""

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy import select

from agent.graph import compile_agent_graph
from api.middleware.auth import UserContext, verify_jwt_token
from core.dependencies import container
from db.pg_models import PendingRefund, RefundStatus

router = APIRouter()
logger = structlog.get_logger()


@router.get("/pending-refunds")
async def list_pending_refunds(
    limit: int = 10,
    offset: int = 0,
    context: UserContext = Depends(verify_jwt_token),
):
    """获取所有待人工审批的退款申请单"""
    return await container.refund_service.list_pending_refunds(
        tenant_id=str(context.tenant_id), limit=limit, offset=offset
    )


@router.post("/approve/{refund_id}")
async def approve_refund(
    refund_id: str,
    context: UserContext = Depends(verify_jwt_token),
):
    """人工审批通过退款单。通过 LangGraph resume() 恢复状态机运行。"""
    logger.info("admin.approve_refund", refund_id=refund_id, approver=context.user_id)

    # 1. 调用 RefundService 更新审批单状态
    refund = await container.refund_service.update_refund_status(
        refund_id=refund_id, approver_id=context.user_id, approved=True
    )

    # 2. 恢复挂起的 LangGraph 节点
    from domain.schemas.approval import ApprovalResumePayload
    resume_dto = ApprovalResumePayload(approved=True, approver_id=context.user_id)
    config: RunnableConfig = {"configurable": {"thread_id": str(refund.session_id)}}

    checkpointer = await container.session_manager.get_checkpointer()
    graph = compile_agent_graph(checkpointer=checkpointer)
    await graph.ainvoke(Command(resume=resume_dto.model_dump()), config=config)

    # 推送事件广播到 SSE 用户的连接中
    redis_client = container.cache_redis.client
    if redis_client:
        await redis_client.publish(
            f"session:{refund.session_id}",
            json.dumps(
                {
                    "event": "approved",
                    "data": f"退款单 {refund_id} 已由管理员审批通过",
                },
                ensure_ascii=False,
            ),
        )

    return {"status": "success", "message": "已审批通过，状态机已恢复执行"}


@router.post("/reject/{refund_id}")
async def reject_refund(
    refund_id: str,
    reason: str = "拒绝退款",
    context: UserContext = Depends(verify_jwt_token),
):
    """人工审批拒绝退款单。通过 LangGraph resume() 返回拒绝结果。"""
    logger.info("admin.reject_refund", refund_id=refund_id, approver=context.user_id)

    # 1. 调用 RefundService 更新审批单状态
    refund = await container.refund_service.update_refund_status(
        refund_id=refund_id, approver_id=context.user_id, approved=False
    )

    # 2. 恢复状态机，并告知拒绝原因
    from domain.schemas.approval import ApprovalResumePayload
    resume_dto = ApprovalResumePayload(approved=False, approver_id=context.user_id, reason=reason)
    config: RunnableConfig = {"configurable": {"thread_id": str(refund.session_id)}}

    checkpointer = await container.session_manager.get_checkpointer()
    graph = compile_agent_graph(checkpointer=checkpointer)
    await graph.ainvoke(Command(resume=resume_dto.model_dump()), config=config)

    # 推送至用户长连接
    redis_client = container.cache_redis.client
    if redis_client:
        await redis_client.publish(
            f"session:{refund.session_id}",
            json.dumps(
                {
                    "event": "rejected",
                    "data": f"退款申请已退回。原因: {reason}",
                },
                ensure_ascii=False,
            ),
        )

    return {"status": "success", "message": "退款申请已拒绝"}


@router.post("/takeover/{session_id}")
async def takeover_session(
    session_id: str,
    context: UserContext = Depends(verify_jwt_token),
):
    """人工接管会话。AI 停止服务，后续消息流切换回人工客服。"""
    logger.info("admin.takeover", session_id=session_id, agent_user=context.user_id)

    redis_client = container.cache_redis.client
    if not redis_client:
        raise RuntimeError("Redis 客户端未初始化")

    # 写入 Redis 缓存标识：该会话已被接管
    await redis_client.setex(f"takeover:{session_id}", 7200, context.user_id)

    # 广播接管事件
    await redis_client.publish(
        f"session:{session_id}",
        json.dumps(
            {"event": "takeover", "data": "人工客服已接管该会话，正在为您转接..."},
            ensure_ascii=False,
        ),
    )

    return {"status": "success", "message": "已成功接管会话"}
