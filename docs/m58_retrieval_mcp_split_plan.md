# M58 Retrieval MCP 拆分方案

> 状态：M58-A 文档已落地；M58-B facade 初版已落地；M58-C MCP server / stdio runner 初版已落地并通过 stdio smoke；M58-D Streamable HTTP runner 已通过 localhost smoke；M58-E 内部 Agent MCP proxy 初版已落地；M58-F 高并发 live smoke 已收敛。

## 目标

把当前和主服务进程绑在一起的 retrieval / RAG 能力，拆成可独立启动的 MCP server。

目标不是新增一套知识库，而是把已有召回能力对外暴露成 MCP：

```text
Career / Note / Knowledge / Learning / SessionArtifact
  -> RetrievalService
  -> MCP tools
  -> 外部 MCP client / 后续内部 MCP proxy
```

核心原则：

- `RetrievalService` 仍是统一召回入口。
- `RetrievalIndexStore` 仍是可重建 projection / cache。
- MCP server 只调用 service 层，不直接读写业务文件。
- 第一版 MCP 只读，不开放写入、删除、reindex。
- 不允许模型通过工具参数传 `session_id`、路径或 store 内部字段。

## 当前代码状态

当前 retrieval 已经具备 MCP 化的基础边界：

- `app/retrieval/models.py`
  - `RetrievalQuery`
  - `RetrievalHit`
  - `ContextPack`
  - `RetrievalSourceRef`
- `app/retrieval/service.py`
  - `RetrievalService.search()`
  - `RetrievalService.build_context_pack()`
- `app/tools/builtin_tools/retrieval.py`
  - `retrieval_search`
  - `retrieval_context_pack`
  - 当前工具已经拒绝 `path`、`file_path`、`workspace_path`、`session_id` 等不该由模型控制的字段。
- `app/api/dependencies/retrieval.py`
  - 组装 `RetrievalService`，依赖 Career / Note / Knowledge / Learning / Session / RetrievalIndex stores。

当前还没有：

- MCP SDK 依赖。
- 独立 MCP server 入口。
- MCP client/proxy 回接内部 `ToolRegistry`。
- MCP transport 配置。

## MCP 边界选择

MCP 官方能力模型里：

- `tools` 适合模型主动调用的动作，例如 search / build context pack。
- `resources` 适合 host/client 主动选择或读取的上下文。
- 本地集成优先 `stdio`。
- 独立 HTTP 服务使用 Streamable HTTP，并且需要 Origin 校验、localhost 绑定或认证。

因此第一版只做 tools：

```text
retrieval_search
retrieval_context_pack
```

暂不做 resources。

原因：

- 当前产品最需要的是“按 query 检索”和“组上下文包”。
- 现有内部工具名已经稳定，沿用 snake_case 可以减少迁移成本。
- resources 需要进一步设计 URI、权限、source 反查和展示策略，第一版不是必要条件。

后续可选 resources：

```text
retrieval://manifest
retrieval://source/{source_type}/{source_id}
retrieval://chunk/{chunk_id}
```

这些必须等 source 权限和敏感字段裁剪稳定后再开放。

## 目标架构

### 第一阶段：MCP adapter，不改主流程

```text
app/tools/builtin_tools/retrieval.py
  -> app/retrieval/facade.py
  -> RetrievalService

app/mcp/retrieval_server.py
  -> app/retrieval/facade.py
  -> RetrievalService
```

这一阶段主 Agent 仍然走原来的内置工具。

MCP server 作为独立入口启动，用来给外部 client 或本地 MCP Inspector 调用。

### 第二阶段：独立进程

```text
scripts/run_retrieval_mcp.py
  -> app/mcp/retrieval_server.py
  -> app/api/dependencies/retrieval.py
  -> DATA_DIR 下的现有 stores
```

主 FastAPI 服务和 MCP server 可以共享同一个 `DATA_DIR`。

共享文件 store 时，第一版只读，避免先引入写冲突。

### 第三阶段：内部 Agent 可选走 MCP proxy

