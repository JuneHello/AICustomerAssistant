"""工具执行节点 — 三级错误处理的 Tool 调用引擎

Level 1 - 可重试 (5xx/Timeout): 指数退避重试 (最多 2 次)
Level 2 - 业务拒绝 (4xx): 不重试，翻译为用户可读文本
Level 3 - 不可恢复: 道歉 + 自动转人工，禁止 LLM 编造结果
"""

import inspect
import traceback

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agent.state import AgentState
from agent.tools.order_query import query_order
from agent.tools.logistics_query import query_logistics
from agent.tools.product_query import query_product
from agent.tools.refund_submit import submit_refund
from config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()

# 意图 → 工具映射
INTENT_TOOL_MAP = {
    "order_query": query_order,
    "logistics_query": query_logistics,
    "faq": query_product,  # 商品咨询类也可能需要查商品
    "refund_request": submit_refund,
}


class RetryableToolError(Exception):
    """Level 1: 可重试的工具错误 (5xx, Timeout)"""


class BusinessRejectionError(Exception):
    """Level 2: 业务逻辑拒绝 (4xx, 余额不足, 状态不允许)"""

    def __init__(self, user_message: str):
        self.user_message = user_message
        super().__init__(user_message)


class UnrecoverableToolError(Exception):
    """Level 3: 不可恢复错误 (服务宕机, 认证失效)"""


@retry(
    retry=retry_if_exception_type(RetryableToolError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=3),
    reraise=True,
)
async def _execute_with_retry(tool_func, **kwargs):
    """带指数退避重试的工具执行封装。"""
    return await tool_func.ainvoke(kwargs)


async def tool_executor(state: AgentState) -> dict:
    """工具执行节点。

    根据 state.intent 分发到对应工具。实现三级错误处理。
    循环保护：tool_call_count >= MAX_TOOL_ITERATIONS 时强制转人工。
    """
    intent = state.get("intent")
    tool_call_count = state.get("tool_call_count", 0)
    entities = state.get("entities", {})

    if not intent:
        return {"tool_call_count": tool_call_count}

    # 循环保护
    if tool_call_count >= settings.MAX_TOOL_ITERATIONS:
        logger.warning(
            "tool_executor.loop_detected",
            tool_call_count=tool_call_count,
            intent=intent,
        )
        return {
            "escalation_reason": f"tool_loop_exceeded_{tool_call_count}",
            "intent": "human_request",
            "tool_call_count": tool_call_count,
        }

    tool_func = INTENT_TOOL_MAP.get(intent)
    if not tool_func:
        logger.info("tool_executor.no_tool_for_intent", intent=intent)
        return {"tool_call_count": tool_call_count}

    logger.info(
        "tool_executor.executing",
        intent=intent,
        tool=tool_func.name,
        attempt=tool_call_count + 1,
    )

    try:
        # 1. 检查工具必填参数是否已在 entities 中提供
        underlying_func = getattr(tool_func, "func", None) or getattr(tool_func, "coroutine", None) or tool_func
        sig = inspect.signature(underlying_func)  # type: ignore[arg-type]
        missing_args = []
        for name, param in sig.parameters.items():
            if param.default is inspect.Parameter.empty and name not in ("kwargs", "args") and name not in entities:
                missing_args.append(name)
        
        if missing_args:
            arg_map = {
                "order_id": "订单号",
                "amount": "退款金额",
                "product_id": "商品ID",
                "tracking_number": "物流单号",
            }
            friendly_args = [arg_map.get(arg, arg) for arg in missing_args]
            raise BusinessRejectionError(f"缺少查询所需的必要信息：{', '.join(friendly_args)}。请提供这些信息以继续。")

        # 2. 执行工具
        tool_args = {
            **entities,
            "session_id": state.get("session_id"),
            "tenant_id": state.get("tenant_id"),
            "user_id": state.get("user_id"),
        }
        result = await _execute_with_retry(tool_func, **tool_args)

        logger.info(
            "tool_executor.success",
            tool=tool_func.name,
            result_keys=list(result.keys()) if isinstance(result, dict) else "raw",
        )

        # 3. 校验工具执行结果，如果是业务错误，主动抛出 BusinessRejectionError
        if isinstance(result, dict) and result.get("status") == "error":
            raise BusinessRejectionError(result.get("message", "工具执行发生业务错误"))

        # 工具输出清洗 — 保留精简摘要，防止上下文爆炸
        if isinstance(result, dict):
            cleaned = {
                "status": result.get("status", "success"),
                "data": result.get("data", result),
            }
        else:
            cleaned = {"status": "success", "data": str(result)[:500]}

        # 4. 合并工具返回的实体到 state.entities，并清除可能残留的 tool_error
        new_entities = {**entities}
        new_entities.pop("tool_error", None)
        if isinstance(result, dict):
            for key in ("order_id", "order_status", "tracking_number", "refund_id", "amount", "refund_reason"):
                if key in result and result[key] is not None:
                    new_entities[key] = result[key]

        # 5. 累加工具执行结果列表
        old_tool_outputs = state.get("tool_outputs") or []
        new_tool_outputs = old_tool_outputs + [cleaned]

        return {
            "entities": new_entities,
            "tool_call_count": tool_call_count + 1,
            "tool_outputs": new_tool_outputs,
        }

    except BusinessRejectionError as e:
        logger.info("tool_executor.business_rejection", message=e.user_message)
        return {
            "entities": {**entities, "tool_error": e.user_message},
            "tool_call_count": tool_call_count + 1,
        }

    except RetryableToolError:
        # 重试全部耗尽后到达此处 → 升级为 Level 3
        logger.error("tool_executor.retries_exhausted", tool=tool_func.name)
        return {
            "escalation_reason": f"tool_unrecoverable_{tool_func.name}",
            "intent": "human_request",
            "tool_call_count": tool_call_count + 1,
        }

    except Exception as e:
        # Level 3: 不可恢复
        traceback.print_exc()
        logger.error("tool_executor.unrecoverable", error=str(e), tool=tool_func.name)
        return {
            "escalation_reason": f"tool_unrecoverable_{tool_func.name}: {e}",
            "intent": "human_request",
            "tool_call_count": tool_call_count + 1,
        }
