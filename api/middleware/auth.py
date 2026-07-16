"""JWT 身份验证中间件 — 提供租户与用户身份校验"""

from datetime import datetime, timezone
from fastapi import Header, HTTPException, status
import jwt
import structlog

from config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


class UserContext:
    """认证通过的用户上下文信息"""

    def __init__(self, user_id: str, tenant_id: str):
        self.user_id = user_id
        self.tenant_id = tenant_id


async def verify_jwt_token(
    authorization: str = Header(None, alias="Authorization")
) -> UserContext:
    """FastAPI 依赖项：验证 JWT token 并提取身份。

    如果 Authorization 头缺失或非法，抛出 401 异常。
    在开发/测试环境下支持跳过验证。
    """
    # 允许开发环境下使用 Mock 头
    if settings.APP_ENV == "development" and authorization == "mock_admin_token":
        return UserContext(user_id="admin_user_001", tenant_id="t-001")

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing",
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be in 'Bearer <Token>' format",
        )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )

        user_id = payload.get("sub")
        tenant_id = payload.get("tenant_id")
        exp = payload.get("exp")

        if not user_id or not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )

        # 检查是否过期
        if exp and datetime.now(timezone.utc).timestamp() > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
            )

        return UserContext(user_id=user_id, tenant_id=tenant_id)

    except jwt.PyJWTError as e:
        logger.warning("auth.invalid_token", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )
