# Memory 子系统开发过程记录

## 开发约定

- 记录位置：仓库根目录（本文件）。
- 记录方式：每完成一项即追加一条，包含时间、变更内容、影响范围、验证结果。
- 当前目标：按 `MEMORY_FILE_BASED_DESIGN.md` 继续推进（在 v2 直连基线上完善治理与检索质量）。

## 进度日志

### 2026-04-21

1. [完成] 创建开发过程记录文档。
- 说明：建立本文件，作为后续持续记录载体。
- 影响范围：仅文档，无代码行为变更。
- 验证：文件创建成功。

2. [完成] 搭建 memory 核心骨架（不切现网逻辑）。
- 说明：
  - 新增 `app/memory/` 核心模块：`models/contracts/policies/retrieval/consolidation/lifecycle/facade`。
  - 新增 `app/memory/stores/`：`jsonl_file_store.py`（文件存储实现）与 `legacy_adapter.py`（迁移适配器）。
  - 新增 `app/memory/__init__.py` 与 `stores/__init__.py` 统一导出。
- 影响范围：
  - 新增代码，不改现有 `runtime/tool/service` 调用链，当前行为不变。
  - 为后续双写/灰度切换提供接口基础。
- 验证：待运行 `mypy/pytest` 回归。

3. [完成] 核心骨架接入后的回归验证。
- 说明：完成类型检查与测试回归，确认新增模块未影响现有行为。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 57 source files`）
  - `uv run pytest -q`：通过（`28 passed`）

4. [完成] 接入 memory 双写核心链路。
- 说明：
  - 新增 `app/memory/bridge.py`，统一 legacy 写入 -> v2 candidate 的映射策略。
  - `MemoryManager` 接入可选 `memory_facade`，在 legacy 成功写入后 best-effort 写候选。
  - `MemoryWriteTool` 接入可选 `memory_facade`，保持旧行为优先、候选写入失败只告警不阻断。
  - DI 接入：`app/api/deps.py` 新增 `get_memory_store/get_memory_facade`，默认使用 `data/memory_v2` 文件存储。
  - 测试辅助接入：`tests/helpers.py` 同步接入 memory facade。
- 影响范围：
  - 读路径仍保持旧逻辑（未切换）。
  - 写路径变为 legacy + candidate 双写（best-effort）。

5. [完成] 补充双写链路测试并完成回归验证。
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

10. [完成] 落地 shared 晋升阈值与跨轮去重治理。
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

11. [完成] 落地 compact V1（memory JSONL 压缩治理）。
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

17. [完成] 新增 RunContext 并升级事件/会话元数据骨架。
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

18. [完成] 工具执行链路全面切换到 RunContext。
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

19. [完成] 统一 memory 检索入口并改为显式 agent 上下文驱动。
- 说明：
  - `MemoryManager` 移除隐式默认 agent，读写改为显式接收 `RunContext` 或 `agent_id`。
  - 新增统一检索入口：
    - `search_bundle(...)`（返回原始检索 bundle，供工具保留 scope/confidence）
    - `search_with_summary(...)`（返回命中结果与检索摘要，供上下文注入）
    - `search_for_agent(...)` / `list_memories_for_agent(...)`（供 API 显式按 agent 查询）
  - `ContextAssembler` 改为接收 `RunContext`，并把检索摘要写入 `ContextBundle.memory_summary`。
  - `AgentRuntime` 新增 `memory_retrieval` 事件，记录 query、命中数、scope、扫描量等信息，便于排查召回问题。
  - `memory_search` 工具改为复用 `MemoryManager.search_bundle(...)`，和自动上下文检索走同一检索链路。
  - `/api/memories` 新增 `agent_id` 查询参数（默认 `agent_main`），避免“全局混查”。
  - 同步更新依赖注入与测试装配，补齐上下文签名迁移后的测试用例。
- 影响范围：
  - 同一 agent 下，自动上下文检索与工具检索行为一致。
  - 记忆读取边界更清晰：按 agent 显式检索，shared 仍由 memory 层策略统一合并。
  - 运行事件可观测性增强，定位“为什么没召回”更直接。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 59 source files`）
  - `uv run pytest -q`：通过（`42 passed`）

