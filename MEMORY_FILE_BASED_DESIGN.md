# Memory 子系统（文件存储版）设计方案

## 1. 目标与约束

- 目标：把 `memory` 从“工具级能力”升级为“核心子系统”，支持后续多 Agent 扩展。
- 约束：暂不使用数据库，全部基于文件存储（JSON/JSONL + 本地索引文件）。
- 原则：
  - 高内聚：检索、写入、合并、遗忘都在 Memory 子系统内部完成。
  - 低耦合：Runtime/Tool 只依赖 `MemoryFacade`，不直接依赖具体存储。
  - 可演进：后续替换为 DB/向量库时，上层接口保持稳定。

---

## 2. 作用域与层级

Memory 分三层：

1. `shared_long`（全局共享长期记忆）
- 面向所有 Agent。
- 保存稳定事实、长期偏好、跨任务经验、项目约束。

2. `agent_long`（Agent 私有长期记忆）
- 按 `agent_id` 隔离。
- 保存该 Agent 的长期工作经验、策略偏好。

3. `agent_short`（Agent 私有短期记忆）
- 按 `agent_id + session_id` 隔离。
- 保存当前任务计划、临时推理、最近工具结果。
- 必须带 TTL（过期自动失效/清理）。

默认读取优先级：`agent_short -> agent_long -> shared_long`。

---

## 3. 文件存储布局（无数据库）

根目录基于现有 `data/` 扩展：

```text
data/
  memory_v2/
    shared/
      long.jsonl
      index.json
    agents/
      <agent_id>/
        long.jsonl
        long.index.json
        short/
          <session_id>.jsonl
          <session_id>.index.json
    candidates/
      pending.jsonl
      processed/
        YYYY-MM-DD.jsonl
    ops/
      consolidation.log.jsonl
      lifecycle.log.jsonl
      errors.log.jsonl
```

说明：

- `*.jsonl`：append-only 事件/记录，保证写入简单与可追溯。
- `*.index.json`：轻量倒排或统计索引（可重建），用于加速关键词检索。
- `candidates/`：Agent 写入候选记忆，不直接落最终层。
- `ops/`：治理过程审计日志（去重、合并、冲突处理、遗忘决策）。

---

## 4. 数据模型（文件版）

统一记录模型（JSON 行）：

```json
{
  "memory_id": "mem_xxx",
  "scope": "shared_long|agent_long|agent_short",
  "owner_agent_id": "agent_main",
  "session_id": "sess_xxx",
  "memory_type": "fact|preference|constraint|plan|scratch",
  "content": "文本内容",
  "tags": ["tag1", "tag2"],
  "importance": 0.82,
  "confidence": 0.91,
  "status": "active|archived|deleted",
  "created_at": "2026-04-21T00:00:00Z",
  "updated_at": "2026-04-21T00:00:00Z",
  "expires_at": "2026-04-22T00:00:00Z",
  "source_event_id": "evt_xxx",
  "source_agent_id": "agent_main",
  "version": 1,
  "parent_memory_id": null,
  "content_hash": "sha256:..."
}
```

候选记录模型（`candidates/pending.jsonl`）：

```json
{
  "candidate_id": "cand_xxx",
  "agent_id": "agent_main",
  "session_id": "sess_xxx",
  "scope_hint": "agent_short",
  "memory_type": "fact",
  "content": "候选内容",
  "tags": ["from_tool"],
  "confidence": 0.74,
  "source_event_id": "evt_xxx",
  "idempotency_key": "agent_main:evt_xxx:hash",
  "created_at": "2026-04-21T00:00:00Z"
}
```

---

## 5. 子系统接口（Facade）

上层只依赖以下接口，不关心文件细节：

1. `read_context(req)`：按作用域与预算读取记忆上下文。
2. `write_candidate(req)`：写入候选记忆（不直接写 shared/long 最终层）。
3. `consolidate(req)`：去重、合并、冲突处理、晋升 shared。
4. `forget(req)`：软删除/归档/TTL 清理。

建议请求最小字段：

- `agent_id`
- `session_id`（可选）
- `query`
- `include_scopes`
- `limit`
- `token_budget`

---

## 6. 读取策略（按需，不全量）

流程：

1. 先从 `agent_short` 取最近且未过期记录（高优先级）。
2. 再从 `agent_long` 取相关记录。
3. 最后从 `shared_long` 取跨 Agent 共识信息。
4. 跨层合并后重排（匹配分 + 置信度 + 新鲜度）。
5. 按 `token_budget` 截断，返回可注入的 `MemoryReadBundle`。

