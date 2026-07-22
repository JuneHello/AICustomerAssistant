"""业务数据传输对象 (DTO) (domain/schemas/dto.py)"""

from typing import Optional
from pydantic import BaseModel


class ProductDTO(BaseModel):
    """商品数据 DTO"""

    id: str
    name: str
    price: float
    stock: int
    category: Optional[str] = None
    description: Optional[str] = None


class OrderDTO(BaseModel):
    """订单数据 DTO"""

    id: str
    order_no: str
    user_id: str
    total_amount: float
    status: str
    created_at: Optional[str] = None


class LogisticsDTO(BaseModel):
    """物流信息 DTO"""

    order_no: str
    status: str
    tracking_number: Optional[str] = None
    logistics_company: Optional[str] = None
    estimated_delivery: Optional[str] = None


class RefundResultDTO(BaseModel):
    """退款申请结果 DTO"""

    status: str
    refund_id: str
    order_id: str
    amount: float
    message: str
    order_verified: bool = True
    eligibility_checked: bool = True
    refund_reason: Optional[str] = None