20. [完成] 补齐上下文强约束与记忆跨 agent 策略开关，并补充契约测试。
- 说明：
  - `EventRecorder.record` 改为只接收 `RunContext`，移除 `agent_id/run_id/parent_run_id` 散参写法。
  - `AgentRuntime` 全部事件写入改为传 `context=RunContext`，并移除 `agent_main` 兜底上下文分支（`run_input.context` 改为必填）。
  - `MemoryWriteTool` 移除 `default_agent_id` 兜底，写入 agent 仅来自运行上下文。
  - `MemoryManager` 新增跨 agent 策略开关：
    - `allow_cross_agent_read`（默认关闭）
    - `allow_cross_agent_write`（默认关闭）
    - 未开启时，拒绝跨 agent 指定目标读写请求。
  - `/api/memories` 新增 `target_agent_id` 参数，配合策略开关控制是否允许跨 agent 指定读取目标。
  - 新增契约测试文件 `tests/test_multi_agent_contracts.py`，覆盖：
    - 单 agent 路径下事件字段与 participants 维护不回退；
    - 双 agent 私有记忆隔离；
    - shared 记忆跨 agent 可见 + 跨 agent 私有读取默认受限。
- 影响范围：
  - 运行链路参数边界更统一，后续接多 agent 调度时上下文更稳定。
  - 记忆跨 agent 访问行为从“隐式可读”改为“显式策略控制”。

21. [完成] 落地 AgentCapability 权限矩阵并打通到工具与记忆链路。
- 说明：
  - 新增 `app/runtime/agent_capability.py` 与 `app/config/agent_capabilities.json`，提供文件化能力矩阵：
    - `allowed_tools`
    - `memory_read_scopes` / `memory_write_scopes`
    - `allow_cross_session_short_read`
    - `allow_cross_agent_memory_read` / `allow_cross_agent_memory_write`
  - `Settings` 与 `deps` 接入能力配置加载，`ChatService` 在入口校验 `entry_agent_id` 必须存在于能力矩阵。
  - `ToolRegistry.execute` 增加按 `context.agent_id` 的工具权限校验，未授权工具直接拒绝执行。
  - `MemoryManager` 增加能力约束：
    - 写入按 tags 推断目标 scope，并校验写权限。
    - 跨 agent 读写走显式开关控制。
    - `allow_cross_session_short_read=false` 时，`agent_short` 读取自动收敛到当前 session。
  - `MemoryWriteTool` 改为复用 `MemoryManager.write_memory`，避免工具层绕开统一策略。
  - 同步迁移测试装配与用例，补充权限矩阵相关回归测试。
- 影响范围：
  - 多 agent 场景下工具权限和记忆作用域边界可配置、可审计，且默认最小权限。
  - 单 agent 现有行为保持可用（默认配置 `agent_main` 维持全工具 + 全 scope）。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 61 source files`）
  - `uv run pytest -q`：通过（`48 passed`）

22. [完成] 增加会话删除能力并修复前端右侧调试面板滚动问题。
- 说明：
  - 后端新增会话删除链路：
    - `SessionRepository` 协议增加 `delete_session(session_id)`。
    - `JsonlSessionRepository` 实现删除会话目录（`data/sessions/<session_id>`）。
    - `ChatService` 增加 `delete_session(...)`，串行加锁后执行删除。
    - API 新增 `DELETE /api/sessions/{session_id}`，返回 `SessionDeleteResponse`。
  - 前端新增“删除当前会话”按钮：
    - 调用删除接口后同步清理本地会话快照并自动切换到其他会话/空白会话。
  - 修复右侧面板滚动：
    - `panel-right` 与其 `grow` 卡片增加独立滚动，解决 `Memories` 区域超出不可见问题。
    - 增加对应滚动条样式，保持视觉一致。
  - 新增测试：
    - `tests/test_storage.py`：会话删除后目录与事件不可读校验。
    - `tests/test_chat_service.py`：服务层删除会话校验。
    - `tests/test_chat_api.py`：删除接口端到端校验。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 61 source files`）
  - `uv run pytest -q`：通过（`51 passed`）

23. [完成] 增加记忆编辑能力：`memory_forget` / `memory_update` 工具与记忆编辑 skill。
- 说明：
  - 新增记忆工具：
    - `memory_forget(query, limit, hard_delete, reason?)`：先检索后遗忘，支持软删除/硬删除。
    - `memory_update(query, new_content, new_tags, limit, hard_delete_old)`：按“先删旧，再写新”流程替换记忆。
  - `MemoryManager` 增加 `forget_memory_ids(...)`，统一执行删除权限校验（按 scope 检查能力矩阵）并调用 memory lifecycle。
  - `ToolRegistry` 侧接入两个新工具，保持工具权限矩阵统一生效。
  - 新增 `app/skills/memory-editor/SKILL.md`，固化记忆新增/删除/更新的触发条件与执行顺序。
  - 同步更新 `memory`、`tools` skill 文案，并在前端 skill 选项中加入 `memory-editor`（默认勾选）。
  - `ChatService` 默认 skill 列表加入 `memory-editor`（当请求未显式传 skill_names 时生效）。
  - 补充测试：
    - `memory_forget` 可正确删除命中记忆；
    - `memory_update` 单命中替换成功；
    - `memory_update` 多命中返回歧义候选，不盲改。
