"""实体提取节点 — 基于 LLM 提取用户消息中的关键业务实体

提取用户消息中的 order_id, product_id, amount, refund_reason, tracking_number, keyword 等实体，
并自动合并写入到 state.entities 中，供后续工具执行节点使用。
"""

import json
import litellm
import structlog

from agent.state import AgentState
from config.settings import get_settings
from core.dependencies import container

logger = structlog.get_logger()
settings = get_settings()

ENTITY_EXTRACTION_PROMPT = """你是一个高精度的客服实体提取器。
请根据当前的【用户意图】和【用户最新消息】，提取出对话中包含的业务实体。

支持提取的字段：
- order_id: 订单号（通常为 8 位及以上的数字串，如 9821389421，请仔细识别）
- product_id: 商品ID
- amount: 金额（浮点数数字，如 299.0，不要包含单位或元字）
- refund_reason: 退款原因（例如 "下错单了"、"质量不好"、"不想要了" 等）
- tracking_number: 物流单号/运单号（例如 SF1049284201）
- keyword: 商品查询/搜索关键词

请以 JSON 格式输出，对于未提及或无法确认的字段，设为 null。
输出格式要求：{"order_id": str|null, "product_id": str|null, "amount": float|null, "refund_reason": str|null, "tracking_number": str|null, "keyword": str|null}

仅返回 JSON 格式结果，不要包含任何额外的解释或 Markdown 代码块包裹（不要包含 ```json 等）。"""


async def entity_extractor(state: AgentState) -> dict:
    """实体提取节点。

    从最新用户消息中提取关键业务实体并合入 state.entities。
    仅当意图为特定需要调用工具的意图时，此节点起作用，减少不必要的 LLM 调用开销。
    """
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    messages = state["messages"]

    # 非工具调用意图，或者无消息，跳过提取
    if not messages or intent not in ("order_query", "logistics_query", "refund_request", "faq", "product_query"):
        return {}

    last_message = messages[-1]
    user_content = (
        last_message.content if hasattr(last_message, "content") else str(last_message)
    )

    logger.info("entity_extractor.extracting", intent=intent, user_message=user_content[:100])


    try:
        user_prompt = (
            f"用户意图: {intent}\n"
            f"用户最新消息: {user_content}"
        )
        extracted = await container.llm_provider.generate_json(
            messages=[
                {"role": "system", "content": ENTITY_EXTRACTION_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
        )

        if not isinstance(extracted, dict):
            extracted = {}

        # 过滤掉 null 字段并合并到当前实体字典中
        new_entities = {**entities}
        for k, v in extracted.items():
            if v is not None and v != "":
                new_entities[k] = v

        logger.info(
            "entity_extractor.success",
            extracted_keys=[k for k, v in extracted.items() if v is not None and v != ""],
            entities=new_entities,
        )

        return {"entities": new_entities}

    except Exception as e:
        logger.error("entity_extractor.failed", error=str(e))
        # 提取失败时不中断对话，留给工具层或者后续逻辑报错/转人工
        return {}