```text
ToolRegistry
  -> McpToolProxy
  -> Retrieval MCP server
  -> RetrievalService
```

这一步不是第一版目标。

只有当外部 MCP server 稳定后，才考虑把内部 retrieval 工具也切到 MCP proxy。切换时必须保留当前 `ToolGateway`、ledger、workflow policy 和 agent tool surface 限制。

## 新增文件计划

建议新增：

```text
app/retrieval/facade.py
app/mcp/__init__.py
app/mcp/retrieval_server.py
scripts/run_retrieval_mcp.py
tests/test_retrieval_mcp_server.py
```

建议修改：

```text
pyproject.toml
app/tools/builtin_tools/retrieval.py
```

`pyproject.toml` 只加可选依赖：

```toml
[project.optional-dependencies]
mcp = [
  "mcp>=1,<2",
]
```

如果需要 MCP CLI / Inspector 辅助本地调试，再用：

```toml
mcp-dev = [
  "mcp[cli]>=1,<2",
]
```

不要把 MCP SDK 放进主 dependencies，避免主服务启动链路被 MCP 依赖影响。

## facade 设计

`app/retrieval/facade.py` 的职责是把“工具输入”和“retrieval service 调用”稳定下来。

它应该被内置工具和 MCP server 共同使用，避免两边各写一套校验。

建议结构：

```text
RetrievalToolInput
RetrievalPrincipal
build_retrieval_query()
retrieval_search_payload()
retrieval_context_pack_payload()
```

### RetrievalToolInput

允许字段保持和当前内置工具一致：

```text
query
source_types
related_application_id
top_k
max_chars
include_archived
```

继续拒绝：

```text
session_id
source_session_id
path
file_path
workspace_path
absolute_path
relative_path
created_at
updated_at
status
```

### RetrievalPrincipal

MCP 外部调用没有现成的 `RunContext`，所以需要服务端 principal。

建议字段：

```text
session_id: str | None
owner_user_id: str
workspace_id: str
```

第一版现有 store 还没有完整多用户权限体系，可以先使用默认值：

```text
owner_user_id = "user_local"
workspace_id = "workspace_default"
```

但 `session_id` 必须谨慎：

- 内部工具：继续从 `RunContext.session_id` 注入。
- MCP stdio：可以从启动环境或配置注入固定 app session。
- MCP HTTP：不能把 MCP transport 的 `Mcp-Session-Id` 当作 app `session_id`。
- 没有 app `session_id` 时，默认不召回 `session_artifact`。

这条是硬边界。`session_artifact` 是当前会话文件事实源，不能让模型自己声明属于哪个 session。

## MCP tools 契约

### retrieval_search

输入：

```json
{
  "query": "结合我之前的星河智能项目准备二面",
  "source_types": ["career", "notes", "knowledge"],
  "related_application_id": "application_xxx",
  "top_k": 8,
  "max_chars": 12000,
  "include_archived": false
}
```

输出：

```json
{
  "query": "...",
  "count": 3,
  "hits": [
    {
      "title": "...",
      "summary": "...",
      "snippet": "...",
      "score": 0.82,
      "match_reason": "...",
      "source": {
        "source_type": "job_fit_report",
        "source_id": "fit_xxx",
        "source_session_id": null,
        "artifact_id": null
      },
      "evidence_refs": []
    }
  ]
}
```

不返回本地文件路径。

### retrieval_context_pack

输入同 `retrieval_search`。

输出：

```json
{
  "query": "...",
  "count": 5,
  "context_char_count": 8400,
  "max_chars": 12000,
  "omitted_count": 2,
  "group_counts": {
    "career": 2,
    "notes": 1,
    "knowledge": 2,
    "learning": 0,
    "artifacts": 0
  },
  "context_pack": {
    "hits": [],
    "grouped_context": {},
    "citations": []
  }
}
```

输出结构应尽量复用 `ContextPack.to_payload()`。

## Transport 策略

### stdio

第一版默认支持。

用途：

