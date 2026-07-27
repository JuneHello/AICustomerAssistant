"""动态 Prompt 装配器 — 灵魂与业务的解耦

将全局身份设定 (SOUL.md) 与当前意图的业务流程 (AGENTS.md) 以及 RAG 召回上下文，
动态地拼接组装成给 LLM 的 System Prompt。
"""

import os
from functools import lru_cache

import structlog

logger = structlog.get_logger()

# 基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOUL_PATH = os.path.join(BASE_DIR, "SOUL.md")
AGENTS_PATH = os.path.join(BASE_DIR, "AGENTS.md")


def load_markdown_file(file_path: str) -> str:
    """安全读取 Markdown 提示词文件。"""
    if not os.path.exists(file_path):
        logger.error("prompt_assembler.file_not_found", path=file_path)
        return ""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error("prompt_assembler.read_failed", path=file_path, error=str(e))
        return ""


@lru_cache(maxsize=1)
def get_soul() -> str:
    """获取并缓存 SOUL.md 人格设定。"""
    return load_markdown_file(SOUL_PATH)


@lru_cache(maxsize=1)
def get_agents_sop() -> str:
    """获取并缓存 AGENTS.md 业务规则。"""
    return load_markdown_file(AGENTS_PATH)


def extract_specific_sop(agents_content: str, intent: str) -> str:
    """根据意图类型，从完整的 SOP 文档中抽取特定小结，防止 Prompt 冗余。"""
    if not agents_content:
        return ""

    # 用简易标题解析逻辑提取小结
    sections = agents_content.split("## ")
    extracted_sections = []

    # 总是保留一级大标题
    if sections:
        extracted_sections.append(sections[0])

    target_keywords = []
    if intent == "refund_request":
        target_keywords = ["退款", "退换货", "SOP"]
    elif intent == "logistics_query":
        target_keywords = ["物流", "催单", "快递"]
    elif intent in ("faq", "product_query"):
        target_keywords = ["商品", "库存", "价格", "优惠券", "赔付"]
    else:
        target_keywords = ["退款", "物流", "优惠券"]

    for sec in sections[1:]:
        header_line = sec.split("\n")[0]
        if any(kw in header_line for kw in target_keywords):
            extracted_sections.append("## " + sec)

    return "\n".join(extracted_sections)


def assemble_prompt(
    intent: str,
    entities: dict,
    rag_context: list[str] | None = None,
    tool_outputs: list[dict] | None = None,
) -> str:
    """拼装 System Prompt。

    结构：
    1. SOUL.md - 全局人格与沟通语气
    2. 抽取的业务 SOP - 针对当前意图的业务细则
    3. 当前锁定的实体 (Entities Lock) - 辅助 LLM 进行逻辑判断，避免从摘要中提取
    4. 外部工具执行返回明细数据 (如有)
    5. RAG 召回的外部知识片段 (如有)
    """
    soul = get_soul()
    full_sop = get_agents_sop()
    specific_sop = extract_specific_sop(full_sop, intent)

    # 构造实体信息
    entities_str = ""
    if entities:
        entities_str = "\n### 当前会话锁定数据 (实体锁)\n"
        for k, v in entities.items():
            if v is not None:
                entities_str += f"- **{k}**: {v}\n"

    # 构造工具执行输出信息
    tool_outputs_str = ""
    if tool_outputs:
        import json
        tool_outputs_str = "\n### 外部工具执行返回明细数据 (已由系统核实为真实业务数据)\n"
        for i, output in enumerate(tool_outputs, 1):
            serialized = json.dumps(output, ensure_ascii=False)
            tool_outputs_str += f"- 记录 [{i}]: {serialized}\n"

    # 构造 RAG 知识库信息
    rag_str = ""
    if rag_context:
        rag_str = "\n### 召回的知识库参考资料 (仅能根据该资料回答咨询)\n"
        for i, doc in enumerate(rag_context, 1):
            rag_str += f"文献 [{i}]: {doc}\n\n"

    # 组装 System Prompt
    assembled = (
        "【全局客服人格与身份规范】\n"
        f"{soul}\n\n"
        "【当前业务操作规范 (SOP)】\n"
        f"{specific_sop}\n"
        f"{entities_str}"
        f"{tool_outputs_str}"
        f"{rag_str}\n"
        "请严格根据以上【业务操作规范】、【外部工具执行返回明细数据】和【召回的知识库参考资料】对用户进行回复。"
        "对于需要填写单据、查询数据的敏感意图，你必须参考已锁定的数据（如有）。"
        "如果召回资料不包含用户需要的信息，请向用户坦白表示不知道或委婉引导转人工客服，切勿编造虚假承诺、价格或政策。"
    )

    return assembled
