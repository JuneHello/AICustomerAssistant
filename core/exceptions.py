"""统一领域与 API 业务异常定义 (core/exceptions.py)"""

from typing import Any, Optional


class AppException(Exception):
    """全局应用异常基类"""

    def __init__(
        self,
        message: str,
        code: int = 50000,
        status_code: int = 500,
        details: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class EntityNotFoundException(AppException):
    """实体未找到异常 (404)"""

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message=message, code=40400, status_code=404, details=details)


class BadRequestException(AppException):
    """客户端无效请求参数异常 (400)"""

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message=message, code=40000, status_code=400, details=details)


class ConflictException(AppException):
    """业务逻辑或状态冲突异常 (409)"""

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message=message, code=40900, status_code=409, details=details)


class SecurityBlockException(AppException):
    """安全护栏越权或阻断拦截异常 (403)"""

    def __init__(self, message: str, details: Optional[Any] = None) -> None:
        super().__init__(message=message, code=40300, status_code=403, details=details)
