"""退款提交工具 (agent/tools/refund_submit.py)"""

from langchain_core.tools import tool

from core.dependencies import container


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
    return await container.refund_service.submit_refund(
        order_id=order_id,
        amount=amount,
        reason=reason,
        tenant_id=kwargs.get("tenant_id"),
        session_id=kwargs.get("session_id"),
        user_id=kwargs.get("user_id"),
    )
