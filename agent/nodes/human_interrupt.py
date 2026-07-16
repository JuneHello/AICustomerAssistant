"""人工审批中断节点 — 使用 LangGraph interrupt() 挂起等待

敏感操作（退款、赔付）在此节点暂停执行，等待人工审批结果。
状态通过 langgraph-checkpoint-postgres 自动持久化。
审批完成后通过 Command(resume=approval_result) 恢复。
"""

import uuid
from datetime import datetime, timezone

import structlog
from langgraph.types import interrupt

from agent.state import AgentState

logger = structlog.get_logger()


async def human_interrupt(state: AgentState) -> dict:
    """人工审批中断节点。

    1. 从 state.entities 提取退款信息
    2. 生成幂等键和审批单
    3. 调用 LangGraph interrupt() 挂起状态机
    4. 审批结果通过 Command(resume=...) 注入
    """
    entities = state.get("entities", {})
    session_id = state.get("session_id", "")
    tenant_id = state.get("tenant_id", "")

    # 构建审批单
    refund_id = f"RF-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    idempotency_key = f"idem-{session_id}-{uuid.uuid4().hex[:8]}"

    approval_request = {
        "refund_id": refund_id,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "order_id": entities.get("order_id", ""),
        "amount": entities.get("amount", 0),
        "reason": entities.get("refund_reason", "用户申请退款"),
        "idempotency_key": idempotency_key,
        "ai_checks": {
            "order_verified": entities.get("order_verified", False),
            "eligibility_checked": entities.get("eligibility_checked", False),
            "risk_level": entities.get("risk_level", "normal"),
        },
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "human_interrupt.requesting_approval",
        refund_id=refund_id,
        order_id=entities.get("order_id"),
        amount=entities.get("amount"),
    )

    # LangGraph interrupt() — 挂起状态机，等待人工审批
    # 审批结果将通过 Command(resume={"approved": True/False, ...}) 传回
    approval_result = interrupt(approval_request)

    logger.info(
        "human_interrupt.approval_received",
        refund_id=refund_id,
        approved=approval_result.get("approved"),
    )

    return {
        "pending_approval": {
            **approval_request,
            "approval_result": approval_result,
        },
    }