- 验证结果：
  - `uv run mypy app tests`：通过（`Success: no issues found in 61 source files`）
  - `uv run pytest -q`：通过（`54 passed`）

### 2026-04-27

24. [完成] 固化 memory 重构设计文档，并按多 Agent 方向收紧边界定义。
- 说明：
  - 新增根目录文档 `MEMORY_REARCHITECTURE_DESIGN_2026-04-27.md`。
  - 明确四层边界：
    - `AGENT.md`：静态行为宪法层。
    - `SOUL.md`：静态或缓变的人格身份层。
    - `state`：运行态工作区，默认按 agent 隔离。
    - `memory`：长期互动经验层，要求可强化、可衰减、可被覆盖。
  - 根据多 agent 协作预期修正文档口径：
    - `state` 默认拆为 `state_agent_session` 与 `state_shared_session`。
    - 长期记忆命名改为 `memory_agent_long` / `memory_shared_long`，避免误导为“天然按 user 全局共享”。
    - 在 memory schema 中引入 `owner_agent_id` 与 `visibility`，把归属与共享性显式建模。
- 影响范围：
  - 当前仅变更设计文档，不改变运行时代码行为。
  - 为后续 `state` 拆分、memory 收窄和多 agent 协作提供统一术语与边界。
- 验证结果：
  - 文档已落盘并完成本轮评审修订。

25. [完成] 落地 Phase 1：独立 `state` 子系统基础骨架。
- 说明：
  - 新增 `app/state/` 子系统：
    - `models.py`：定义 `StateScope`、`StateStatus`、`StateRecord`。
    - `contracts.py`：定义 `StateStore` 契约。
    - `stores/jsonl_file_store.py`：实现文件化 JSONL state 存储。
    - `manager.py`：实现 `StateManager`，提供 `set/list/clear/publish/revoke` 能力。
  - `state` scope 设计落地为：
    - `agent_session`：当前 agent 在当前 session 下的私有工作状态。
    - `shared_session`：当前 session 内显式发布的共享协作状态。
  - 存储布局按多 agent 方向预留：
    - `state/agents/<agent_id>/sessions/<session_id>.jsonl`
    - `state/shared/sessions/<session_id>.jsonl`
  - `publish_agent_state(...)` 采用“从私有态显式发布到共享态”的模式，不默认跨 agent 泄漏私有 state。
  - 新增测试 `tests/test_state_manager.py`，覆盖：
    - 同 key upsert。
    - agent 私有 state 隔离。
    - 共享 state 发布。
    - 清理私有 state 不影响共享副本。
    - 共享 state 撤销。
    - 发布不存在 key 时抛错。
- 影响范围：
  - 当前为新增基础设施，尚未接入 `ChatService` / `AgentRuntime` / `ContextAssembler` 主链路。
  - 为后续从 `agent_short` 中拆出 `state_agent_session` / `state_shared_session` 提供直接落点。
- 验证结果：
  - `uv run pytest -q tests/test_state_manager.py`：通过（`6 passed`）
  - `uv run mypy app/state tests/test_state_manager.py`：通过（`Success: no issues found in 7 source files`）
  - `uv run pytest -q`：通过（`89 passed in 0.61s`）
  - 备注：`uv run mypy app tests` 当前基线存在 25 个历史遗留错误，主要位于 `app/api/chat.py`、`app/services/chat_service.py` 及既有测试文件；本次未新增或放大这些问题，因此未在本阶段顺手改动。

26. [完成] 将 `state` 正式接入工具层与上下文组装链路。
- 说明：
  - 新增内建工具：
    - `state_set(key, value)`：写入/更新当前 agent 的私有 session state。
    - `state_publish(keys)`：把选定私有 state 发布到 session shared state。
    - `state_list(scope)`：查看当前 session 的私有/共享 state。
  - 依赖装配接入：
    - `app/api/deps.py` 新增 `get_state_store()`、`get_state_manager()`。
    - `ToolRegistry` 默认注册 `state_*` 工具。
    - `tests/helpers.py` 与 `tests/test_agent_runtime.py` 等测试装配同步接入 `StateManager`。
  - `ContextAssembler` 接入 state 注入：
    - system prompt 中新增 `Current agent state` 段落。
    - system prompt 中新增 `Shared session state` 段落。
    - 与 `Relevant memories` 分离，避免把运行态 working state 混进长期 memory 表达。
  - 同步更新 skill 文案：
    - `app/skills/tools/SKILL.md` 增加 `state_*` 用法。
    - `app/skills/memory/SKILL.md` 明确“当前任务目标/下一步/working notes 优先写 state，不写 memory”。
