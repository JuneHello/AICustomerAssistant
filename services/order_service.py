"""订单、商品与物流处理领域服务 (services/order_service.py)"""

from __future__ import annotations

from typing import Any, Optional
import structlog
from sqlalchemy import select

from db.mysql import MySQLDatabase
from db.mysql_models import Order, Product

logger = structlog.get_logger()


class OrderService:
    """订单与商品业务领域服务"""

    def __init__(self, db_mysql: MySQLDatabase) -> None:
        self.db_mysql = db_mysql

    async def get_product(
        self, product_id: Optional[str] = None, keyword: Optional[str] = None
    ) -> dict[str, Any]:
        """查询商品详情（包含关联库存）。"""
        logger.info("order_service.get_product", product_id=product_id, keyword=keyword)
        from db.mysql_models import Inventory, Product

        async with self.db_mysql.session() as session:
            stmt = (
                select(Product, Inventory.available_stock)
                .outerjoin(Inventory, Product.id == Inventory.product_id)
            )

            if product_id:
                stmt = stmt.where(
                    Product.id == int(product_id)
                    if isinstance(product_id, str) and product_id.isdigit()
                    else Product.id == product_id
                )
            elif keyword:
                stmt = stmt.where(Product.name.ilike(f"%{keyword}%")).limit(5)
            else:
                return {"status": "error", "message": "请提供商品ID或关键词"}

            result = await session.execute(stmt)
            rows = result.all()

            if not rows:
                return {"status": "not_found", "message": "未找到相关商品"}

            if product_id:
                p, stock_val = rows[0]
                return {
                    "status": "success",
                    "product": {
                        "id": str(p.id),
                        "name": p.name,
                        "price": float(p.price),
                        "stock": stock_val if stock_val is not None else 99,
                        "description": p.description,
                    },
                }

            return {
                "status": "success",
                "products": [
                    {
                        "id": str(p.id),
                        "name": p.name,
                        "price": float(p.price),
                        "stock": stock_val if stock_val is not None else 99,
                    }
                    for p, stock_val in rows
                ],
            }

    async def get_order(
        self, order_id: Optional[str] = None, user_id: Optional[str] = None
    ) -> dict[str, Any]:
        """查询订单详情。"""
        logger.info("order_service.get_order", order_id=order_id, user_id=user_id)
        async with self.db_mysql.session() as session:
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

            if order_id:
                o = orders[0]
                return {
                    "status": "success",
                    "order": {
                        "order_id": o.order_no,
                        "status": o.status.value if hasattr(o.status, 'value') else o.status,
                        "total_amount": float(o.total_amount),
                        "created_at": o.created_at.isoformat() if o.created_at else None,
                    },
                }

            return {
                "status": "success",
                "orders": [
                    {
                        "order_id": o.order_no,
                        "status": o.status.value if hasattr(o.status, 'value') else o.status,
                        "total_amount": float(o.total_amount),
                    }
                    for o in orders
                ],
            }

    async def get_logistics(self, order_id: str) -> dict[str, Any]:
        """查询物流轨迹信息。"""
        logger.info("order_service.get_logistics", order_id=order_id)
        if not order_id:
            return {"status": "error", "message": "请提供订单号"}

        async with self.db_mysql.session() as session:
            stmt = select(Order).where(Order.order_no == order_id)
            result = await session.execute(stmt)
            order = result.scalar_one_or_none()

            if not order:
                return {"status": "not_found", "message": f"未找到订单 {order_id}"}

            return {
                "status": "success",
                "logistics": {
                    "order_id": order.order_no,
                    "tracking_number": f"SF{order.order_no[-8:]}",
                    "company": "顺丰速运",
                    "logistics_status": "运输中" if order.status in ("paid", "shipped") else "待发货",
                    "current_location": "上海转运中心",
                    "estimated_delivery": "预计明日 18:00 前送达",
                },
            }
