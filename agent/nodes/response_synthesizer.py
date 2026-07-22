"""回复生成节点 — 基于 SOUL + SOP + 上下文生成最终回复

整合提示词装配器输出、RAG 知识片段和工具执行结果，
通过 DeepSeek-V3 生成符合品牌人格的客服回复。
"""

import litellm
import structlog
from langchain_core.messages import AIMessage

from agent.state import AgentState
from prompts.assembler import assemble_prompt

logger = structlog.get_logger()


async def response_synthesizer(state: AgentState) -> dict:
    """回复生成节点。

    1. 调用 prompt assembler 动态装配 System Prompt (SOUL + SOP + 实体)
    2. 注入 RAG 知识片段
    3. 调用 LLM 生成回复
    4. 返回 AIMessage 追加到 state.messages
    """
    intent = state.get("intent") or "faq"
    entities = state.get("entities", {})
    rag_context = state.get("rag_context", [])
    tool_outputs = state.get("tool_outputs", [])
    messages = state["messages"]

    # 1. 动态装配 System Prompt
    system_prompt = assemble_prompt(
        intent=intent,
        entities=entities,
        rag_context=rag_context,
        tool_outputs=tool_outputs,
    )

    # 2. 构建 LLM 消息序列 — 滑动窗口保留最近 3 轮
    llm_messages = [{"role": "system", "content": system_prompt}]

    # 取最近 6 条消息 (约 3 轮对话: user+assistant 交替)
    recent_messages = messages[-6:] if len(messages) > 6 else messages
    for msg in recent_messages:
        role = "user" if msg.type == "human" else "assistant"
        content_str = str(msg.content) if not isinstance(msg.content, str) else msg.content
        llm_messages.append({"role": role, "content": content_str})

    # 3. 注入工具错误提示（如果有）
    tool_error = entities.get("tool_error")
    if tool_error:
        llm_messages.append({
            "role": "system",
            "content": (
                f"工具执行返回业务提示：{tool_error}\n"
                "请根据此信息向用户解释情况，并给出 SOP 中的替代方案。"
            ),
        })

    logger.info(
        "response_synthesizer.generating",
        intent=intent,
        num_messages=len(llm_messages),
        has_rag=bool(rag_context),
        has_tool_error=bool(tool_error),
    )

    from core.dependencies import container

    try:
        reply_content = await container.llm_provider.generate(
            messages=llm_messages,
            temperature=0.7,
            max_tokens=1024,
        )

        logger.info(
            "response_synthesizer.completed",
            reply_length=len(reply_content),
        )

        return {
            "messages": [AIMessage(content=reply_content)],
        }

    except Exception as e:
        logger.error("response_synthesizer.llm_error", error=str(e))
        # LLM 失败时的兜底回复
        fallback_reply = (
            "非常抱歉，系统暂时遇到了一些问题，无法为您生成回复。"
            "我将为您转接人工客服，请稍等。"
        )
        return {
            "messages": [AIMessage(content=fallback_reply)],
            "escalation_reason": f"response_generation_failed: {e}",
            "intent": "human_request",
        }
