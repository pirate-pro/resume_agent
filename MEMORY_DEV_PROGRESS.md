# Memory 子系统开发过程记录

## 开发约定

- 记录位置：仓库根目录（本文件）。
- 记录方式：每完成一项即追加一条，包含时间、变更内容、影响范围、验证结果。
- 当前目标：按 `MEMORY_FILE_BASED_DESIGN.md` 继续推进（v2 直连基线下，推进 Step B 治理与检索质量）。

## 进度日志

### 2026-04-21

1. [完成] 创建开发过程记录文档。
- 说明：建立本文件，作为后续持续记录载体。
- 影响范围：仅文档，无代码行为变更。
- 验证：文件创建成功。

2. [完成] 落地 Memory Phase A 核心骨架（不切现网逻辑）。
- 说明：
  - 新增 `app/memory/` 核心模块：`models/contracts/policies/retrieval/consolidation/lifecycle/facade`。
  - 新增 `app/memory/stores/`：`jsonl_file_store.py`（文件存储实现）与 `legacy_adapter.py`（迁移适配器）。
  - 新增 `app/memory/__init__.py` 与 `stores/__init__.py` 统一导出。
- 影响范围：
  - 新增代码，不改现有 `runtime/tool/service` 调用链，当前行为不变。
  - 为后续双写/灰度切换提供接口基础。
- 验证：待运行 `mypy/pytest` 回归。

3. [完成] Phase A 回归验证。
- 说明：完成类型检查与测试回归，确认新增模块未影响现有行为。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 57 source files`）
  - `uv run pytest -q`：通过（`28 passed`）

4. [完成] 落地 Phase B（双写）核心接入。
- 说明：
  - 新增 `app/memory/bridge.py`，统一 legacy 写入 -> v2 candidate 的映射策略。
  - `MemoryManager` 接入可选 `memory_facade`，在 legacy 成功写入后 best-effort 写候选。
  - `MemoryWriteTool` 接入可选 `memory_facade`，保持旧行为优先、候选写入失败只告警不阻断。
  - DI 接入：`app/api/deps.py` 新增 `get_memory_store/get_memory_facade`，默认使用 `data/memory_v2` 文件存储。
  - 测试辅助接入：`tests/helpers.py` 同步接入 memory facade。
- 影响范围：
  - 读路径仍保持旧逻辑（未切换）。
  - 写路径变为 legacy + candidate 双写（best-effort）。

5. [完成] Phase B 测试补充与回归验证。
- 说明：
  - 新增测试覆盖：
    - `MemoryManager` 双写后 candidate 生成与 consolidate 基本链路。
    - `MemoryWriteTool` 双写不破坏 legacy 行为。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 58 source files`）
  - `uv run pytest -q`：通过（`30 passed`）

6. [完成] 移除 Memory 兼容桥接层，切换为纯 v2 运行链路。
- 说明：
  - 删除 `app/memory/bridge.py`。
  - 删除 `app/memory/stores/legacy_adapter.py`，并同步更新 `stores/__init__.py` 导出。
  - `MemoryManager`、`MemoryWriteTool`、`MemorySearchTool` 保持仅依赖 `MemoryFacade`（不再保留旧构造参数路径）。
- 影响范围：
  - 运行时不再存在 dual-write/compat 逻辑，memory 主链路统一为 v2。

7. [完成] 同步更新测试到 v2-only 语义。
- 说明：
  - 更新 `tests/helpers.py`、`tests/test_memory_manager.py`、`tests/test_tool_registry.py`、
    `tests/test_context_assembler.py`、`tests/test_agent_runtime.py`。
  - 移除对 `JsonlMemoryRepository` 的运行时依赖断言，改为校验 `FileMemoryFacade` 读写结果。
- 影响范围：
  - 测试语义与运行时架构一致，避免“实现已切换但测试仍走旧链路”。

8. [完成] 修复 v2 列表查询通配语义。
- 说明：
  - 在 `JsonlFileMemoryStore.search_records` 中将 `*` / `__all__` 视为全量匹配，避免 `list_memories` 因关键词过滤返回空结果。
- 影响范围：
  - `MemoryManager.list_memories` 的行为符合预期。