- 影响范围：
  - runtime 已经具备独立的 state 读写与 prompt 注入路径，agent 可以开始把会话内 working state 与长期 memory 分开处理。
  - 当前尚未把旧的 `agent_short` 自动迁移到 `state_agent_session`；这部分仍属于后续 Phase 1/2 的继续拆分项。
- 验证结果：
  - `uv run pytest tests/test_state_manager.py tests/test_context_assembler.py tests/test_tool_registry.py tests/test_agent_runtime.py`：通过（`37 passed in 0.18s`）
  - `uv run mypy app/state app/runtime/context_assembler.py app/tools/builtins.py app/api/deps.py tests/test_state_manager.py tests/test_context_assembler.py tests/test_tool_registry.py tests/test_agent_runtime.py tests/helpers.py`：通过（`Success: no issues found in 14 source files`）
  - `uv run pytest -q`：通过（`92 passed in 0.57s`）

27. [完成] 收紧自动 memory 召回边界：`ContextAssembler` 不再把 `agent_short` 注入为 `Relevant memories`。
- 说明：
  - `MemoryManager` 新增面向运行时上下文的长期检索入口 `search_context_memories(...)`。
  - `ContextAssembler` 改为调用长期检索入口，而不是通用 `search_with_summary(...)`。
  - 当前策略调整为：
    - 自动 prompt 注入的 `Relevant memories` 仅来自 `agent_long` / `shared_long`。
    - `agent_short` 继续保留给 consolidation、显式 `memory_search`、以及过渡期兼容使用。
    - 会话内 working state 优先通过 `Current agent state` / `Shared session state` 两个新段落承接。
  - 同步更新 `memory-editor` skill，明确“当前任务目标/下一步/working notes 用 `state_set`，不是 `memory_write`”。
  - 补充测试覆盖：
    - `search_context_memories(...)` 不扫描 `agent_short`。
    - `ContextAssembler` 不再把 `agent_short` 组装进 `Relevant memories`。
- 影响范围：
  - runtime 自动上下文的 memory 语义进一步收窄，更接近“长期互动经验”。
  - `memory_search` 工具仍可显式查到 `agent_short`，因此当前不会破坏调试和遗忘/更新工作流。
  - `agent_short` 尚未迁移出 memory 存储层；这一步只是先从“自动召回语义”上剥离。
- 验证结果：
  - `uv run pytest tests/test_memory_manager.py tests/test_context_assembler.py tests/test_tool_registry.py tests/test_agent_runtime.py`：通过（`39 passed in 0.18s`）
  - `uv run mypy app/runtime/memory_manager.py app/runtime/context_assembler.py tests/test_memory_manager.py tests/test_context_assembler.py tests/test_tool_registry.py tests/test_agent_runtime.py tests/helpers.py`：通过（`Success: no issues found in 7 source files`）
  - `uv run pytest -q`：通过（`94 passed in 0.60s`）

28. [完成] 落地 Memory Admission V1：对 `memory_write` 增加运行时准入拦截。
- 说明：
  - 新增 `app/memory/admission.py`，引入显式 `MemoryAdmissionDecision / MemoryAdmissionResult / evaluate_memory_admission(...)`。
  - `MemoryManager.write_memory(...)` 现在在写 candidate 前先跑 admission。
  - 第一版准入策略采用“保守硬拦截”：
    - 明显属于 session working state 的内容：拒绝写 memory，并提示改用 `state_set`
    - 明显属于原始文件/工具输出的内容：拒绝写 memory，并提示先提炼稳定经验
  - `MemoryWriteTool` 增加用户可读的错误透传，避免 admission 被包装成模糊异常。
  - 同步更新：
    - `app/tools/builtins.py` 中 `memory_write` 工具描述
    - `app/skills/tools/SKILL.md`
    - `app/skills/memory/SKILL.md`
    - `app/skills/memory-editor/SKILL.md`
  - 新增测试：
    - `tests/test_memory_admission.py`
    - `tests/test_memory_manager.py` 中 admission 拒绝 working state / raw JSON blob
    - `tests/test_tool_registry.py` 中 `memory_write` 拒绝 working state 并指向 `state_set`
- 影响范围：
  - `memory` 与 `state` 的边界首次在运行时被硬编码，不再只靠 skill 提示约束。
  - `memory_search`、`memory_forget`、`memory_update` 仍沿用现有显式检索链路；本阶段未改它们的读取模型。
  - admission 当前仍是规则式 V1，尚未引入更细的 canonicalization 或 confirmation 流程。
