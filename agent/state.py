"""LangGraph 状态机 Schema 定义

Agent 运行时状态由 langgraph-checkpoint-postgres 自动持久化到 PostgreSQL，
通过 thread_id 关联到 sessions 表，无需手动序列化。
"""

from typing import TypedDict, Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Agent 运行时状态 Schema。

    优化点：
    - 使用明确的 BaseMessage 强类型约束，提升 IDE 补全与运行期安全。
    - entities 和 pending_approval 的内部结构必须采用 JSON 可序列化的
      Python 基础类型 (str, int, float, bool, None, list, dict)，
      避免 langgraph-checkpoint-postgres 在序列化时抛出 TypeError 异常。
    """

    # 对话历史 — add_messages reducer 自动追加新消息
    messages: Annotated[list[BaseMessage], add_messages]

    # 会话元数据
    session_id: str
    tenant_id: str
    user_id: str

    # 意图分类结果
    intent: str | None

    # 实体锁 — 结构化提取的关键业务实体
    # 示例: {"order_id": "9821389421", "amount": 299.0, "product_name": "..."}
    entities: dict

    # 工具调用循环计数器 — 同一交互内 >= MAX_TOOL_ITERATIONS 时强制转人工
    tool_call_count: int

    # 挂起的审批单 — human_interrupt 节点填充，审批完成后清空
    # 示例: {"refund_id": "RF-xxx", "order_id": "...", "amount": 299.0}
    pending_approval: dict | None

    # 转人工原因 — escalation_handler 节点使用
    escalation_reason: str | None

    # RAG 召回的知识片段
    rag_context: list[str]
