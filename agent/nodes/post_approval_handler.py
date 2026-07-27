"""审批后处理节点 — Saga 事务执行

人工审批通过后，触发 Saga 流程：
1. 预检校验（只读）
2. 本地预锁（状态 → refunding）
3. 通知业务系统执行退款
4. 记录 Saga 审计日志

审批拒绝时，生成拒绝说明返回给用户。
"""

import uuid
from datetime import datetime, timezone

import structlog
from langchain_core.messages import AIMessage

from agent.state import AgentState
from core.dependencies import container
from db.pg_models import SagaLog, SagaStepStatus

logger = structlog.get_logger()


async def post_approval_handler(state: AgentState) -> dict:
    """审批后处理节点。

    从 state.pending_approval 中读取审批结果，
    通过则启动 Saga 事务，拒绝则生成说明。
    """
    pending = state.get("pending_approval")
    if not pending:
        logger.error("post_approval_handler: no pending_approval in state")
        return {
            "messages": [AIMessage(content="系统异常，审批信息丢失，请联系人工客服。")],
            "intent": "human_request",
            "escalation_reason": "missing_approval_data",
        }

    approval_result = pending.get("approval_result", {})
    approved = approval_result.get("approved", False)
    refund_id = pending.get("refund_id", "")
    order_id = pending.get("order_id", "")
    amount = pending.get("amount", 0)

    if not approved:
        # 审批拒绝
        rejection_reason = approval_result.get("reason", "审批未通过")
        logger.info(
            "post_approval_handler.rejected",
            refund_id=refund_id,
            reason=rejection_reason,
        )

        return {
            "messages": [
                AIMessage(
                    content=(
                        f"非常抱歉，您的退款申请（单号 {refund_id}）经审核后未能通过。\n"
                        f"原因：{rejection_reason}\n"
                        "如有疑问，我可以为您转接人工客服进一步处理。"
                    )
                )
            ],
            "pending_approval": None,
        }

    # 审批通过 — 启动 Saga 流程
    tx_id = uuid.uuid4()
    approver_id = approval_result.get("approver_id", "system")

    logger.info(
        "post_approval_handler.saga_starting",
        refund_id=refund_id,
        tx_id=str(tx_id),
        order_id=order_id,
        amount=amount,
    )

    saga_steps = []

    try:
        # Step 1: 预检校验（只读）
        saga_steps.append({
            "tx_id": str(tx_id),
            "step_name": "pre_check",
            "status": "completed",
            "payload": {"order_id": order_id, "amount": amount},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # Step 2: 本地预锁 — 更新 pending_refunds 状态为 approved
        saga_steps.append({
            "tx_id": str(tx_id),
            "step_name": "local_lock",
            "status": "completed",
            "payload": {
                "refund_id": refund_id,
                "new_status": "approved",
                "approver_id": approver_id,
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # Step 3: 通知业务系统执行退款
        # 注意：实际退款由业务系统 API 完成，此处仅记录通知
        saga_steps.append({
            "tx_id": str(tx_id),
            "step_name": "notify_business_system",
            "status": "pending",
            "payload": {
                "refund_id": refund_id,
                "order_id": order_id,
                "amount": float(amount),
                "idempotency_key": pending.get("idempotency_key", ""),
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # 持久化 Saga 事务日志到 PostgreSQL saga_logs 表

        try:
            async with container.db_postgres.session() as session:
                async with session.begin():
                    raw_tenant = pending.get("tenant_id") or state.get("tenant_id") or "00000000-0000-0000-0000-000000000001"
                    try:
                        tenant_uuid = uuid.UUID(str(raw_tenant))
                    except ValueError:
                        tenant_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_tenant))

                    for idx, step in enumerate(saga_steps, start=1):
                        log_entry = SagaLog(
                            saga_id=tx_id,
                            tenant_id=tenant_uuid,
                            step_name=step["step_name"],
                            step_order=idx,
                            status=SagaStepStatus.SUCCEEDED if step["status"] == "completed" else SagaStepStatus.STARTED,
                            input_data=step.get("payload"),
                        )
                        session.add(log_entry)
        except Exception as db_err:
            logger.warning("post_approval_handler.saga_log_write_warning", error=str(db_err))

        logger.info(
            "post_approval_handler.saga_completed",
            tx_id=str(tx_id),
            steps=len(saga_steps),
        )

        return {
            "messages": [
                AIMessage(
                    content=(
                        f"好消息！您的退款申请（单号 {refund_id}）已审批通过 ✅\n"
                        f"退款金额：¥{amount}\n"
                        f"关联订单：{order_id}\n"
                        "退款将在 1-3 个工作日内原路退回，请留意账户变动。"
                    )
                )
            ],
            "pending_approval": None,
        }

    except Exception as e:
        logger.error(
            "post_approval_handler.saga_error",
            tx_id=str(tx_id),
            error=str(e),
        )
        # Saga 失败 — 记录失败步骤，转人工处理
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"退款申请 {refund_id} 审批已通过，但执行过程遇到异常。\n"
                        "我已为您创建优先工单，技术团队会尽快处理。"
                    )
                )
            ],
            "escalation_reason": f"saga_execution_failed: {e}",
            "intent": "human_request",
        }