- 验证结果：
  - `uv run pytest tests/test_memory_admission.py tests/test_memory_manager.py tests/test_tool_registry.py tests/test_context_assembler.py tests/test_agent_runtime.py`：通过（`45 passed`）
  - `uv run mypy app/memory/admission.py app/runtime/memory_manager.py app/tools/builtins.py app/memory/__init__.py tests/test_memory_admission.py tests/test_memory_manager.py tests/test_tool_registry.py tests/test_context_assembler.py tests/test_agent_runtime.py tests/helpers.py`：通过（`Success: no issues found in 10 source files`）
  - `uv run pytest -q`：通过（`100 passed in 0.64s`）

29. [完成] 落地 Classification / Canonicalization Metadata V1：为可接受 memory 增加结构化归类元信息。
- 说明：
  - 新增 `app/memory/classification.py`，提供 `MemoryClassification` 与 `classify_memory(...)`。
  - `app/memory/intake.py` 在 `build_candidate_request(...)` 阶段加入结构化归类，并把结果写入 metadata：
    - `kind`
    - `source_kind`
    - `canonical_key`
    - `normalized_value`
    - `subject_kind`
    - `classification_version`
  - 当前第一版先覆盖几类高价值 key：
    - `preferred_name`
    - `preferred_language`
    - `response_style`
    - `preferred_format`
    - `disliked_format`
    - `long_term_goal`
    - `primary_stack`
    - `interaction_style`
  - 设计上采取“metadata 先行”：
    - 暂不修改 `MemoryRecord` 顶层 schema
    - 先让 consolidation / 检索 / 迁移链路可以消费结构化 metadata
    - 后续再决定何时把这些字段提升为正式 schema 字段
  - 新增测试：
    - `tests/test_memory_classification.py`
    - `tests/test_memory_manager.py` 校验结构化 metadata 已写入 record
- 影响范围：
  - 可接受的 memory 写入后，不再只是“content + tags”，而是开始具备结构化归类信号。
  - 这为后续基于 `canonical_key` 的 upsert / conflict / reinforce 打下基础。
  - 当前读取接口仍主要返回原始 memory 内容；结构化 metadata 先用于内部治理与后续演进。
- 验证结果：
  - `uv run pytest tests/test_memory_classification.py tests/test_memory_admission.py tests/test_memory_manager.py tests/test_context_assembler.py tests/test_tool_registry.py tests/test_agent_runtime.py`：通过（`49 passed`）
  - `uv run mypy app/memory/classification.py app/memory/intake.py app/memory/__init__.py app/runtime/memory_manager.py tests/test_memory_classification.py tests/test_memory_admission.py tests/test_memory_manager.py tests/test_context_assembler.py tests/test_tool_registry.py tests/test_agent_runtime.py tests/helpers.py`：通过（`Success: no issues found in 11 source files`）
  - `uv run pytest -q`：通过（`104 passed in 0.62s`）

30. [完成] 落地 Canonical Dedup V1：使用 `canonical_key + normalized_value` 做长期记忆同语义去重。
- 说明：
  - `app/memory/consolidation.py` 新增 canonical identity 去重逻辑：
    - 批内若 `canonical_key + normalized_value` 相同，则按同一语义候选合并。
    - 跨轮若目标作用域已存在相同 `canonical_key + normalized_value` 的 active record，则跳过重复写入。
  - `app/memory/contracts.py` / `app/memory/stores/jsonl_file_store.py` 新增 `count_active_records_by_canonical_value(...)`，用于查询既有 active record 中的 canonical identity。
  - 当前第一版只做“同语义去重”：
    - 不再仅依赖 `content_hash`
    - 但还不处理“同 `canonical_key` 不同 `normalized_value`”的冲突覆盖
  - 新增测试 `tests/test_memory_consolidation.py::test_consolidation_dedupes_semantic_duplicates_by_canonical_key`，验证不同措辞但同一称呼偏好的重复写入会被合并。
- 影响范围：
  - 长期 memory 现在开始具备语义级别的去重能力，能减少“同一偏好/称呼只是换了句式就写出多条 record”的噪音。
  - 这为后续做 `canonical_key` 级 upsert / conflict resolution 提供了更稳的基础。
  - 当前未引入旧 record 的自动 supersede；冲突覆盖仍是后续阶段。
- 验证结果：
  - `uv run pytest tests/test_memory_consolidation.py tests/test_memory_classification.py tests/test_memory_manager.py`：通过（`18 passed`）
  - `uv run mypy app/memory/contracts.py app/memory/stores/jsonl_file_store.py app/memory/consolidation.py tests/test_memory_consolidation.py tests/test_memory_classification.py tests/test_memory_manager.py`：通过（`Success: no issues found in 6 source files`）
  - `uv run pytest -q`：通过（`105 passed in 0.63s`）

