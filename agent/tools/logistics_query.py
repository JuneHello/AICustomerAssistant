"""物流查询工具 (agent/tools/logistics_query.py)"""

from langchain_core.tools import tool

from core.dependencies import container


@tool
async def query_logistics(order_id: str) -> dict:
    """查询物流信息。

    Args:
        order_id: 关联订单号

    Returns:
        包含物流状态、运单号、预计送达时间的字典
    """
    return await container.order_service.get_logistics(order_id=order_id)
