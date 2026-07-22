import asyncio
import traceback
from sqlalchemy import select

def test_tool_debug():
    """单元测试内的调试函数，运行数据库查询并输出现有租户和会话 ID 详情。"""
    async def run_debug():
        from core.dependencies import container
        from db.pg_models import Tenant, Session
        try:
            await container.initialize()
            print("\n" + "="*40)
            print("[DEBUG] Querying tenants and sessions from Pg...")
            async with container.db_postgres.session() as session:
                try:
                    # 查询 tenants
                    stmt_t = select(Tenant)
                    res_t = await session.execute(stmt_t)
                    tenants = res_t.scalars().all()
                    print(f"[DEBUG] Found {len(tenants)} tenants:")
                    for t in tenants:
                        print(f"  - Tenant ID: {t.id} (Type: {type(t.id)}), Name: {t.name}")
                    
                    # 查询 sessions
                    stmt_s = select(Session).limit(5)
                    res_s = await session.execute(stmt_s)
                    sessions = res_s.scalars().all()
                    print(f"[DEBUG] Found {len(sessions)} sessions (showing top 5):")
                    for s in sessions:
                        print(f"  - Session ID: {s.id} (Type: {type(s.id)}), Tenant ID: {s.tenant_id}")
                except Exception as e:
                    print("[DEBUG] Query failed:")
                    traceback.print_exc()
                    raise e
            print("="*40)
        finally:
            await container.close()

    asyncio.run(run_debug())
