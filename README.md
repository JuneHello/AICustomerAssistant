# AI Customer Assistant · 智能客服助手

> 基于 LangGraph + DeepSeek 构建的多租户电商智能客服系统

---

## ✨ 技术栈

| 层级       | 技术选型                                                       |
| ---------- | -------------------------------------------------------------- |
| **LLM**    | DeepSeek-V3（主力） / DeepSeek-V2-Lite（降级兜底），LiteLLM 路由 |
| **Agent**  | LangGraph 状态机编排，支持 Tool Calling / RAG / 多轮对话       |
| **API**    | FastAPI + SSE 流式推送                                         |
| **存储**   | PostgreSQL 16（pgvector 向量检索）+ MySQL（电商业务只读）      |
| **缓存**   | Redis 7（会话缓存 / Celery Broker）                            |
| **异步任务** | Celery Worker（退款审批等长耗时任务）                         |
| **可观测** | Langfuse 2（Trace / Prompt 管理）+ Prometheus 指标              |
| **部署**   | Docker Compose 一键编排                                        |

---

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone <repo-url>
cd AICustomerAssistant
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填写实际的 API Key、数据库密码等
```

### 3. 启动服务

```bash
docker compose up -d
```

服务启动后：

- **API 服务**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs
- **Langfuse**: http://localhost:3000

### 4. 数据库迁移

```bash
# 进入容器执行迁移
docker compose exec app alembic upgrade head
```

### 5. 本地开发（不使用 Docker）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动开发服务器
uvicorn api.app:app --reload --port 8000
```

---

## 📂 项目结构

```
AICustomerAssistant/
├── api/                    # FastAPI 路由与中间件
│   ├── app.py              # 应用入口
│   ├── routes/             # 路由模块
│   └── middleware/         # JWT 认证、限流等中间件
├── agent/                  # LangGraph Agent 核心逻辑
│   ├── graph.py            # 状态机定义
│   ├── nodes/              # Agent 节点（Router / Tool / RAG）
│   └── tools/              # 工具函数（订单查询、退款等）
├── config/                 # 配置管理
│   ├── settings.py         # Pydantic Settings
│   └── litellm_config.yaml # LiteLLM 路由配置
├── db/                     # 数据库层
│   ├── connections.py      # 双数据源异步引擎
│   ├── pg_models.py        # PostgreSQL ORM 模型
│   ├── mysql_models.py     # MySQL 只读 ORM 模型
│   └── migrations/         # Alembic 迁移脚本
├── rag/                    # RAG 检索与重排序
├── workers/                # Celery 异步任务
├── docker-compose.yml      # 容器编排
├── Dockerfile              # 多阶段构建
├── requirements.txt        # Python 依赖
├── alembic.ini             # Alembic 配置
└── README.md               # 项目说明
```

---

## 🔧 核心能力

- **多轮对话**：基于 LangGraph 状态机的对话管理，支持上下文压缩与 Token 预算控制
- **RAG 检索增强**：pgvector 向量检索 + BGE Reranker 精排，提供精准知识库问答
- **工具调用**：订单查询、物流追踪、退款申请等结构化工具，安全沙箱执行
- **多租户隔离**：租户级别的知识库、会话、配置完全隔离
- **Saga 事务**：退款等跨系统操作采用 Saga 模式，支持补偿回滚
- **可观测性**：全链路 Trace 接入 Langfuse，关键指标暴露 Prometheus

---

## 📄 许可证

MIT License