9. [完成] 清理 Skill 仓储的 legacy 兼容读取逻辑（硬切标准协议）。
- 说明：
  - `MarkdownSkillRepository` 移除 `skills/<name>.md` 老布局兼容，仅保留 `skills/<name>/SKILL.md` 标准协议。
  - 移除 skill 名称 `_`/`-` 自动互转别名解析，改为严格按请求名匹配 `frontmatter.name`。
  - 更新 `tests/test_storage.py`：legacy 布局从“可读取”改为“应报错”。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 57 source files`）
  - `uv run pytest -q`：通过（`30 passed`）

10. [完成] 推进 Step B：shared 晋升阈值与跨轮去重落地。
- 说明：
  - `MemoryStore` 新增 `count_active_records_by_hash(...)` 契约。
  - `JsonlFileMemoryStore` 实现按 scope/agent/session/content_hash 统计 active 记录数。
  - `MemoryConsolidationService` 新增治理策略：
    - `shared_long` 晋升需要同时满足置信度阈值 + 重复次数阈值。
    - 未满足 shared 门槛时自动降级写入 `agent_long`。
    - 写入前与既有记录做同 hash 去重，避免跨轮重复写入。
  - 新增测试 `tests/test_memory_consolidation.py` 覆盖上述策略。
- 影响范围：
  - shared 记忆更稳健，不再因单次高置信输入直接污染全局层。
  - consolidation 的去重从“仅批内”提升为“批内 + 既有记录”。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 58 source files`）
  - `uv run pytest -q`：通过（`32 passed`）

11. [完成] 推进 Step B：compact V1 落地（memory JSONL 压缩治理）。
- 说明：
  - 新增模型与接口：
    - `MemoryCompactRequest`、`CompactResult`。
    - `MemoryFacade.compact(...)`、`MemoryStore.compact(...)` 契约与实现链路（facade -> lifecycle -> store）。
  - `JsonlFileMemoryStore.compact(...)` 实现：
    - 支持按 `scope/agent_id/session_id` 定位压缩范围。
    - 清理 `deleted` 与过期记录（可配置开关）。
    - 默认按 `memory_id` 去重保留最新版本；可选按 `content_hash` 再去重。
    - 原子重写 JSONL（`.tmp` -> replace）。
    - 重建索引文件并写入 `ops/compact.log.jsonl` 审计日志。
  - 新增测试：`tests/test_memory_compaction.py`（3 个用例）。
- 影响范围：
  - memory 文件可定期瘦身，降低检索噪音与历史冗余。
  - 为后续 TTL 定时治理与自动触发 compact 提供基础能力。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 59 source files`）
  - `uv run pytest -q`：通过（`35 passed`）

12. [完成] 修复“长期记忆无法跨会话命中”问题。
- 说明：
  - 根因：`memory_write` 在未传 `tags` 时会被策略推断为 `agent_short`，导致换会话后 `memory_search` 看不到该记忆。
  - 修复：`MemoryWriteTool` 在无长期/共享标签时自动补齐 `memory` 标签，确保默认写入长期层语义。
  - 同步修复：`MemoryManager.write_memory` 同样补齐长期标签，避免 service/API 侧写入出现语义漂移。
  - 新增测试：
    - `test_memory_write_tool_without_tags_is_long_term_and_cross_session_searchable`
    - `test_memory_manager_write_without_tags_defaults_to_agent_long`
- 影响范围：
  - `memory_write(content=...)` 默认行为与工具描述“写入长期记忆”一致。
  - 跨会话 memory 检索可命中这类默认写入的长期记忆。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 59 source files`）
  - `uv run pytest -q`：通过（`37 passed`）

13. [完成] Memory 路由策略调整为“默认短期，按规则晋升长期/共享”。
- 说明：
  - 回撤默认补 `memory` 标签的行为（`MemoryWriteTool`、`MemoryManager`），不再“默认长期”。
  - `MemoryConsolidationService` 增加 `agent_short -> agent_long` 晋升：
    - 达到重复阈值 + 置信度阈值后晋升长期。
    - `explicit_user_rule/system_policy` 可直升长期。
  - `shared_long` 晋升保留高置信 + 重复门槛；新增显式规则直通（可跳过重复门槛）。
  - `MemoryPolicy` 新增长期晋升参数：`agent_long_promotion_min_confidence`、`agent_long_promotion_min_repeat`。
  - 同步更新技能文档与工具描述，明确 `memory_write` 为“默认短期候选”。
  - 测试更新与新增：
    - 默认写入短期且会话隔离测试。
    - 短期重复后晋升长期测试。
    - 显式规则 shared 直通测试。
- 影响范围：
  - 分层更符合“记忆形成过程”：short 记录 -> long 沉淀 -> shared 共识。
  - 降低长期层污染和膨胀风险。

### 2026-04-22