- 本地 MCP client。
- MCP Inspector。
- 桌面 IDE / Agent host。

约束：

- stdout 只能输出 MCP JSON-RPC 消息。
- 普通日志写 stderr。
- 启动时通过环境变量或配置传 `DATA_DIR`。

### Streamable HTTP

第一版已支持 localhost 启动。

用途：

- 主服务进程以外的本地服务。
- 后续前后端或多 agent runtime 统一走 MCP endpoint。

约束：

- 默认绑定 `127.0.0.1`。
- 不能默认绑定 `0.0.0.0`。
- 校验 Origin。
- 有认证前不开放远程访问。
- 区分 MCP transport session 和 app session。

## 权限和安全边界

第一版必须满足：

- 只读。
- 不接受路径参数。
- 不接受 `session_id` 参数。
- 不返回绝对路径。
- 不开放 `RetrievalIndexStore.replace_source_chunks()`。
- 不开放 `RetrievalIndexStore.archive_source_chunks()`。
- 不开放 `RetrievalIndexer` 写入入口。
- 不读取 MCP client 提供的任意文件。

`include_archived=true` 仍可保留，但只表示允许读取已归档业务记录或索引 chunk，不表示越权读取。

如果没有 app session：

```text
source_types 为空：
  默认召回 career / notes / knowledge / learning / index 中非 session_only 内容

source_types 显式包含 artifacts / session_artifact：
  返回参数错误，或静默过滤 artifacts 并在 metadata 中说明 skipped_session_artifact=true
```

建议第一版采用参数错误，避免调用方误以为拿到了完整上下文。

## 实施拆分

### M58-A 文档

当前文档。

完成标准：

- 明确第一版 MCP 只读。
- 明确不新增知识库。
- 明确 session 边界。
- 明确文件计划和验收标准。

### M58-B facade

新增 `app/retrieval/facade.py`。

把当前 `app/tools/builtin_tools/retrieval.py` 里的输入校验、source type alias、payload 组装迁出来。

完成标准：

- 内置 `retrieval_search` 行为不变。
- 内置 `retrieval_context_pack` 行为不变。
- 现有 retrieval tests 通过。

### M58-C MCP server

新增 `app/mcp/retrieval_server.py` 和 `scripts/run_retrieval_mcp.py`。

完成标准：

- `uv run --extra mcp python scripts/run_retrieval_mcp.py --transport stdio` 可启动。
- MCP Inspector 能看到两个 tools。
- 两个 tools 能返回结构化 JSON。
- 无 app session 时不能读取 session artifact。

### M58-D HTTP transport

给 runner 增加 Streamable HTTP。

完成标准：

- 默认 host 为 `127.0.0.1`。
- 默认 path 为 `/mcp`。
- 明确 Origin / auth 配置。
- 没配置认证时拒绝非 localhost 场景。

验证状态：

- `scripts/run_retrieval_mcp.py --transport streamable-http --host 127.0.0.1 --port <free_port>` 可启动。
- MCP Python client `streamable_http_client("http://127.0.0.1:<free_port>/mcp")` 可 initialize / list_tools / call_tool。
- 已固化为 `tests/test_retrieval_mcp_server.py::test_retrieval_mcp_streamable_http_runner_smoke_uses_real_data_dir_layout`。

### M58-E 内部 proxy，可选

新增 `McpToolProxy`，让内部 Agent 可选通过 MCP 调 retrieval。

第一版落地为 retrieval 专用 MCP proxy，默认不开启。

启用方式：

```text
RETRIEVAL_TOOL_BACKEND=mcp
```

默认值：

```text
RETRIEVAL_TOOL_BACKEND=local
```

完成标准：

- `ToolRegistry` 仍按 agent 类型控制工具可见性。
- `RunContext.session_id` 仍由系统注入。
- workflow / gateway / ledger 行为不回退。
- 模型仍不能通过 tool 参数传 `session_id`。
- API registry 和 live smoke registry 使用同一套 retrieval tool backend 切换逻辑。

实现文件：

