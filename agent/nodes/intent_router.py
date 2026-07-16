"""意图路由节点 — 基于 LLM 的意图分类

将用户消息分类到以下意图之一：
- faq: 常见问题 / 商品咨询
- order_query: 查询订单状态
- logistics_query: 查询物流信息
- refund_request: 申请退款/退货
- complaint: 投诉/不满
- human_request: 用户主动要求转人工
"""

import json

import litellm
import structlog

from agent.state import AgentState

logger = structlog.get_logger()

# 意图分类的 System Prompt
INTENT_CLASSIFICATION_PROMPT = """你是一个意图分类器。根据用户的最新消息，将其分类为以下意图之一：

- faq: 常见问题咨询、商品信息查询、退换货政策咨询
- order_query: 查询订单状态、订单详情
- logistics_query: 查询物流信息、快递进度
- refund_request: 申请退款、退货、换货、赔偿
- complaint: 投诉、表达不满、要求解释
- human_request: 用户明确要求转人工客服

仅返回 JSON 格式：{"intent": "<意图标签>", "confidence": <0.0-1.0>}
不要返回其他任何内容。"""

VALID_INTENTS = {
    "faq", "order_query", "logistics_query",
    "refund_request", "complaint", "human_request",
}


async def intent_router(state: AgentState) -> dict:
    """LLM 意图分类节点。

    从 state.messages 中取最新的用户消息，调用 DeepSeek 进行意图分类。
    低置信度 (<0.5) 时自动标记为 human_request 转人工。
    """
    messages = state["messages"]
    if not messages:
        logger.warning("intent_router: 空消息列表")
        return {"intent": "human_request", "escalation_reason": "empty_messages"}

    # 取最新用户消息
    last_message = messages[-1]
    user_content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )

    logger.info("intent_router.classifying", user_message=user_content[:100])

    from config.settings import settings
    try:
        response = await litellm.acompletion(
            model=settings.PRIMARY_LLM,
            messages=[
                {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
            max_tokens=100,
            response_format={"type": "json_object"},
        )

        result_text = response.choices[0].message.content.strip()
        result = json.loads(result_text)

        intent = result.get("intent", "faq")
        confidence = result.get("confidence", 0.0)

        # 校验意图有效性
        if intent not in VALID_INTENTS:
            logger.warning("intent_router.invalid_intent", raw_intent=intent)
            intent = "faq"
            confidence = 0.3

        # 低置信度强制转人工
        if confidence < 0.5:
            logger.info(
                "intent_router.low_confidence",
                intent=intent,
                confidence=confidence,
            )
            return {
                "intent": "human_request",
                "escalation_reason": f"low_confidence_{intent}_{confidence:.2f}",
            }

        logger.info(
            "intent_router.classified",
            intent=intent,
            confidence=confidence,
        )
        return {"intent": intent}

    except (json.JSONDecodeError, KeyError) as e:
        logger.error("intent_router.parse_error", error=str(e))
        return {"intent": "faq"}

    except Exception as e:
        logger.error("intent_router.llm_error", error=str(e))
        return {
            "intent": "human_request",
            "escalation_reason": f"intent_classification_failed: {e}",
        }
