"""商品查询工具 (agent/tools/product_query.py)"""

from typing import Optional
from langchain_core.tools import tool

from core.dependencies import container


@tool
async def query_product(
    product_id: Optional[str] = None, keyword: Optional[str] = None
) -> dict:
    """查询商品详情。支持按商品ID或关键词搜索。

    Args:
        product_id: 商品ID（精确查询）
        keyword: 搜索关键词（模糊查询）

    Returns:
        包含商品名称、价格、库存等信息的字典
    """
    return await container.order_service.get_product(product_id=product_id, keyword=keyword)
