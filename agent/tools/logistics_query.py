"""物流查询工具 — 从 MySQL 业务库查询物流状态"""

from langchain_core.tools import tool
import structlog

logger = structlog.get_logger()


@tool
async def query_logistics(order_id: str, **kwargs) -> dict:
    """查询订单物流信息。

    Args:
        order_id: 订单号

    Returns:
        包含物流状态、运单号、预计送达时间的字典
    """
    from sqlalchemy import select
    from db.connections import MysqlSession
    from db.mysql_models import Order

    logger.info("tool.query_logistics", order_id=order_id)

    if not order_id:
        return {"status": "error", "message": "请提供订单号"}

    async with MysqlSession() as session:
        stmt = select(Order).where(Order.order_no == order_id)
        result = await session.execute(stmt)
        order = result.scalar_one_or_none()

        if not order:
            return {"status": "not_found", "message": f"未找到订单 {order_id}"}

        status = order.status.value if hasattr(order.status, "value") else str(order.status)

        logistics_info = {
            "status": "success",
            "order_id": order_id,
            "order_status": status,
            "tracking_number": getattr(order, "tracking_number", None),
            "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
            "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        }

        # 根据订单状态生成物流描述
        if status == "pending":
            logistics_info["description"] = "订单待发货，商家正在处理中"
        elif status == "shipped":
            logistics_info["description"] = "包裹已发出，正在配送中"
        elif status == "delivered":
            logistics_info["description"] = "包裹已签收"
        elif status == "cancelled":
            logistics_info["description"] = "订单已取消"
        else:
            logistics_info["description"] = f"当前状态: {status}"

        return logistics_info
