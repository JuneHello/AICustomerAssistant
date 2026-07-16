"""订单查询工具 — 从 MySQL 业务库只读查询订单信息"""

from langchain_core.tools import tool
import structlog

logger = structlog.get_logger()


@tool
async def query_order(
    order_id: str = "",
    user_id: str = "",
) -> dict:
    """查询订单详情。支持按订单号或用户ID查询。

    Args:
        order_id: 订单号（优先）
        user_id: 用户ID（查询该用户最近订单）

    Returns:
        包含订单状态、金额、时间等信息的字典
    """
    from sqlalchemy import select
    from db.connections import MysqlSession
    from db.mysql_models import Order

    logger.info("tool.query_order", order_id=order_id, user_id=user_id)

    async with MysqlSession() as session:
        if order_id:
            stmt = select(Order).where(Order.order_no == order_id)
        elif user_id:
            stmt = (
                select(Order)
                .where(Order.user_id == user_id)
                .order_by(Order.created_at.desc())
                .limit(5)
            )
        else:
            return {"status": "error", "message": "请提供订单号或用户ID"}

        result = await session.execute(stmt)
        orders = result.scalars().all()

        if not orders:
            return {"status": "not_found", "message": "未找到相关订单"}

        order_list = []
        for order in orders:
            order_list.append({
                "order_id": order.order_no,
                "user_id": order.user_id,
                "status": order.status.value if hasattr(order.status, "value") else str(order.status),
                "total_amount": float(order.total_amount),
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
                "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
            })

        return {
            "status": "success",
            "data": order_list[0] if order_id else order_list,
            "order_id": order_list[0]["order_id"] if order_list else None,
            "order_status": order_list[0]["status"] if order_list else None,
        }
