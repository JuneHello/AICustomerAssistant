"""LangGraph 状态机图定义 — Agent 核心编排

定义从用户输入到输出的完整节点图，包含：
- 输入安全检查 → 意图路由 → (条件分发)
- FAQ/商品 → RAG 检索 → 回复生成
- 订单/物流 → 工具执行 → 回复生成
- 退款 → 工具执行 → 人工中断 → 审批后处理 → 回复生成
- 转人工 → 转接处理
- 所有路径 → 输出安全检查 → 结束
"""

import structlog
from langgraph.graph import END, START, StateGraph

from agent.guardrails.input_guard import input_guardrails
from agent.guardrails.output_guard import output_guardrails
from agent.nodes.entity_extractor import entity_extractor
from agent.nodes.escalation_handler import escalation_handler
from agent.nodes.human_interrupt import human_interrupt
from agent.nodes.intent_router import intent_router
from agent.nodes.post_approval_handler import post_approval_handler
from agent.nodes.rag_retriever import rag_retriever
from agent.nodes.response_synthesizer import response_synthesizer
from agent.nodes.tool_executor import tool_executor
from agent.state import AgentState

logger = structlog.get_logger()


def _route_after_input_guard(state: AgentState) -> str:
    """输入安全检查后的路由：被拦截的直接结束，通过的进入意图路由。"""
    if state.get("intent") == "blocked":
        return "end"
    return "intent_router"


def _route_by_intent(state: AgentState) -> str:
    """根据意图分类结果分发到不同处理分支。"""
    intent = state.get("intent", "faq")

    if intent in ("faq",):
        return "rag_retriever"
    elif intent in ("order_query", "logistics_query", "refund_request"):
        return "entity_extractor"
    elif intent in ("human_request", "complaint"):
        return "escalation_handler"
    else:
        return "rag_retriever"  # 默认走 RAG


def _route_after_extraction(state: AgentState) -> str:
    """实体提取后的条件路由：根据意图流向对应的工具。"""
    intent = state.get("intent", "")
    if intent == "refund_request":
        return "tool_executor_refund"
    elif intent in ("order_query", "logistics_query"):
        return "tool_executor"
    return "response_synthesizer"


def _route_after_tool(state: AgentState) -> str:
    """工具执行后的路由：循环超限转人工，否则继续回复生成。"""
    if state.get("intent") == "human_request":
        return "escalation_handler"
    return "response_synthesizer"


def _route_after_refund_tool(state: AgentState) -> str:
    """退款工具执行后的路由。"""
    if state.get("intent") == "human_request":
        return "escalation_handler"
    return "human_interrupt"


def _route_after_approval(state: AgentState) -> str:
    """审批后处理的路由。"""
    if state.get("intent") == "human_request":
        return "escalation_handler"
    return "output_guardrails"


def build_graph() -> StateGraph:
    """构建 Agent 状态机图。"""

    graph = StateGraph(AgentState)

    # ── 注册节点 ──────────────────────────────────────────────
    graph.add_node("input_guardrails", input_guardrails)
    graph.add_node("intent_router", intent_router)
    graph.add_node("entity_extractor", entity_extractor)
    graph.add_node("rag_retriever", rag_retriever)
    graph.add_node("tool_executor", tool_executor)
    graph.add_node("tool_executor_refund", tool_executor)  # 复用同一函数
    graph.add_node("response_synthesizer", response_synthesizer)
    graph.add_node("human_interrupt", human_interrupt)
    graph.add_node("post_approval_handler", post_approval_handler)
    graph.add_node("escalation_handler", escalation_handler)
    graph.add_node("output_guardrails", output_guardrails)

    # ── 定义边 ────────────────────────────────────────────────

    # START → 输入安全检查
    graph.add_edge(START, "input_guardrails")

    # 输入安全检查 → 条件路由
    graph.add_conditional_edges(
        "input_guardrails",
        _route_after_input_guard,
        {
            "intent_router": "intent_router",
            "end": END,
        },
    )

    # 意图路由 → 条件分发
    graph.add_conditional_edges(
        "intent_router",
        _route_by_intent,
        {
            "rag_retriever": "rag_retriever",
            "entity_extractor": "entity_extractor",
            "escalation_handler": "escalation_handler",
        },
    )

    # 实体提取 → 条件分发到对应工具
    graph.add_conditional_edges(
        "entity_extractor",
        _route_after_extraction,
        {
            "tool_executor": "tool_executor",
            "tool_executor_refund": "tool_executor_refund",
            "response_synthesizer": "response_synthesizer",
        },
    )

    # RAG 检索 → 回复生成
    graph.add_edge("rag_retriever", "response_synthesizer")

    # 工具执行 → 条件路由（循环保护）
    graph.add_conditional_edges(
        "tool_executor",
        _route_after_tool,
        {
            "response_synthesizer": "response_synthesizer",
            "escalation_handler": "escalation_handler",
        },
    )

    # 退款工具执行 → 人工中断
    graph.add_conditional_edges(
        "tool_executor_refund",
        _route_after_refund_tool,
        {
            "human_interrupt": "human_interrupt",
            "escalation_handler": "escalation_handler",
        },
    )

    # 人工中断 → 审批后处理
    graph.add_edge("human_interrupt", "post_approval_handler")

    # 审批后处理 → 条件路由
    graph.add_conditional_edges(
        "post_approval_handler",
        _route_after_approval,
        {
            "output_guardrails": "output_guardrails",
            "escalation_handler": "escalation_handler",
        },
    )

    # 回复生成 → 输出安全检查
    graph.add_edge("response_synthesizer", "output_guardrails")

    # 输出安全检查 → 结束
    graph.add_edge("output_guardrails", END)

    # 转接处理 → 结束
    graph.add_edge("escalation_handler", END)

    return graph


def compile_agent_graph(checkpointer=None):
    """根据传入的 checkpointer 编译 Agent 状态机图。"""
    return build_graph().compile(checkpointer=checkpointer)

