"""强类型 LangGraph 人工中断与审批 Resume Schema (domain/schemas/approval.py)"""

from typing import Any, Optional
from pydantic import BaseModel, Field


class ApprovalResumePayload(BaseModel):
    """人工审批 Resume 恢复执行 Payload"""

    approved: bool = Field(description="是否同意审批")
    approver_id: Optional[str] = Field(default=None, description="审批管理员ID")
    reason: Optional[str] = Field(default=None, description="拒绝原因或附加意见")


class HandoffPayload(BaseModel):
    """转人工客服交接 Payload"""

    session_id: str
    tenant_id: str
    user_id: str
    escalation_reason: str
    summary: str
    user_emotion: str = "neutral"
    entities: dict[str, Any] = Field(default_factory=dict)
    ai_actions_taken: list[str] = Field(default_factory=list)
    pending_refund_id: Optional[str] = None
    recent_messages: list[dict[str, str]] = Field(default_factory=list)
    escalated_at: str
