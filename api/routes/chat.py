"""聊天路由端点 (chat.py) — 接受用户输入并通过 SSE 提供流式应答

包含关键的 SSE 内存泄漏保护，客户端退出时优雅注销 Redis Pub/Sub。
"""

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent.state import AgentState
from api.middleware.auth import UserContext, verify_jwt_token
from core.dependencies import container

router = APIRouter()
logger = structlog.get_logger()


class SendMessageRequest(BaseModel):
    """发送消息请求体"""
    content: str
    session_id: str


@router.post("/send")
async def send_message(
    body: SendMessageRequest,
    context: UserContext = Depends(verify_jwt_token),
):
    """同步发送消息接口。主要用于非流式测试或意图激活。"""
    logger.info("chat.send", session_id=body.session_id, user_id=context.user_id)

    # 0. 检查该会话是否已被人工接管
    redis_client = container.cache_redis.client
    if redis_client:
        takeover_flag = await redis_client.get(f"takeover:{body.session_id}")
        if takeover_flag:
            return {
                "status": "takeover",
                "reply": "当前会话已由人工客服接管，请在人工客服窗口继续沟通。",
            }

    # 1. 组装输入状态
    initial_state: AgentState = {
        "messages": [HumanMessage(content=body.content)],
        "session_id": body.session_id,
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
    config: RunnableConfig = {"configurable": {"thread_id": body.session_id}}

    try:
        graph = container.agent_graph
        if graph is None:
            raise RuntimeError("Agent 图尚未初始化，请检查应用启动流程")
        final_state = await graph.ainvoke(initial_state, config=config)

        # 3. 提取最后一条 AI 回复并推送给 Redis Pub/Sub (广播到流通道)
        last_msg = final_state["messages"][-1]
        reply_text = last_msg.content

        if redis_client:
            await redis_client.publish(
                f"session:{body.session_id}",
                json.dumps({"event": "message", "data": reply_text}, ensure_ascii=False),
            )

        return {"status": "success", "reply": reply_text}

    except Exception as e:
        logger.error("chat.send_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent 处理异常，请稍后重试",
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
        redis_client = container.cache_redis.client
        if not redis_client:
            raise RuntimeError("Redis 客户端未初始化")
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
                    payload = json.loads(message["data"])
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
