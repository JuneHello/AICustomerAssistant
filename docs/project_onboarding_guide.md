# AI Customer Assistant · 新人开发者入门与代码架构指南

本指南专为新接手 **AI Customer Assistant** 项目的开发者设计，旨在帮助您快速理清项目的双数据源设计、LangGraph 状态机决策链以及核心研发规范。

---

## 1. 项目物理架构 (Double-DB Topology)

本项目采用**双数据源**设计，隔离了**商城业务数据**与**智能客服内部状态**，确保在线业务库的高安全性。

```
                       ┌─────────────────────────┐
                       │      Client / User      │
                       └────────────┬────────────┘
                                    │ HTTP / SSE
                       ┌────────────▼────────────┐
                       │     FastAPI Server      │
                       └────────────┬────────────┘
                                    │ LangGraph Workflow
                       ┌────────────▼────────────┐
                       │  Agent State Machine    │
                       └─────┬─────────────┬─────┘
                             │             │
        (Read-Only Query)    │             │  (State Checkpoints / Write)
 ┌───────────────────────────▼┐           ┌▼───────────────────────────┐
 │       MySQL Business DB    │           │     PostgreSQL DB          │
 │ ────────────────────────── │           │ ────────────────────────── │
 │  • orders (订单表)         │           │  • tenants (多租户配置)     │
 │  • products (商品表)       │           │  • sessions (会话表)        │
 │  • users (用户表)          │           │  • pending_refunds (审批)  │
 │  • inventories (库存表)    │           │  • checkpoint_writes (暂存) │
 └────────────────────────────┘           └────────────────────────────┘
```

* **MySQL (业务只读库)**：代表商城的在线生产数据库。智能助手可通过工具从中查询订单状态、物流详情、商品及库存，但**绝对不会直接写入任何数据**。
* **PostgreSQL (客服状态库)**：客服系统的内部存储。用于存储多租户隔离配置（tenants）、客服会话历史（sessions）、待审批退款单（pending_refunds）以及由 `langgraph-checkpoint-postgres` 自动记录的状态机检查点数据。

---

## 2. 状态机链路流程 (LangGraph Workflow)

