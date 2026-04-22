# 多 Agent 前置改造开发文档（先立地基）

## 1. 文档目标

本文档用于指导当前单 Agent 系统进行“多 Agent 可扩展化前置改造”。

目标不是立刻上线完整多 Agent 编排，而是先完成以下基础能力：

1. 明确 `session / run / agent` 三层边界。
2. 消除当前链路中对 `agent_main` 的隐式硬编码。
3. 统一上下文与工具调用协议，避免后续重复拆改。
4. 为后续 orchestrator（调度）、sub-agent（执行）提供稳定接口。

---

## 2. 当前现状（基于代码排查）

### 2.1 当前已实现

1. `session` 以 JSON 文件目录管理，事件在 `data/sessions/<session_id>/events.jsonl`。
2. Runtime 为单 Agent 执行链：`ChatService -> AgentRuntime -> model/tool loop`。
3. Memory 已具备分层：`agent_short / agent_long / shared_long`。

### 2.2 当前关键问题

1. **会话模型不含 agent 维度**：`SessionMeta` 无 `agent_id/participants`。
2. **请求协议不含入口 agent**：`ChatRequest` 无 `entry_agent_id`。
3. **事件模型不可追踪多 agent**：`EventRecord` 无 `agent_id/run_id/parent_run_id`。
4. **工具与 memory 仍有默认 agent 依赖**：`default_agent_id="agent_main"`。
5. **缺少统一运行上下文对象**：不同模块传参分散，后续编排会混乱。

---

## 3. 设计原则

1. 高内聚低耦合：跨模块只通过明确协议传递上下文。
2. 显式优先：agent、run、scope 必须显式输入，避免隐式默认。
3. 先统一协议，再扩展能力：先把地基打稳，再接 orchestrator。
4. 文件存储优先：当前阶段继续 JSON/JSONL，不引入数据库。
5. 先可观测再优化：事件必须可回放、可审计、可定位。

---

## 4. 核心边界定义（最终口径）

### 4.1 Session（全局会话容器）

1. `session` 是用户对话容器，不归属于某个单一 agent。
2. 一个 session 可由多个 agent 参与（后续由 orchestrator 管理参与者）。
3. 会话文件（上传文件、active files）默认仍为 session 级资产。

### 4.2 Agent（执行主体）

1. `agent` 是执行与决策主体，具备独立能力边界（工具权限、memory 作用域）。
2. `agent_short`、`agent_long` 为 agent 私有层；`shared_long` 为跨 agent 共享层。

### 4.3 Run（一次执行链路）

1. 一次用户输入对应至少一个 run（入口 agent run）。
2. 后续多 agent 协作时，会产生 parent/child run 树。
3. run 是审计最小单元，必须可追踪。

---

## 5. 目标数据模型改造

## 5.1 RunContext（新增，核心）

新增统一运行上下文对象（domain 层 dataclass）：

1. `session_id: str`
2. `run_id: str`
3. `agent_id: str`
4. `turn_id: str`
5. `parent_run_id: str | None`
6. `entry_agent_id: str`
7. `trace_flags: dict[str, bool]`

说明：

- runtime、tool executor、memory manager、event recorder 全部接收 `RunContext`。
- 严禁继续在深层模块自行拼 `session_id + default_agent_id`。

## 5.2 EventRecord（升级）

在现有事件模型基础上新增字段：

1. `agent_id: str`
2. `run_id: str`
3. `parent_run_id: str | None`
4. `event_version: int`（固定 `2`）

保留原字段：`event_id/session_id/type/payload/created_at`。

## 5.3 SessionMeta（升级）

新增：

1. `participants: list[str]`（参与过该 session 的 agent_id 集合）
2. `entry_agent_id: str | None`（最近入口 agent）

## 5.4 ChatRequest（升级）

新增：

1. `entry_agent_id: str = "agent_main"`
2. `trace_level: Literal["basic", "verbose"] = "basic"`

---

## 6. 协议与接口改造

## 6.1 Runtime 链路

当前：

- `AgentRunInput(session_id, user_message, ...)`

目标：

- `AgentRunInput(context: RunContext, user_message, ...)`

## 6.2 ToolExecutor 协议

当前：

- `execute(call, session_id)`

目标：

- `execute(call, context: RunContext)`

影响：

- 所有内置工具统一读取 `context.session_id`、`context.agent_id`。
- 去掉工具内部 `default_agent_id` 作为业务决策依据，仅保留初始化兜底校验（过渡期后删除）。

## 6.3 MemoryManager 协议

当前：

- 依赖 `default_agent_id`

目标：

- `write_memory(..., context: RunContext)`
- `search(..., context: RunContext, strategy)`

策略要求：

1. `memory_search` 与自动上下文检索都用同一查询策略。
2. 在同一 `agent_id` 下读取 `agent_short`（跨 session）、`agent_long`。
3. 同时读取 `shared_long`。

