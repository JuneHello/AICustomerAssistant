"""RAG 检索节点 — 调用两阶段检索服务

从知识库中检索与用户问题最相关的知识片段，
存入 state.rag_context 供后续 response_synthesizer 使用。
"""

import structlog

from agent.state import AgentState
from services.rag import retrieve_knowledge

logger = structlog.get_logger()


async def rag_retriever(state: AgentState) -> dict:
    """知识库检索节点。

    从最新用户消息中提取 query，调用 RAG 两阶段检索服务
    （向量检索 + 关键词检索 → Reranker 精排 → Top-3）。
    """
    messages = state["messages"]
    if not messages:
        logger.warning("rag_retriever: 空消息列表")
        return {"rag_context": []}

    last_message = messages[-1]
    raw_query = last_message.content if hasattr(last_message, "content") else str(last_message)
    query = str(raw_query) if not isinstance(raw_query, str) else raw_query
    tenant_id = state.get("tenant_id", "")

    logger.info("rag_retriever.searching", query=query[:100], tenant_id=tenant_id)

    try:
        results = await retrieve_knowledge(
            query=query,
            tenant_id=tenant_id,
        )

        context_texts = [r["content"] for r in results if r.get("content")]

        logger.info(
            "rag_retriever.completed",
            num_results=len(context_texts),
            top_score=results[0].get("score", 0) if results else 0,
        )

        return {"rag_context": context_texts}

    except Exception as e:
        logger.error("rag_retriever.error", error=str(e))
        # RAG 失败不阻断对话，返回空上下文
        return {"rag_context": []}