降级策略：

- 索引损坏：自动回退全量顺序扫描（限流）。
- 某层读取失败：记录错误并跳过该层，不阻断主链路。

---

## 7. 写入与治理策略

### 7.1 写入（Agent 侧）

- Agent 仅调用 `write_candidate`，把候选记忆写入 `candidates/pending.jsonl`。
- 使用 `idempotency_key` 防重复写。

### 7.2 治理（Memory Subsystem 侧）

`consolidate` 周期/触发执行：

1. 规范化（trim、tag 标准化、hash 计算）。
2. 去重（相同 `content_hash` + 相近上下文）。
3. 合并（同主题多条合并为新版本，保留 lineage）。
4. 冲突处理（同一事实不同值时保留多版本 + 主版本选择）。
5. 晋升决策（是否进入 `shared_long`）。

晋升 `shared_long` 建议条件（可配置）：

- 重复出现次数达到阈值。
- 来自工具可验证结果或用户明确确认。
- 置信度超过阈值。

---

## 8. 遗忘与生命周期

- `agent_short`：强制 TTL（如 24h），过期后标记 `archived/deleted`。
- `agent_long/shared_long`：软删除优先，支持恢复；低价值记录转归档。
- 周期清理任务：
  - 清理过期短期记忆。
  - 压缩 JSONL（compact），剔除已删除旧版本。
  - 重建索引文件。

---

## 9. 容错与可恢复

1. 写入原子性
- 先写临时文件再 `rename`，避免半写入。
- 追加写失败不影响主对话，只记录错误日志。

2. 幂等保证
- `idempotency_key` + 最近窗口去重。

3. 索引可重建
- 索引永远是“可丢失缓存”，可由 JSONL 全量重建。

4. 错误隔离
- consolidation 或 forget 失败仅影响内存治理，不影响主聊天链路。

---

## 10. 与现有代码的映射

当前关键位置：

- `app/runtime/memory_manager.py`
- `app/runtime/context_assembler.py`
- `app/tools/builtins.py` 中 `memory_write` / `memory_search`
- `app/infra/storage/jsonl_memory_repository.py`

改造策略：

1. 新增 `app/memory/*`（Facade + 文件存储实现 + 治理模块）。
2. `MemoryManager` 改为依赖 `MemoryFacade`。
3. 工具层调用 Facade，而非直接操作 Repository。
4. 保留 `jsonl_memory_repository` 作为 legacy adapter，保证兼容旧数据。

---

## 11. 迁移计划（不影响现有模块）

### Phase A（骨架引入）
- 新增 `app/memory/` 模块与接口。
- 不改现有逻辑，仅完成编译与测试接入。

### Phase B（双写）
- `memory_write` 同时写旧仓储与 candidate 文件。
- 读取仍走旧逻辑（风险最低）。

### Phase C（灰度读切换）
- `context_assembler` 引入 `MemoryFacade.read_context`。
- 用 feature flag 控制：`MEMORY_ENGINE=v1|v2`。

### Phase D（启用治理）
- 打开 consolidation/forget 周期任务。
- 观测冲突率、命中率、重复率。

### Phase E（收敛）
- 稳定后默认 v2。
- 旧仓储退化为只读迁移兼容层。

---

## 12. 配置建议（文件版）

```env
MEMORY_ENGINE=v1
MEMORY_DUAL_WRITE=true
MEMORY_V2_ROOT=data/memory_v2
MEMORY_SHORT_TTL_SECONDS=86400
MEMORY_CONSOLIDATE_INTERVAL_SECONDS=300
MEMORY_FORGET_INTERVAL_SECONDS=600
MEMORY_SHARED_PROMOTION_MIN_CONFIDENCE=0.85
MEMORY_SHARED_PROMOTION_MIN_REPEAT=2
```

---

## 13. 测试与验收

最小验收项：

1. 单元测试
- 读写候选、去重、冲突处理、TTL 过期、索引重建。

2. 集成测试
- 单 Agent：读写与上下文注入正确。
- 多 Agent：共享/私有作用域隔离正确。

3. 故障测试
- 索引删除后可恢复。
- consolidation 失败不影响聊天主链路。

4. 回归测试
- 现有 `memory_write` / `memory_search` 行为不破坏。

---

## 14. 非目标（当前阶段不做）

- 不引入外部数据库/向量数据库。
- 不做复杂语义向量检索（后续可插拔）。
- 不做跨机器分布式一致性（先单机文件版稳定）。

