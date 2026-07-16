"""Pytest 共享测试夹具 (conftest.py)"""

import pytest
from fastapi.testclient import TestClient

from api.app import app


@pytest.fixture
def client():
    """FastAPI TestClient"""
    return TestClient(app)


@pytest.fixture
def mock_jwt_headers():
    """Mock 认证请求头，跳过 JWT 验证"""
    return {"Authorization": "mock_admin_token", "X-Tenant-ID": "t-001"}
