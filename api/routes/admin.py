"""后台管理路由 (admin.py) — 退款审批、人工接管和状态监控

处理需要人工介入的流程，控制 LangGraph 挂起的状态节点继续运行。
"""

import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
import structlog
from langgraph.types import Command
from langchain_core.runnables import RunnableConfig

from agent.graph import agent_graph
from api.middleware.auth import verify_jwt_token, UserContext
from db.connections import get_redis_client, PgSession
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
    async with PgSession() as session:
        stmt = (
            select(PendingRefund)
            .where(
                PendingRefund.tenant_id == context.tenant_id,
                PendingRefund.status == RefundStatus.PENDING,
            )
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        refunds = result.scalars().all()

        return [
            {
                "id": str(r.id),
                "order_id": r.order_id,
                "amount": float(r.amount),
                "reason": r.reason,
                "ai_checks": r.metadata_.get("ai_checks") if r.metadata_ else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in refunds
        ]


@router.post("/approve/{refund_id}")
async def approve_refund(
    refund_id: str,
    context: UserContext = Depends(verify_jwt_token),
):
    """人工审批通过退款单。通过 LangGraph resume() 恢复状态机运行。"""
    logger.info(
        "admin.approve_refund", refund_id=refund_id, approver=context.user_id
    )

    async with PgSession() as session:
        # 1. 查找并更新待审批单状态
        stmt = select(PendingRefund).where(PendingRefund.id == refund_id)
        result = await session.execute(stmt)
        refund = result.scalar_one_or_none()

        if not refund:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="退款审批单不存在"
            )

        if refund.status != RefundStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"审批单已处理过，当前状态为: {refund.status}",
            )

        refund.status = RefundStatus.APPROVED
        refund.reviewed_by = context.user_id
        await session.commit()

        # 2. 恢复挂起的 LangGraph 节点
        # 使用 Command(resume=...) 发送通过信号给挂起的 human_interrupt 节点
        config: RunnableConfig = {"configurable": {"thread_id": str(refund.session_id)}}
        resume_payload = {
            "approved": True,
            "approver_id": context.user_id,
        }

        try:
            # 触发 LangGraph 执行后续节点
            await agent_graph.ainvoke(
                Command(resume=resume_payload), config=config
            )

            # 推送事件广播到 SSE 用户的连接中
            redis_client = await get_redis_client()
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

        except Exception as e:
            logger.error("admin.resume_failed", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"恢复状态机执行失败: {e}",
            )

        return {"status": "success", "message": "已审批通过，状态机已恢复执行"}


@router.post("/reject/{refund_id}")
async def reject_refund(
    refund_id: str,
    reason: str = "拒绝退款",
    context: UserContext = Depends(verify_jwt_token),
):
    """人工审批拒绝退款单。通过 LangGraph resume() 返回拒绝结果。"""
    logger.info(
        "admin.reject_refund", refund_id=refund_id, approver=context.user_id
    )

    async with PgSession() as session:
        stmt = select(PendingRefund).where(PendingRefund.id == refund_id)
        result = await session.execute(stmt)
        refund = result.scalar_one_or_none()

        if not refund:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="退款审批单不存在"
            )

        refund.status = RefundStatus.REJECTED
        refund.reviewed_by = context.user_id
        await session.commit()

        # 恢复状态机，并告知拒绝原因
        config: RunnableConfig = {"configurable": {"thread_id": str(refund.session_id)}}
        resume_payload = {"approved": False, "reason": reason}

        await agent_graph.ainvoke(Command(resume=resume_payload), config=config)

        # 推送至用户长连接
        redis_client = await get_redis_client()
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
    logger.info(
        "admin.takeover", session_id=session_id, agent_user=context.user_id
    )

    redis_client = await get_redis_client()
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
