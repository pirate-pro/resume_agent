# Memory 子系统开发过程记录

## 开发约定

- 记录位置：仓库根目录（本文件）。
- 记录方式：每完成一项即追加一条，包含时间、变更内容、影响范围、验证结果。
- 当前目标：按 `MEMORY_FILE_BASED_DESIGN.md` 推进 Phase A（先搭骨架，不改变现有行为）。

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
