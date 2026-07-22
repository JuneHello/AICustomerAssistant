"""聊天路由端点 (chat.py) — 接受用户输入并通过 SSE 提供流式应答

包含关键的 SSE 内存泄漏保护，客户端退出时优雅注销 Redis Pub/Sub。
"""

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from langchain_core.messages import HumanMessage
from sse_starlette.sse import EventSourceResponse

from agent.graph import agent_graph
from api.middleware.auth import UserContext, verify_jwt_token
from db.connections import get_redis_client

router = APIRouter()
logger = structlog.get_logger()


@router.post("/send")
async def send_message(
    content: str,
    session_id: str,
    context: UserContext = Depends(verify_jwt_token),
):
    """同步发送消息接口。主要用于非流式测试或意图激活。"""
    logger.info("chat.send", session_id=session_id, user_id=context.user_id)

    # 1. 组装输入状态
    from agent.state import AgentState

    initial_state: AgentState = {
        "messages": [HumanMessage(content=content)],
        "session_id": session_id,
        "tenant_id": context.tenant_id,
        "user_id": context.user_id,
        "intent": None,
        "entities": {},
        "tool_call_count": 0,
        "pending_approval": None,
        "escalation_reason": None,
        "rag_context": [],
        "tool_outputs": [],
    }

    # 2. 运行状态机
    # thread_id 用于持久化 state checkpoint
    from langchain_core.runnables import RunnableConfig

    config: RunnableConfig = {"configurable": {"thread_id": session_id}}

    try:
        final_state = await agent_graph.ainvoke(initial_state, config=config)

        # 3. 提取最后一条 AI 回复并推送给 Redis Pub/Sub (广播到流通道)
        last_msg = final_state["messages"][-1]
        reply_text = last_msg.content

        redis_client = await get_redis_client()
        await redis_client.publish(
            f"session:{session_id}",
            json.dumps({"event": "message", "data": reply_text}, ensure_ascii=False),
        )

        return {"status": "success", "reply": reply_text}

    except Exception as e:
        logger.error("chat.send_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent runtime error: {e}",
        )


@router.get("/stream")
async def chat_stream(
    session_id: str = Query(..., description="会话ID"),
    context: UserContext = Depends(verify_jwt_token),
):
    """服务器发送事件 (SSE) 流式推送通道。

    优化点 (SSE 内存泄露防御代码实现)：
    - 订阅 Redis 中特定 session_id 的频道。
    - 使用 try...except asyncio.CancelledError...finally 捕获长连接的强行断开。
    - 无论发生何种断开（客户端关闭页面或断网），彻底执行 unsubscribe 并关闭连接，杜绝内存与句柄泄漏。
    """
    logger.info("chat.stream_connected", session_id=session_id)

    async def event_generator():
        redis_client = await get_redis_client()
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"session:{session_id}")

        try:
            # 发生长连接订阅时，发送建立成功的 ACK
            yield {
                "event": "connected",
                "data": json.dumps({"status": "established", "session_id": session_id}),
            }

            while True:
                # 定期无阻塞拉取消息
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    payload = json.loads(message["data"].decode("utf-8"))
                    yield {
                        "event": payload.get("event", "message"),
                        "data": payload.get("data", ""),
                    }
                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            # 客户端强行切断连接（如关闭页面）
            logger.info("chat.stream_disconnected_cancelled", session_id=session_id)

        except Exception as e:
            logger.error("chat.stream_error", session_id=session_id, error=str(e))

        finally:
            # 核心防漏：确保发生任何异常或取消时，退订频道并关闭 pubsub 连接
            logger.info("chat.stream_cleanup_connections", session_id=session_id)
            await pubsub.unsubscribe(f"session:{session_id}")
            await pubsub.close()

    return EventSourceResponse(event_generator())
