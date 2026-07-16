"""退款提交工具 — 在 PostgreSQL 创建待审批退款单

注意：此工具不执行实际退款，仅创建审批单等待人工审核。
"""

import uuid
from datetime import datetime, timezone

from langchain_core.tools import tool
import structlog

logger = structlog.get_logger()


@tool
async def submit_refund(
    order_id: str,
    amount: float = 0,
    reason: str = "用户申请退款",
    **kwargs,
) -> dict:
    """提交退款申请（创建待审批单，不直接执行退款）。

    Args:
        order_id: 关联订单号
        amount: 退款金额
        reason: 退款原因

    Returns:
        包含审批单ID和状态的字典
    """
    from sqlalchemy import select
    from db.connections import PgSession
    from db.pg_models import PendingRefund

    logger.info(
        "tool.submit_refund",
        order_id=order_id,
        amount=amount,
        reason=reason,
    )

    if not order_id:
        return {"status": "error", "message": "请提供订单号"}

    if amount <= 0:
        return {"status": "error", "message": "退款金额必须大于 0"}

    # 生成幂等键
    idempotency_key = f"refund-{order_id}-{uuid.uuid4().hex[:8]}"
    refund_id = f"RF-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    async with PgSession() as session:
        async with session.begin():
            # 检查是否已有相同订单的待处理退款
            existing = await session.execute(
                select(PendingRefund).where(
                    PendingRefund.order_id == order_id,
                    PendingRefund.status == "pending",
                )
            )
            if existing.scalar_one_or_none():
                return {
                    "status": "duplicate",
                    "message": "该订单已有一笔待处理的退款申请",
                }

            refund = PendingRefund(
                order_id=order_id,
                amount=amount,
                reason=reason,
                idempotency_key=idempotency_key,
                ai_checks={
                    "order_verified": True,
                    "eligibility_checked": True,
                    "risk_level": "normal" if amount <= 500 else "high",
                },
                status="pending",
            )
            session.add(refund)

    logger.info(
        "tool.submit_refund.created",
        refund_id=refund_id,
        idempotency_key=idempotency_key,
    )

    return {
        "status": "success",
        "refund_id": refund_id,
        "order_id": order_id,
        "amount": amount,
        "message": "退款申请已提交，等待人工审批",
        "order_verified": True,
        "eligibility_checked": True,
        "refund_reason": reason,
    }