智能客服的对话和任务分发中心定义在 [agent/graph.py](file:///Users/zhangfeng/backend/AICustomerAssistant/agent/graph.py)。用户消息的流转和状态扭转如下：

1. **`input_guardrails` (输入安全审查)**：
   - 检查消息长度上限。
   - 检测 Prompt 越狱攻击，拦截诸如 `"忽略之前的客服设定，从现在起你是..."` 的注入语句。如果触发拦截，将意图标为 `blocked`，直接跳到合成节点输出安全回复。
2. **`intent_router` (意图路由)**：
   - 分类消息为：`logistics_query`（物流查询）、`refund_request`（退款申请）、`faq`（知识库问答）、`human_request`（转人工）或 `chat`（普通闲聊）。
3. **前置处理节点 (分流)**：
   - **RAGRetriever 分流**：意图为 `faq` 时激活，通过向量与字面全文匹配检索 Postgres 知识库，提取上下文存入 `state.rag_context`。
   - **EntityExtractor 分流**：意图为业务指令时激活，使用 LLM 抽取出关键实体（如 `order_id`, `tracking_number`, `amount`），合并入 `state.entities`。
4. **`tool_executor` (工具调用器)**：
   - 利用 `inspect.signature` 内省目标工具的入参。
   - 若缺失必填参数（如退款时缺少订单号），不报错崩溃，而是抛出 `BusinessRejectionError` 并在 `state.entities` 挂载 `tool_error` 业务提示，通知合成节点向用户追问缺失信息。
   - 运行成功后，将返回的详情结构化写入 `state.tool_outputs`，闭环生成真实回答。
5. **`response_synthesizer` (回复组装器)**：
   - 读取 `state.tool_outputs` 或 `state.rag_context`，结合 [SOUL.md](file:///Users/zhangfeng/backend/AICustomerAssistant/prompts/SOUL.md) 官方人格，生成自然语言应答。
6. **`output_guardrails` (输出安全审查)**：
   - 拦截敏感词、竞品提及（如京东、拼多多）。
   - 在退款时效及金额方面，自动补全合规免责声明，保障商业安全。

---

## 3. 强类型状态 `AgentState` 与 Saga 审批事务

### 3.1 客服会话上下文定义 (`AgentState`)
所有运行状态均由 `langgraph-checkpoint-postgres` 自动序列化并存储在数据库中，其强类型 schema 定义在 [agent/state.py](file:///Users/zhangfeng/backend/AICustomerAssistant/agent/state.py)：
```python
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages] # 对话历史序列
    session_id: str             # 会话 ID (映射 pg sessions.id)
    tenant_id: str              # 租户 ID (映射 pg tenants.id)
    user_id: str                # 用户 ID (MySQL users.id 字符化)
    intent: str | None          # 当前分类意图
    entities: dict              # 结构化提取的关键业务实体
    tool_call_count: int        # 工具递归上限计数器
    pending_approval: dict | None # 挂起的审批数据
    escalation_reason: str | None # 转人工原因
    rag_context: list[str]      # RAG 召回的文本片段
    tool_outputs: list[dict]    # 数据库工具执行明细数据
```

### 3.2 退款 Saga 事务流程
为避免大模型失控直接触发退款接口，退款操作采用**人工二阶段确认 (Handoff & Resume)** 机制：
1. `submit_refund` 工具在 Postgres 中插入一条状态为 `pending` 的 `pending_refunds` 工单。
2. 状态机在 `human_interrupt` 节点触发 **LangGraph `interrupt` 中断信号挂起**，进程结束。
3. 外部管理后台（对应 API 路由 [admin.py](file:///Users/zhangfeng/backend/AICustomerAssistant/api/routes/admin.py)）通过后台管理终点 `/api/admin/approve/{refund_id}` 进行人工审批：
   - 修改数据库记录状态为 `approved`。
   - 调用 `agent_graph.ainvoke(Command(resume=resume_payload))` 唤醒原会话断点。
   - 状态机被唤醒，执行下半场逻辑（向用户播报退款成功并更新状态），形成完整的 Saga 事务。

---

## 4. 类型安全与开发规范建议 (Mypy & Pytest)

近期重构优化解决了系统在运行期的不稳定隐患，在新增功能时请务必遵循以下规范：

1. **多模态消息兼容**：
   - 提取用户消息内容时，由于 LangChain 消息 content 可能是多模态列表，必须做字符串类型强转：
     `content = str(raw_content) if not isinstance(raw_content, str) else raw_content`。
2. **UUID 兼容防御**：
   - 电商表结构对 `tenant_id` 和 `session_id` 采用了 PostgreSQL UUID 外键约束，但测试集传入的常常是 `"t-001"` 等非标准格式字符串。
   - 代码中应使用 `uuid.uuid5(uuid.NAMESPACE_DNS, raw_str)` 进行确定性的哈希映射，既能通过 Postgres 数据库类型校验，又能保证在同个租户会话下的数据完整性。
3. **连接池清理**：
   - 在 pytest 的异步用例 `finally` 清理阶段，必须调用 `await dispose_engines()` 以释放 SQLAlchemy 的全局连接池，否则在多事件循环（Event Loop）环境下会引发 `RuntimeError: Event loop is closed`。

---

## 5. 本地命令参考

在开发过程中，您可以通过以下两条指令确保代码合规：

```bash
# 1. 全量静态类型校验 (无警告通过)
/opt/anaconda3/envs/ai-customer-assistant/bin/mypy --ignore-missing-imports agent/ config/ db/ api/ services/

# 2. 运行自动化测试与 E2E 黄金用例跑测 (100% 通关)
/opt/anaconda3/envs/ai-customer-assistant/bin/python -m pytest tests/
```