```text
app/tools/mcp_retrieval_proxy.py
app/tools/retrieval_registration.py
```

## 测试计划

### 单元测试

新增或调整：

```text
tests/test_retrieval_facade.py
tests/test_retrieval_mcp_server.py
```

覆盖：

- MCP tool 输入 schema。
- 不接受 `session_id`。
- 不接受路径字段。
- source type alias 仍可用。
- 无 app session 时拒绝 session artifact。
- payload 不包含文件路径。
- `retrieval_search` 和内置工具输出核心字段一致。
- `retrieval_context_pack` 和内置工具输出核心字段一致。

### 回归测试

继续运行现有：

```bash
.venv/bin/python -m pytest tests/test_retrieval_tools.py tests/test_retrieval_service.py tests/test_retrieval_index_search.py tests/test_retrieval_agent_flow.py
```

如果新增 MCP 依赖后本地环境未安装 extra，MCP 测试应使用 marker 或 import skip，不能影响默认测试集。

### 手动验收

本地检查：

```bash
uv run --extra mcp python scripts/run_retrieval_mcp.py --transport stdio
```

Inspector 检查：

```bash
npx @modelcontextprotocol/inspector \
  uv \
  --directory /home/ubunt/resume_agent \
  run \
  --extra mcp \
  python scripts/run_retrieval_mcp.py --transport stdio
```

## Smoke 验证记录

### stdio 外部进程

已用 MCP Python client 通过 stdio 拉起独立子进程：

```text
sys.executable scripts/run_retrieval_mcp.py --transport stdio
```

验证结果：

- `list_tools` 能看到 `retrieval_search` 和 `retrieval_context_pack`。
- 不传 `--app-session-id` 时，`retrieval_search` 能返回 Career / Note / Knowledge / Learning 等事实源命中。
- 不传 `--app-session-id` 时，显式请求 `session_artifact` 返回错误：`session_artifact retrieval requires an app session`。
- 传 `--app-session-id sess_alpha` 时，`retrieval_context_pack` 能返回当前 session 的 `artifact_alpha_jd`。
- MCP payload 不返回 `session_id`，不暴露本地路径。

该验证已固化为：

```text
tests/test_retrieval_mcp_server.py::test_retrieval_mcp_stdio_runner_smoke_uses_real_data_dir_layout
```

### Streamable HTTP 外部进程

已用 MCP Python client 通过 Streamable HTTP 连接独立子进程：

```text
sys.executable scripts/run_retrieval_mcp.py \
  --transport streamable-http \
  --host 127.0.0.1 \
  --port <free_port> \
  --app-session-id sess_alpha
```

验证结果：

- `initialize` 成功。
- `list_tools` 能看到 `retrieval_search` 和 `retrieval_context_pack`。
- `retrieval_search` 能返回真实 Career / Note / Knowledge / Learning 命中。
- `retrieval_context_pack` 能返回当前 session 的 `artifact_alpha_jd`。
- MCP payload 不返回 `session_id`，不暴露本地路径。
- 该 transport 默认 localhost；非 localhost 绑定仍需要显式 `--allow-remote`。

该验证已固化为：

```text
tests/test_retrieval_mcp_server.py::test_retrieval_mcp_streamable_http_runner_smoke_uses_real_data_dir_layout
```

### 内部 Agent MCP proxy

已通过 `RETRIEVAL_TOOL_BACKEND=mcp` 让内部 Agent 注册同名 retrieval proxy tools：

```text
retrieval_search
retrieval_context_pack
```

验证结果：

- 内部 proxy 仍由系统注入 `RunContext.session_id`。
- tool 参数仍拒绝 `session_id`。
- proxy payload 不返回 `session_id`，不暴露本地路径。
- live smoke 的 API registry 和脚本内 registry 都走同一套 `register_retrieval_tools()` backend 切换逻辑。
- `rag_read_only` 探针通过：`search=1`、`context_pack=1`、`budget_violations=0`。
- 高并发全量 live smoke（P0+P1，11 场景，并发 4）结果：10 过 1 失败；失败场景为 `rag_to_note`，失败点是前置 `career_resume_version_create` 首次生成无证据量化表述触发严格校验，retrieval proxy 本身无失败。
- `rag_to_note` 单场景复跑通过：`search=1`、`context_pack=1`、`budget_violations=0`。