14. [完成] 优化 memory 检索前置处理与中文召回质量（不改 memory 结构）。
- 说明：
  - 在 `JsonlFileMemoryStore.search_records` 增加查询预处理 `_QueryPlan`：
    - 查询归一化（符号清洗、空白规整）。
    - 严格召回 token（原词 + 中文 2/3-gram + 名称意图扩展词）。
    - 兜底召回 token（去停用字后的单字集合）。
  - 落地“两阶段召回”：
    - 第一阶段使用严格 token 打分。
    - 严格阶段无命中时自动启用兜底 token 召回，并打印调试日志。
  - 升级 `_score_record`：
    - 增加“完整查询串命中”加分。
    - 按 token 长度加权，提升关键短语命中排序质量。
  - 新增测试：
    - `test_memory_manager_search_recalls_chinese_long_memory_by_question_form`
    - `test_context_assembler_recalls_cross_session_chinese_name_memory`
- 影响范围：
  - 修复“长期记忆已存在，但中文问句（如‘你叫什么名字’）未召回”的问题。
  - 不引入新 memory 结构，兼容现有 `agent_long/shared_long/agent_short` 文件布局。

15. [完成] 统一 memory 检索作用域：`memory_search` 与自动上下文检索对齐为 agent 级。
- 说明：
  - 修复行为不一致问题：
    - 自动上下文检索（`MemoryManager.search`）原本按 agent 级检索（`session_id=None`）。
    - `memory_search` 工具原本按当前 session 检索（`session_id=<current>`）。
  - 变更 `MemorySearchTool.execute`：读取时固定传 `session_id=None`，使同一 agent 下可跨会话检索 `agent_short`。
  - 更新工具描述与 skill 文案，明确 `memory_search` 为“同 agent 跨会话可见”语义。
  - 新增测试：
    - `test_memory_write_tool_without_tags_defaults_to_short_and_is_agent_scoped`
    - `test_memory_search_tool_isolated_by_agent_id`
- 影响范围：
  - 解决“同一系统两条读取路径返回不一致”问题。
  - 保持 agent 隔离边界：不同 agent 仍不可见彼此记忆。

16. [完成] 多 Agent 前置改造文档落地（详细设计版）。
- 说明：
  - 新增根目录文档 `MULTI_AGENT_PREP_DESIGN.md`。
  - 覆盖 session/run/agent 边界定义、数据模型升级、接口改造、分阶段实施、测试验收、迁移与回滚策略。
- 影响范围：
  - 统一后续改造口径，避免“边开发边改口径”导致的返工。

17. [完成] Phase A 第一批代码骨架（RunContext + 事件/会话元数据升级）。
- 说明：
  - `domain.models` 新增 `RunContext`，并扩展：
    - `EventRecord`：`agent_id/run_id/parent_run_id/event_version`
    - `SessionMeta`：`participants/entry_agent_id`
    - `AgentRunInput`：可挂载 `context`
  - `schemas.chat` 新增：
    - `ChatRequest.entry_agent_id/trace_level`
    - `EventView` 对应新增字段
  - `ChatService` 在请求编排阶段生成 `RunContext` 并挂载到 `AgentRunInput`。
  - `AgentRuntime` 增加 `_resolve_run_context`，并将 run/agent 元信息写入所有 runtime 事件。
  - `EventRecorder`、`JsonlSessionRepository` 完成新字段读写：
    - 事件落盘包含 `agent_id/run_id/...`
    - metadata 维护 `participants/entry_agent_id`
    - 旧数据读取提供安全默认值
  - SSE 事件序列化同步输出新增字段。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 59 source files`）
  - `uv run pytest -q`：通过（`42 passed`）

18. [完成] Phase B 第二批改造（工具执行链路全面切换 RunContext）。
- 说明：
  - `Tool` 协议签名统一为 `execute(arguments, context: RunContext)`，移除 `session_id` 直传模式。
  - `ToolExecutor` 协议同步切换为 `execute(call, context: RunContext)`。
  - `ToolRegistry.execute` 全链路改为接收 `RunContext`，并在日志中显式输出 `session_id/agent_id`。
  - `AgentRuntime._execute_tool_safely` 改为传递 `RunContext`，工具执行错误日志补齐 `agent_id` 维度。
  - 内置工具 `builtins` 全部改为通过 `context` 读取运行信息：
    - 文件工具读取 `context.session_id`。
    - memory 工具读取 `context.agent_id` + `context.session_id`，不再依赖隐式会话参数。
  - `tests/test_tool_registry.py` 全量迁移为 `_context(...)` 调用，消除旧签名测试路径。
- 影响范围：
  - 工具层已完成多 Agent 预备改造，后续可在不改工具接口的前提下接入 orchestrator 子运行链路。
  - 统一上下文对象后，排查问题时可稳定关联到具体 `run/agent/session`。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 59 source files`）
  - `uv run pytest -q`：通过（`42 passed`）
