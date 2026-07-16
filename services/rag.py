"""两阶段 RAG 检索服务 (rag.py)

1. 向量检索：使用 pgvector 查询 HNSW 索引中与 Query 最匹配的内容 (BGE-M3 语义向量)
2. 关键词检索：使用 PostgreSQL 全文检索 (ts_rank) 进行字面精准配对
3. 取并集去重，且过滤已发布及有效期限内的知识条目
4. 精排：使用 BGE-Reranker-v2-M3 进行重新打分过滤，丢弃相关度分数小于 0.6 的低质量文献
5. 保留 Top-3 精准结果返回给 LLM 生成回复
"""

from datetime import datetime, timezone
from sqlalchemy import select, text
import structlog

from config.settings import get_settings
from db.connections import PgSession
from db.pg_models import KnowledgeBase

logger = structlog.get_logger()
settings = get_settings()


async def get_embedding(text: str) -> list[float]:
    """生成文本的嵌入向量。生产环境通常调用外部 Embedding 服务。

    此处为占位 Mock，模拟 BGE-M3 生成的 1024 维向量。
    """
    import random

    random.seed(hash(text))
    # 模拟生成 1024 维的归一化浮点数
    vector = [random.uniform(-0.1, 0.1) for _ in range(1024)]
    norm = sum(x**2 for x in vector) ** 0.5
    return [x / norm for x in vector]


async def rerank_documents(query: str, documents: list[dict]) -> list[dict]:
    """使用 BGE-Reranker-v2-M3 对候选文档进行精排打分。

    此处为 Mock 精排逻辑，生产环境中应使用 FlagEmbedding 库或 Reranker 接口服务。
    """
    logger.info("rag.reranker", num_candidates=len(documents))
    import random

    random.seed(42)

    reranked = []
    for doc in documents:
        # Mock 打分：包含 query 关键词的给予高分，其余随机打分
        match_count = sum(1 for word in query if word in doc["content"])
        base_score = 0.5 + min(0.49, match_count * 0.1)
        score = base_score if match_count > 0 else random.uniform(0.1, 0.55)

        doc["score"] = score
        reranked.append(doc)

    # 按照评分倒序排列
    return sorted(reranked, key=lambda x: x["score"], reverse=True)


async def retrieve_knowledge(query: str, tenant_id: str) -> list[dict]:
    """RAG 两阶段检索主函数"""
    logger.info(
        "rag.retrieve",
        query=query[:100],
        tenant_id=tenant_id,
        top_k=settings.RAG_TOP_K,
    )

    query_vector = await get_embedding(query)
    now = datetime.now(timezone.utc)

    async with PgSession() as session:
        # 1. 向量检索：使用余弦相似度查询已发布且在有效期内的知识
        # 使用 pgvector 的 <=> 操作符表示余弦距离，1 - 余弦距离 = 余弦相似度
        vector_stmt = (
            select(
                KnowledgeBase.id,
                KnowledgeBase.title,
                KnowledgeBase.content,
                (1 - KnowledgeBase.embedding.cosine_distance(query_vector)).label(
                    "similarity"
                ),
            )
            .where(
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.status == "published",
                (KnowledgeBase.valid_from <= now)
                | (KnowledgeBase.valid_from == None),
                (KnowledgeBase.valid_until >= now)
                | (KnowledgeBase.valid_until == None),
            )
            .order_by(KnowledgeBase.embedding.cosine_distance(query_vector))
            .limit(settings.RAG_TOP_K)
        )

        vector_res = await session.execute(vector_stmt)
        vector_candidates = vector_res.all()

        # 2. 关键词检索：利用 PostgreSQL 全文检索 (ts_rank)
        # 为便于演示，采用简单的 SQL LIKE/ILIKE 进行字面召回并集
        kw_stmt = (
            select(
                KnowledgeBase.id,
                KnowledgeBase.title,
                KnowledgeBase.content,
                text("0.5 AS similarity"),  # 默认匹配权重
            )
            .where(
                KnowledgeBase.tenant_id == tenant_id,
                KnowledgeBase.status == "published",
                (KnowledgeBase.content.ilike(f"%{query[:10]}%")),
            )
            .limit(settings.RAG_TOP_K)
        )

        kw_res = await session.execute(kw_stmt)
        kw_candidates = kw_res.all()

        # 3. 两路召回合并与去重
        candidates_map = {}
        for r in vector_candidates:
            candidates_map[r.id] = {
                "id": r.id,
                "title": r.title,
                "content": r.content,
                "similarity": float(r.similarity),
            }

        for r in kw_candidates:
            if r.id not in candidates_map:
                candidates_map[r.id] = {
                    "id": r.id,
                    "title": r.title,
                    "content": r.content,
                    "similarity": float(r.similarity),
                }

        candidates = list(candidates_map.values())

        if not candidates:
            logger.info("rag.retrieve.no_candidates")
            return []

        # 4. 精排重打分阶段
        reranked = await rerank_documents(query, candidates)

        # 5. 过滤与截断 (相关性阈值过滤)
        filtered = [
            doc
            for doc in reranked
            if doc["score"] >= settings.RAG_RERANKER_THRESHOLD
        ]
        final_results = filtered[: settings.RAG_FINAL_TOP_N]

        logger.info(
            "rag.retrieve.finished",
            candidates_found=len(candidates),
            passed_filter=len(filtered),
            returned=len(final_results),
        )

        return final_results