31. [完成] 落地 Canonical Supersede V1：同 `canonical_key` 的新值可接管旧值，并引入来源优先级。
- 说明：
  - `app/memory/contracts.py` / `app/memory/stores/jsonl_file_store.py` 新增两类能力：
    - `list_active_records_by_canonical_key(...)`
    - `archive_records_by_memory_ids(...)`
  - `app/memory/consolidation.py` 新增 canonical conflict 处理：
    - 若新候选与既有 active record 具有相同 `canonical_key`、不同 `normalized_value`，则进入 supersede 判定。
    - 新候选来源权重不低于旧记录时，归档旧记录并写入新记录。
    - 新候选来源权重更低时，拒绝覆盖，并将本轮记为 `conflicts`。
  - 当前已落地来源优先级顺序：
    - `system_policy`
    - `explicit_user_rule`
    - `explicit_user`
    - `user_feedback`
    - `tool_verified`
    - `repeated_behavior`
    - `assistant_inferred`
  - supersede 的审计链路：
    - 旧记录 metadata 写入 `superseded_by_memory_id` / `superseded_by_normalized_value`
    - 新记录 `parent_memory_id` 指向上一条被替代记录
  - 新增测试：
    - `test_consolidation_supersedes_old_canonical_value_with_new_value`
    - `test_consolidation_does_not_let_low_priority_source_override_explicit_user`
- 影响范围：
  - memory 已经从“只会去重”提升到“可以按 canonical key 做受控更新”。
  - 用户明确更新称呼/偏好这类场景，现已能形成更干净的单条 active 语义，而不是把旧值和新值都保留为 active。
  - 当前仍未实现更细粒度的 `contradicted/suppressed` 正式状态；本阶段先使用 `archived` 作为被替代旧值的隐藏状态。
- 验证结果：
  - `uv run pytest tests/test_memory_consolidation.py tests/test_memory_classification.py tests/test_memory_manager.py`：通过（`20 passed`）
  - `uv run mypy app/memory/contracts.py app/memory/stores/jsonl_file_store.py app/memory/consolidation.py tests/test_memory_consolidation.py tests/test_memory_classification.py tests/test_memory_manager.py`：通过（`Success: no issues found in 6 source files`）
  - `uv run pytest -q`：通过（`107 passed in 0.62s`）

32. [完成] 落地 `memory_update` Canonical Match V1：更新链路优先按 `canonical_key + normalized_value` 精准定位。
- 说明：
  - `app/memory/classification.py` 扩展了 preferred name 识别：
    - 除了 `以后叫我李华` / `请叫我李华`
    - 现在也能识别 `用户称呼是李华` / `用户称呼改为小李` / `用户名字叫李华`
  - `app/memory/contracts.py` / `app/memory/facade.py` 新增 facade 级 canonical 查询能力：
    - `list_active_records_by_canonical_key(...)`
    - manager 可以在不依赖 store 细节的前提下做结构化精确匹配
  - `app/runtime/memory_manager.py` 新增 `resolve_update_targets(...)`：
    - 先尝试 `canonical_exact`
    - 如果 query 无法结构化，或当前没有 active exact match，再回退到原有 `text_search`
  - `app/tools/builtins.py` 中的 `memory_update` 已切到新链路，并在结果里返回 `match_strategy`
  - 新增测试：
    - `tests/test_memory_classification.py`：陈述式 preferred name 识别
    - `tests/test_memory_manager.py`：`resolve_update_targets` 优先命中 canonical exact
    - `tests/test_tool_registry.py`：即使全文搜索会歧义，`memory_update` 仍优先锁定 canonical exact 目标
- 影响范围：
  - `memory_update` 不再完全依赖全文搜索，更新“称呼/偏好/长期事实”这类结构化记忆时更稳。
  - 当 query 同时命中多条文本相似 record 时，structured memory 现在会优先走精确定位，减少误改 active memory 的风险。
  - 文本搜索仍保留为兜底路径，兼容尚未 canonicalized 的旧记录和自由文本记忆。
- 验证结果：
  - `uv run pytest tests/test_memory_classification.py tests/test_memory_manager.py tests/test_tool_registry.py -q`：通过（`37 passed`）
  - `uv run mypy app/memory/classification.py app/memory/contracts.py app/memory/facade.py app/runtime/memory_manager.py app/tools/builtins.py tests/test_memory_classification.py tests/test_memory_manager.py tests/test_tool_registry.py`：通过（`Success: no issues found in 8 source files`）
  - `uv run pytest -q`：通过（`110 passed`）

