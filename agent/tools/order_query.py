"""订单查询工具 (agent/tools/order_query.py)"""

from typing import Optional
from langchain_core.tools import tool

from core.dependencies import container


@tool
async def query_order(
    order_id: Optional[str] = None, user_id: Optional[str] = None
) -> dict:
    """查询订单详情。支持按订单号或用户ID查询。

    Args:
        order_id: 订单号（优先）
        user_id: 用户ID（查询该用户最近订单）

    Returns:
        包含订单状态、金额、时间等信息的字典
    """
    return await container.order_service.get_order(order_id=order_id, user_id=user_id)