---

## 7. 多 Agent 预留（本阶段只做骨架）

新增 orchestrator 接口，不接真实复杂策略：

1. `plan(context, user_message) -> PlanResult`
2. `dispatch(plan) -> list[RunContext]`
3. `collect(child_results) -> AggregatedResult`
4. `synthesize(aggregated) -> final_answer`

第一版可实现为“单入口 agent 直通”，但接口必须存在，便于后续替换。

---

## 8. 开发分阶段（必须按顺序）

## Phase A：上下文与模型改造（地基）

1. 新增 `RunContext` 模型。
2. 升级 `ChatRequest`、`AgentRunInput`、`EventRecord`。
3. 升级 session metadata 结构（participants、entry_agent_id）。
4. 更新 schema 校验与序列化。

交付标准：

- API 仍可跑通；单 agent 行为不变。
- 新增字段全部可读写。

## Phase B：执行链路改造

1. `ChatService` 生成 `RunContext` 并传给 Runtime。
2. `AgentRuntime`、`EventRecorder`、`ToolRegistry` 改为 context 驱动。
3. 内置工具改造为读取 context。

交付标准：

- 不再需要在工具或 memory 内部使用隐式 agent。
- 所有事件都带 `agent_id/run_id`。

## Phase C：Memory 链路统一

1. `MemoryManager` 改为显式接收 `context.agent_id`。
2. 自动检索与 `memory_search` 工具复用同一入口。
3. 明确 `agent_short/agent_long/shared_long` 读取策略。

交付标准：

- 同一 agent 读取结果一致。
- 不同 agent 严格隔离（shared 除外）。

## Phase D：orchestrator 骨架接入

1. 新增 orchestrator 接口与默认实现（直通模式）。
2. `ChatService` 通过 orchestrator 启动入口 run。
3. 先不做并行 sub-agent，只做可扩展框架。

交付标准：

- 当前功能不回退。
- 可在不改 API 的前提下引入子 agent 调度。

---

## 9. 测试与验收

## 9.1 必须新增测试

1. `test_run_context_propagation.py`
- 校验 API -> service -> runtime -> tool 全链路 context 透传。

2. `test_event_record_v2.py`
- 校验事件含 `agent_id/run_id/parent_run_id/event_version`。

3. `test_memory_scope_by_agent.py`
- 同 agent 跨会话可见 `agent_short`。
- 不同 agent 不可见彼此 `agent_short/agent_long`。
- shared 可见。

4. `test_session_participants.py`
- 参与 agent 会写入 metadata.participants。

## 9.2 验收口径

1. 单 agent 路径功能与现状一致（兼容用户体验）。
2. 多 agent 核心上下文字段齐全，可观测。
3. Memory 与 Tool 在 agent 维度行为一致。
4. 所有新增测试通过，mypy 通过。

---

## 10. 迁移策略（文件存储）

本项目不做长期“打补丁式双协议并存”，采用一次性升级策略：

1. 提供 `scripts/migrate_session_metadata_v2.py`：补齐历史 metadata 字段。
2. 提供 `scripts/migrate_events_v2.py`：为历史事件补默认 `agent_id/run_id/event_version`。
3. 启动前先迁移，再运行新代码。

原则：

- 不长期维护 v1/v2 双写双读。
- 迁移可回滚（保留 `.bak` 文件）。

---

## 11. 风险与回滚

## 11.1 风险

1. 事件结构变更导致前端调试面板解析异常。
2. 工具协议从 `session_id` 改为 `RunContext` 后，调用点漏改。
3. 历史文件未迁移导致运行时报错。

## 11.2 回滚策略

1. 代码层：按 phase 分批提交；每 phase 单独可回退。
2. 数据层：迁移前备份 `data/sessions` 与 `data/memory_v2`。
3. 发布层：先在本地数据集演练迁移，再切生产数据。

---

## 12. 开发规范（本项目执行）

1. 每完成一项 phase 子任务，更新 `MEMORY_DEV_PROGRESS.md`。
2. 注释使用中文，提交信息使用中文。
3. 每次提交前至少执行：

```bash
uv run mypy app tests
uv run pytest -q
```

4. 按“分批提交并推送”执行，不混入无关运行产物。

---

## 13. 第一批实施清单（下一步）

下一批开发仅做 Phase A（不进入 orchestrator 实装）：

1. 新增 `RunContext` 及相关 dataclass。
2. ChatRequest 增加 `entry_agent_id/trace_level`。
3. EventRecord 升级字段并落盘。
4. Session metadata 增加 `participants/entry_agent_id`。
5. 补齐 Phase A 测试与迁移脚本。

> 完成 Phase A 后再进入 Phase B，避免一次改动过大。
