"""输出安全检查 — 幻觉拦截、竞品过滤、承诺检查

在 Agent 回复发送给用户之前执行最后一道安全过滤。
"""

import re

import structlog
from langchain_core.messages import AIMessage

from agent.state import AgentState

logger = structlog.get_logger()

# ── 竞品品牌关键词（禁止在回复中提及）────────────────────────
COMPETITOR_BRANDS = {
    "京东", "拼多多", "淘宝", "天猫", "亚马逊", "唯品会",
    "苏宁", "当当", "网易严选", "小红书",
}

# ── 未授权承诺检测模式 ────────────────────────────────────────
UNAUTHORIZED_PROMISE_PATTERNS = [
    re.compile(r"(?:保证|承诺|一定).*(?:全额退款|免费|赠送)", re.IGNORECASE),
    re.compile(r"(?:我来|我给您).*(?:直接退款|立即退款)", re.IGNORECASE),
    re.compile(r"(?:已经|已为您).*(?:完成退款|处理退款|退回)", re.IGNORECASE),
]


def check_competitor_mentions(text: str) -> list[str]:
    """检测回复中是否提及竞品品牌。"""
    found = []
    for brand in COMPETITOR_BRANDS:
        if brand in text:
            found.append(brand)
    return found


def check_unauthorized_promises(text: str) -> list[str]:
    """检测回复中是否包含未授权承诺。"""
    found = []
    for pattern in UNAUTHORIZED_PROMISE_PATTERNS:
        match = pattern.search(text)
        if match:
            found.append(match.group())
    return found


def check_hallucination(text: str, entities: dict) -> bool:
    """基础幻觉检测 — 验证回复中的关键数据是否来自工具结果。

    如果回复中提到具体的订单号或金额，但 entities 中没有对应数据，
    可能是 LLM 编造的。
    """
    # 检测回复中是否出现了 entities 中不存在的订单号
    order_ids_in_reply = re.findall(r"(?:订单|单号)\s*[#:]?\s*(\d{8,})", text)
    known_order_id = str(entities.get("order_id", ""))

    for oid in order_ids_in_reply:
        if known_order_id and oid != known_order_id:
            logger.warning(
                "output_guard.possible_hallucination",
                found_order_id=oid,
                known_order_id=known_order_id,
            )
            return True

    return False


async def output_guardrails(state: AgentState) -> dict:
    """输出安全检查节点。

    对 Agent 的最后一条回复进行安全过滤：
    1. 竞品品牌提及拦截
    2. 未授权承诺拦截
    3. 幻觉检测
    """
    messages = state.get("messages", [])
    entities = state.get("entities", {})

    if not messages:
        return {}

    # 找到最后一条 AI 回复
    last_ai_message = None
    for msg in reversed(messages):
        if msg.type != "human":
            last_ai_message = msg
            break

    if not last_ai_message:
        return {}

    raw_content = last_ai_message.content
    reply_content = str(raw_content) if not isinstance(raw_content, str) else raw_content
    issues = []

    # 1. 竞品品牌检查
    competitor_mentions = check_competitor_mentions(reply_content)
    if competitor_mentions:
        logger.warning(
            "output_guard.competitor_mention",
            brands=competitor_mentions,
        )
        issues.append(f"competitor_mention:{','.join(competitor_mentions)}")
        # 移除竞品提及
        for brand in competitor_mentions:
            reply_content = reply_content.replace(brand, "其他平台")

    # 2. 未授权承诺检查
    unauthorized = check_unauthorized_promises(reply_content)
    if unauthorized:
        logger.warning(
            "output_guard.unauthorized_promise",
            promises=unauthorized,
        )
        issues.append(f"unauthorized_promise:{','.join(unauthorized)}")
        # 添加免责说明
        reply_content += "\n\n（具体退款金额和时效以实际审核结果为准）"

    # 3. 幻觉检测
    if check_hallucination(reply_content, entities):
        issues.append("possible_hallucination")
        # 幻觉严重时，替换为安全回复
        reply_content = (
            "抱歉，我在核实您的信息时遇到了一些问题。"
            "为了确保为您提供准确的信息，我建议为您转接人工客服处理。"
        )

    if issues:
        logger.info("output_guard.issues_found", issues=issues)
        return {
            "messages": [AIMessage(content=reply_content)],
        }

    return {}
