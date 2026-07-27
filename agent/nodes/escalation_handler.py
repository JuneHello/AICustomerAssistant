"""转人工节点 — 构建 Handoff Payload 并发布转接事件

收集会话上下文、实体、AI 已执行的操作，打包成结构化交接包，
通过 Redis Pub/Sub 通知人工客服系统。
"""

import json
from datetime import datetime, timezone

import structlog
from langchain_core.messages import AIMessage

from agent.state import AgentState

logger = structlog.get_logger()


async def escalation_handler(state: AgentState) -> dict:
    """转人工处理节点。

    构建结构化 Handoff Payload（非扔原始聊天记录），
    通过 Redis Pub/Sub 发布 escalation 事件。
    """
    session_id = state.get("session_id", "")
    tenant_id = state.get("tenant_id", "")
    user_id = state.get("user_id", "")
    entities = state.get("entities", {})
    escalation_reason = state.get("escalation_reason") or "unknown"
    messages = state.get("messages", [])

    # 提取最近 3 轮原始对话
    recent_messages = []
    for msg in messages[-6:]:
        content_str = str(msg.content) if not isinstance(msg.content, str) else msg.content
        recent_messages.append({
            "role": "user" if msg.type == "human" else "assistant",
            "content": content_str[:500],  # 截断过长消息
        })

    # 构建 Handoff Payload
    handoff_payload = {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "escalation_reason": escalation_reason,
        "summary": _build_summary(entities, escalation_reason),
        "user_emotion": _detect_emotion(messages),
        "entities": entities,
        "ai_actions_taken": _extract_ai_actions(messages),
        "pending_refund_id": entities.get("refund_id"),
        "recent_messages": recent_messages,
        "escalated_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "escalation_handler.escalating",
        session_id=session_id,
        reason=escalation_reason,
        entity_count=len(entities),
    )

    # 通过 EscalationEngine 统一发布转接事件
    try:
        from services.escalation import EscalationEngine

        await EscalationEngine.publish_escalation_event(
            session_id=session_id,
            tenant_id=tenant_id,
            reason=escalation_reason,
            payload=handoff_payload,
        )
    except Exception as e:
        logger.error("escalation_handler.publish_failed", error=str(e))

    # 生成用户提示消息
    return {
        "messages": [
            AIMessage(
                content=(
                    "我已为您转接人工客服，客服人员将会看到我们之前的沟通记录。\n"
                    "请稍等片刻，马上就会有专人为您服务 🙏"
                )
            )
        ],
    }


def _build_summary(entities: dict, reason: str) -> str:
    """根据实体和转接原因生成简洁摘要。"""
    parts = []
    if entities.get("order_id"):
        parts.append(f"关联订单 #{entities['order_id']}")
    if entities.get("amount"):
        parts.append(f"金额 ¥{entities['amount']}")
    if entities.get("order_status"):
        parts.append(f"订单状态: {entities['order_status']}")

    summary = "，".join(parts) if parts else "用户咨询"
    return f"{summary}。转接原因: {reason}"


def _detect_emotion(messages: list) -> str:
    """简单的情绪检测（基于关键词）。"""
    if not messages:
        return "neutral"

    angry_keywords = {"投诉", "差评", "曝光", "垃圾", "骗子", "举报", "消协", "工商"}
    anxious_keywords = {"着急", "催", "等很久", "什么时候", "急用", "快点"}

    recent_text = " ".join(
        msg.content for msg in messages[-4:] if msg.type == "human"
    )

    if any(kw in recent_text for kw in angry_keywords):
        return "angry"
    if any(kw in recent_text for kw in anxious_keywords):
        return "anxious"
    return "neutral"


def _extract_ai_actions(messages: list) -> list[str]:
    """从对话历史中提取 AI 已执行的操作。"""
    actions = []
    for msg in messages:
        if msg.type != "human" and hasattr(msg, "additional_kwargs"):
            tool_calls = msg.additional_kwargs.get("tool_calls", [])
            for tc in tool_calls:
                func_name = tc.get("function", {}).get("name", "unknown")
                actions.append(f"{func_name}: executed")
    return actions if actions else ["no_tools_executed"]
