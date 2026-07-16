"""测试 AgentState 状态规范与边界验证"""

from langchain_core.messages import HumanMessage, AIMessage

from agent.state import AgentState


def test_agent_state_keys():
    """验证 AgentState 字段属性"""
    state = AgentState(
        messages=[HumanMessage(content="Hello")],
        session_id="session-1",
        tenant_id="t-1",
        user_id="u-1",
        intent=None,
        entities={"order_id": "123456789"},
        tool_call_count=0,
        pending_approval=None,
        escalation_reason=None,
        rag_context=[],
    )

    assert len(state["messages"]) == 1
    assert state["session_id"] == "session-1"
    assert state["entities"]["order_id"] == "123456789"
    assert state["tool_call_count"] == 0
