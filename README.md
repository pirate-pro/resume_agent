# Single Agent Runtime (Minimal)

最小可运行的单 Agent Runtime，基于 FastAPI + JSONL + Markdown + 本地文件目录。

## 功能

- `POST /api/chat`：单轮聊天入口（支持工具调用循环）
- `GET /api/sessions/{session_id}/events`：查看会话事件日志
- `GET /api/memories`：查看/检索 memory
- `GET /health`：健康检查

## 技术栈

- Python 3.12+
- FastAPI
- Pydantic v2 / pydantic-settings
- httpx
- pytest
- mypy

## 环境准备

```bash
cp .env.example .env
```

你给的测试模型配置已经兼容，支持以下变量：

- `VL_MODEL_NAME`
- `VL_MODEL_API_URL`
- `VL_MODEL_API_KEY`

同时也支持：

- `LLM_MODEL`
- `LLM_BASE_URL`
- `LLM_API_KEY`

## 启动

```bash
uv sync
uv run uvicorn app.main:app --reload --workers 1
```

## 测试

```bash
uv run pytest
uv run mypy
```

## 数据目录

运行后将生成：

```text
data/
├── sessions/
│   └── {session_id}/
│       ├── metadata.json
│       ├── events.jsonl
│       └── workspace/
└── memory/
    └── memories.jsonl
```