33. [完成] 落地 `memory_update` Canonical Direct V2：canonical memory 更新不再先删旧值，而是直接走 supersede / dedupe / conflict。
- 说明：
  - `app/runtime/memory_manager.py` 新增 `MemoryWriteResult` 和 `write_memory_with_result(...)`：
    - 写入链路现在可以向上层返回 `ConsolidateResult`
    - 工具层可以根据 `written_records / merged_records / conflicts` 判断本次更新到底是 supersede、no-op 还是被阻止
  - `app/tools/builtins.py` 中的 `memory_update` 已拆成两条路径：
    - target 带 `canonical_key` 时：
      - 不再执行 `forget -> write`
      - 直接提交新 candidate，让 consolidation 决定 `supersede / semantic_noop / source_priority_conflict`
    - target 不带 `canonical_key` 时：
      - 仍保留旧的 replace fallback（`forget -> write`）
  - 这一步还新增了 `update_mode` 返回值：
    - `canonical_supersede`
    - `canonical_direct`
    - `replace_rewrite`
  - 同步修正了 `app/memory/classification.py` 的 `source_kind` 推断：
    - 之前带 `system_policy` / `explicit_user_rule` tag 的记录，会错误保留为工具 source 名
    - 现在会被正确归类为 `system_policy` / `explicit_user_rule`
    - 这样 consolidation 的来源优先级才真正可靠
  - 新增测试：
    - `tests/test_tool_registry.py`：canonical update 会保留 supersede 审计链，而不是先删旧值
    - `tests/test_tool_registry.py`：`system_policy` 级 canonical memory 不能被 `memory_update` 低优先级覆盖
    - `tests/test_memory_classification.py`：`system_policy` tag 能正确写成 `source_kind=system_policy`
- 影响范围：
  - canonical memory 的更新现在真正走“受控更新”链路，而不是假装更新、实际重写。
  - `memory_update` 不会再因为先归档旧值而绕过来源优先级校验。
  - supersede 审计链 (`parent_memory_id` / `superseded_by_*`) 在工具更新场景下也能保持完整。
  - 非结构化旧 memory 暂时仍保留 replace fallback，兼容历史数据。
- 验证结果：
  - `uv run pytest tests/test_tool_registry.py tests/test_memory_manager.py tests/test_memory_classification.py -q`：通过（`39 passed`）
  - `uv run mypy app/memory/classification.py app/runtime/memory_manager.py app/tools/builtins.py tests/test_tool_registry.py tests/test_memory_manager.py tests/test_memory_classification.py`：通过（`Success: no issues found in 6 source files`）
  - `uv run pytest -q`：通过（`112 passed`）

34. [完成] 落地 Legacy Structured Backfill V1：旧 memory 在首次 update 时自动补齐结构化 metadata。
- 说明：
  - `app/memory/contracts.py` / `app/memory/facade.py` / `app/memory/stores/jsonl_file_store.py` 新增 `refresh_record_metadata(...)`：
    - 用于对既有 record 做窄范围 metadata patch
    - 当前只服务于 memory 子系统内部，不暴露给通用工具层
  - `app/runtime/memory_manager.py` 新增 `ensure_structured_metadata(...)`：
    - 对选中的 target record 重新跑 classification
    - 仅在缺失结构化字段时回填：
      - `kind`
      - `source_kind`
      - `canonical_key`
      - `normalized_value`
      - `subject_kind`
      - `classification_version`
  - `app/tools/builtins.py` 中的 `memory_update` 现在会在定位到 target 后，先尝试对 legacy record 做 metadata backfill，再判断是否能走 canonical direct path。
  - 这样旧数据也能逐步迁入新语义，不必等离线全量迁移后才享受 canonical supersede / source priority。
  - 新增测试：
    - `tests/test_memory_manager.py`：legacy record metadata backfill
    - `tests/test_tool_registry.py`：legacy name memory 首次 update 即转入 canonical supersede
- 影响范围：
  - `replace_rewrite` fallback 再次收窄：一部分“旧但可识别”的 memory，不再走旧重写路径。
  - 老 record 的结构化语义会在首次被编辑时就地补齐，减少历史数据长期卡在旧模型里的问题。
  - 当前 backfill 仍是按需、单条触发；还没有做离线批量迁移。
- 验证结果：
  - `uv run pytest tests/test_memory_manager.py tests/test_tool_registry.py -q`：通过（`36 passed`）
  - `uv run mypy app/memory/contracts.py app/memory/facade.py app/memory/stores/jsonl_file_store.py app/runtime/memory_manager.py app/tools/builtins.py tests/test_memory_manager.py tests/test_tool_registry.py`：通过（`Success: no issues found in 7 source files`）
  - `uv run pytest -q`：通过（`114 passed`）

