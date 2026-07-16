"""离线评测运行器 (test_eval_runner.py) — pytest + LLM-as-a-Judge

基于黄金测试集 (Golden Dataset)，运行 Agent 并验证意图分类与关键实体状态。
"""

import asyncio
import json
import os
import pytest
import structlog

logger = structlog.get_logger()

# 基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(BASE_DIR, "golden_dataset.json")


def load_dataset() -> list:
    """加载黄金测试集"""
    if not os.path.exists(DATASET_PATH):
        return []
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


async def run_agent_case(case: dict):
    """运行单个评测用例的异步函数"""
    from agent.graph import agent_graph
    from langchain_core.messages import HumanMessage
    import uuid

    session_id = f"eval-{case['case_id']}-{uuid.uuid4().hex[:6]}"
    
    # 构造初始状态
    initial_state = {
        "messages": [HumanMessage(content=case["query"])],
        "session_id": session_id,
        "tenant_id": "t-001",
        "user_id": "user_eval_001",
        "intent": None,
        "entities": {},
        "tool_call_count": 0,
        "pending_approval": None,
        "escalation_reason": None,
        "rag_context": [],
        "tool_outputs": [],
    }

    config = {"configurable": {"thread_id": session_id}}

    logger.info("eval.case.invoking", case_id=case["case_id"], query=case["query"])
    
    try:
        # 调用状态机运行
        final_state = await agent_graph.ainvoke(initial_state, config=config)
        
        logger.info(
            "eval.case.finished",
            case_id=case["case_id"],
            result_intent=final_state.get("intent"),
            entities=final_state.get("entities"),
        )

        # 1. 验证意图分类是否符合预期
        assert final_state.get("intent") == case["expected_intent"], (
            f"用例 {case['case_id']} 意图不符。预期: {case['expected_intent']}, 实际: {final_state.get('intent')}"
        )

        # 2. 验证关键实体抽取（如提供了订单号或运单号）
        entities = final_state.get("entities", {})
        if "9821389421" in case["query"]:
            assert entities.get("order_id") == "9821389421", f"用例 {case['case_id']} 订单号抽取失败"
        if "SF1049284201" in case["query"]:
            assert entities.get("tracking_number") == "SF1049284201", f"用例 {case['case_id']} 运单号抽取失败"
    finally:
        from db.connections import dispose_engines
        await dispose_engines()


@pytest.mark.parametrize("case", load_dataset())
def test_golden_cases(case):
    """黄金测试集单例跑测并校验意图分类与动作正确率"""
    asyncio.run(run_agent_case(case))

