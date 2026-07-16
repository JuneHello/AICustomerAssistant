"""商品查询工具 — 从 MySQL 业务库查询商品信息"""

from langchain_core.tools import tool
import structlog

logger = structlog.get_logger()


@tool
async def query_product(
    product_id: str = "",
    keyword: str = "",
    **kwargs,
) -> dict:
    """查询商品详情。支持按商品ID或关键词搜索。

    Args:
        product_id: 商品ID（精确查询）
        keyword: 搜索关键词（模糊查询）

    Returns:
        包含商品名称、价格、库存等信息的字典
    """
    from sqlalchemy import select
    from db.connections import MysqlSession
    from db.mysql_models import Product

    logger.info("tool.query_product", product_id=product_id, keyword=keyword)

    async with MysqlSession() as session:
        if product_id:
            stmt = select(Product).where(Product.id == int(product_id) if isinstance(product_id, str) and product_id.isdigit() else Product.id == product_id)
        elif keyword:
            stmt = (
                select(Product)
                .where(Product.name.contains(keyword))
                .limit(5)
            )
        else:
            return {"status": "error", "message": "请提供商品ID或搜索关键词"}

        result = await session.execute(stmt)
        products = result.scalars().all()

        if not products:
            return {"status": "not_found", "message": "未找到相关商品"}

        product_list = []
        for p in products:
            product_list.append({
                "product_id": str(p.id),
                "name": p.name,
                "price": float(p.price),
                "category": p.category,
                "stock": getattr(p, "stock", None),
            })

        return {
            "status": "success",
            "data": product_list[0] if product_id else product_list,
        }