35. [完成] 落地 Offline Structured Backfill V1：提供批量 canonicalize 现存 memory 的离线迁移能力。
- 说明：
  - 新增批量 backfill 模型：
    - `MemoryStructuredBackfillRequest`
    - `MemoryStructuredBackfillResult`
  - `app/memory/metadata_refresh.py` 新增 `build_metadata_refresh_patch(...)`：
    - 用于统一“缺失字段补齐 + 少量已知脏值修正”的策略
    - 当前已覆盖：
      - 缺失的 `kind / source_kind / canonical_key / normalized_value / subject_kind / classification_version`
      - 旧实现遗留的 `source_kind=memory_write_tool/memory_update_tool/...` 修正
  - `app/memory/stores/jsonl_file_store.py` 新增 `backfill_structured_metadata(...)`：
    - 按 scope / agent / session 过滤扫描现存 records
    - 对可识别但缺失结构化 metadata 的 legacy records 做就地 patch
    - 支持对 archived records 一并回填
    - 默认跳过 deleted records
    - 写入 `ops/structured_backfill.log.jsonl`
  - `app/memory/lifecycle.py` / `app/memory/facade.py` 已接出统一生命周期入口。
  - 新增 CLI：
    - `python -m app.memory.backfill_cli --root-dir data/memory_v2`
    - 支持 `--scope`、`--agent-id`、`--session-id`、`--include-deleted`
  - 新增测试：
    - `tests/test_memory_structured_backfill.py`
    - 覆盖 agent_long 批量 patch、archived record patch、deleted skip、stale source_kind 修复、short session 定向 backfill
- 影响范围：
  - memory 迁移不再只依赖运行时“首次编辑时在线回填”，现在可以对现存数据做批量治理。
  - 这一步会显著减少 legacy records 命中 `replace_rewrite` fallback 的概率。
  - 当前迁移仍是保守模式：
    - 只修补缺失结构化字段
    - 只修正少数已知 stale metadata
    - 不主动重写已有 canonical value
- 验证结果：
  - `uv run pytest tests/test_memory_structured_backfill.py tests/test_memory_manager.py tests/test_tool_registry.py -q`：通过（`38 passed`）
  - `uv run mypy app/memory/models.py app/memory/metadata_refresh.py app/memory/contracts.py app/memory/lifecycle.py app/memory/facade.py app/memory/stores/jsonl_file_store.py app/memory/backfill_cli.py app/runtime/memory_manager.py app/tools/builtins.py tests/test_memory_structured_backfill.py tests/test_memory_manager.py tests/test_tool_registry.py`：通过（`Success: no issues found in 12 source files`）
  - `uv run python -m app.memory.backfill_cli --root-dir /tmp/memory_backfill_cli_smoke --scope agent_long`：可执行，输出 JSON summary
  - `uv run pytest -q`：通过（`116 passed`）

36. [完成] 落地 Canonical-Aware Retrieval V1：读取链路开始优先利用结构化 metadata 排序。
- 说明：
  - `app/memory/retrieval.py` 现在不再只按 `confidence / importance / updated_at` 排序。
  - 新增 query-aware rerank：
    - 先对 query 做轻量 canonical intent 识别
    - 如果 query 能映射到 `canonical_key + normalized_value`，则精确匹配该 canonical identity 的 record 会获得最高优先级
    - 如果 query 呈现明确 name intent（例如 `你叫什么名字`），则 `preferred_name` 类型 record 会优先于普通文本命中
  - 当前第一版先覆盖：
    - `canonical exact` 查询优先
    - `preferred_name` name-intent 查询优先
  - 在实现这一步时顺手修复了一个分类 bug：
    - 之前 `这个项目名字叫珍格格` 这类文本会被误判为 `preferred_name`
    - 现在 statement-form 的名字规则已收窄到句首/用户语境，避免把项目名、文件名等误当成用户称呼
  - 新增测试：
    - `tests/test_memory_manager.py`：`memory_search` 对 name-intent 与 canonical exact query 的排序
    - `tests/test_context_assembler.py`：`Relevant memories` 中优先注入 `preferred_name`
    - `tests/test_memory_classification.py`：项目名不再误分类为 `preferred_name`
- 影响范围：
  - `memory_search` 和 runtime prompt 注入现在开始消费结构化 metadata，不再完全依赖纯文本命中顺序。
  - 这会降低“query 命中多个文本相似 memory 时，长期偏好反而被普通事实压后”的情况。
  - 当前仍是 rerank V1，不是 lane-based retrieval；文本 fallback 仍然保留。
- 验证结果：
  - `uv run pytest tests/test_memory_classification.py tests/test_memory_manager.py tests/test_context_assembler.py -q`：通过（`26 passed`）
  - `uv run mypy app/memory/classification.py app/memory/retrieval.py tests/test_memory_classification.py tests/test_memory_manager.py tests/test_context_assembler.py tests/test_tool_registry.py`：通过（`Success: no issues found in 6 source files`）
  - `uv run pytest -q`：通过（`120 passed`）