验证命令：

```bash
RETRIEVAL_TOOL_BACKEND=mcp uv run --extra mcp python tools/smoke_live_matrix.py \
  --scenario rag_read_only \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m58e_proxy_probe \
  --json-report data/live_smoke_matrix_m58e_proxy_probe/report.json \
  --quiet

RETRIEVAL_TOOL_BACKEND=mcp uv run --extra mcp python tools/smoke_live_matrix.py \
  --all-p0 \
  --all-p1 \
  --runs 1 \
  --concurrency 4 \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m58e_mcp_full_c4 \
  --json-report data/live_smoke_matrix_m58e_mcp_full_c4/report.json \
  --quiet

RETRIEVAL_TOOL_BACKEND=mcp uv run --extra mcp python tools/smoke_live_matrix.py \
  --scenario rag_to_note \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m58e_mcp_rag_to_note_retry \
  --json-report data/live_smoke_matrix_m58e_mcp_rag_to_note_retry/report.json \
  --quiet
```

### M58-F 高并发 live smoke 收敛

M58-E 后继续收敛了两个和 MCP proxy 无关、但会影响全量验收稳定性的门禁问题：

- `tools/smoke_career_live_flow.py` 的效率统计区分 raw failed tool result、已恢复保护性失败、未恢复失败。
- `tools/smoke_live_matrix.py` 的 product stop-line 只把未恢复失败作为红线，已恢复的 `career_resume_version_create` 保护性拒绝保留为 warning。
- `FINALIZATION_PACKET` / final-answer recovery prompt 增加更硬的 grounding 规则：packet 未明确给出的候选人姓名、年龄、学校、薪资、技能清单、项目经历、经验年限，不允许在最终答复里展开。

验证结果：

- `rag_to_note` 单场景复跑通过：`search=1`、`context_pack=1`、`budget_violations=0`。
- 高并发全量 live smoke（P0+P1，11 场景，并发 4）最终通过：`11/11`。
- 全量结果：`harmful_duplicate_runs=0/11`、`hidden_runs=0/11`。

验证命令：

```bash
RETRIEVAL_TOOL_BACKEND=mcp uv run --extra mcp python tools/smoke_live_matrix.py \
  --scenario rag_to_note \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m58f2_mcp_rag_to_note \
  --json-report data/live_smoke_matrix_m58f2_mcp_rag_to_note/report.json \
  --quiet

RETRIEVAL_TOOL_BACKEND=mcp uv run --extra mcp python tools/smoke_live_matrix.py \
  --all-p0 \
  --all-p1 \
  --runs 1 \
  --concurrency 4 \
  --max-tool-rounds 24 \
  --data-dir data/live_smoke_matrix_m58f2_mcp_full_c4 \
  --json-report data/live_smoke_matrix_m58f2_mcp_full_c4/report.json \
  --quiet
```

## 不做事项

第一版不做：

- 向量库。
- embedding。
- reranker。
- 自动爬虫。
- MCP 写入工具。
- MCP reindex 工具。
- 把 Note / Knowledge / Career 数据迁移到 RAG。
- 把 MCP transport session 当作产品 session。
- 让模型传 `session_id`。
- 直接向 MCP client 暴露本地文件路径。

## 需要审核的点

开发前需要确认：

- MCP tool 名称是否沿用 `retrieval_search` / `retrieval_context_pack`，还是改成 `retrieval.search` / `retrieval.context_pack`。
- 无 app session 时，显式请求 `session_artifact` 是报错还是过滤。
- 第一版是否只做 `stdio`，HTTP transport 是否放到后续。
- 是否接受 `mcp` 作为 optional dependency，而不是主依赖。
- 是否需要在文档外另补一份 MCP client 配置示例。
