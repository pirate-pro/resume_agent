# 2026-04-23 运行时问题复盘：SSE 流式与 Tool Loop

## 1. 问题背景
当前系统在 `/api/chat/stream` 路径上虽然使用了 SSE，但用户反馈在工具调用阶段仍然有明显“卡住”感，尤其是：
- 模型先发起工具调用（例如文件检索），工具执行几秒后才继续；
- 前端在这几秒里看不到正文增量输出；
- 最终答案常常在 run 结束后一次性分片喷出，流式体验不自然。

这会带来两个直接后果：
1. 用户误以为系统无响应；
2. SSE 的价值被削弱，首 token 体验差。

---

## 2. 核心问题与根因

### 问题 A：`chat_stream` 依赖轮询 JSONL 事件
**现象**
- `chat_stream` 通过 `list_events(session_id)` 每 120ms 轮询一次，读取新增事件后再推 SSE。

**根因**
- 实时推送链路不直连 runtime，而是“runtime 写盘 -> service 轮询读盘 -> SSE 推送”。
- 事件传输多了一层存储中转，天然有延迟与抖动。

**影响**
- 高并发或 IO 抖动下，事件节奏不稳定。
- 架构复杂，后续做多 agent 事件编排会更难。

---

### 问题 B：答案增量是“伪流式”
**现象**
- 之前 `answer_delta` 在 `run_task` 完成后才按固定长度切块推送。
- 工具循环期间没有真实 token 级正文输出。

**根因**
- runtime 只有同步 `run()`，直到完整闭环结束才返回 `AgentRunOutput`。
- `chat_stream` 只能在拿到最终 `answer` 后再分块推送。

**影响**
- 首 token 延迟被放大到“整轮工具 + 整轮模型”后。
- 用户感知是“先等待，再一次性输出”。

---

### 问题 C：模型流式能力缺失
**现象**
- `OpenAICompatibleClient` 只有同步 `generate()`。

**根因**
- 未实现 `stream=true` 的 SSE 解析。
- 无法在模型返回时即时将 `delta.content` 转发给前端。

**影响**
- 即使 API 用了 SSE，也只是“外层流”，不是“模型真流”。

---

## 3. 解决方案（本次已落地）

### 方案 1：引入 `EventChannel`，移除轮询链路
新增 `app/runtime/event_channel.py`：
- 使用 `asyncio.Queue` 做运行时事件通道；
- `emit/emit_run_event/listen/close` 完整生命周期；
- 统一事件序列化为前端可直接消费格式。

设计要点：
- 持久化（JSONL）继续保留；
- 实时链路不再依赖“写盘后再读盘”；
- `run_task` 结束或异常时都显式 `close()`，防止监听方阻塞。

---

### 方案 2：扩展协议，支持流式模型输出
更新 `app/domain/protocols.py`：
- 新增 `StreamChunk`；
- 新增 `ChatModelClient.generate_stream(...)`。

`StreamChunk` 字段：
- `delta`：正文增量；
- `tool_calls`：流结束后收敛出的工具调用；
- `finished`：本轮流结束标识；
- `has_tool_call_delta`：是否出现过工具调用增量。

---

### 方案 3：实现 `OpenAICompatibleClient.generate_stream`
更新 `app/infra/llm/openai_compatible_client.py`：
- 基于 `httpx.AsyncClient.stream` 解析 SSE；
- 支持 tool call 分片累积（按 `index` 聚合 `name/arguments`）；
- 兼容 `[DONE]` 与尾块无空行场景；
- 维持 400 auto-tool-choice 自动回退逻辑；
- 对非 `text/event-stream` 返回做兜底解析（按普通 JSON 完成一次 chunk 输出），避免供应商不规范响应导致空回答。

---

### 方案 4：新增 `AgentRuntime.run_stream`
更新 `app/runtime/agent_runtime.py`：
- 新增异步 `run_stream(run_input, channel)`；
- 工具执行通过 `await asyncio.to_thread(...)` 桥接，避免一次性改造全部工具为 async；
- 每轮模型调用中实时转发 `answer_delta`；
- 检测到 tool call 后，发送 `answer_reset` 回滚本轮临时正文（避免“先吐字后转工具”污染 UI）；
- 关键生命周期事件仍通过 `EventRecorder` 落盘，并同步推送 `run_event`。

保留：
- 旧 `run()` 同步路径继续可用，兼容非流式调用。

---

### 方案 5：`chat_stream` 改为直连 runtime 事件
更新 `app/services/chat_service.py`：
- 删除 120ms 轮询 `list_events` 逻辑；
- 创建 `EventChannel`，直接 `async for item in channel.listen()` 向 SSE 输出；
- run 完成后只发 `done`；
- 异常路径确保关闭 channel 和取消任务。

---

### 方案 6：前端兼容 `answer_reset`
更新 `app/web/assets/app.js`：
- 在 SSE 事件处理新增 `answer_reset` 分支；
- 收到后清空当前 assistant 正文缓冲，避免工具轮次污染最终回答展示。

---

## 4. 验证结果
已执行：
- `uv run pytest -q`
- `uv run python -m compileall -q app tests`

结果：
- 全量测试通过（`54 passed`）；
- 编译检查通过。

---

## 5. 本次改动文件清单
- `app/runtime/event_channel.py`（新增）
- `app/domain/protocols.py`
- `app/infra/llm/openai_compatible_client.py`
- `app/runtime/event_recorder.py`
- `app/runtime/agent_runtime.py`
- `app/services/chat_service.py`
- `app/web/assets/app.js`
- `tests/helpers.py`

---

## 6. 后续可继续优化（本次未做）
1. **心跳事件**：长工具执行期间周期性推 `heartbeat/status`，提升“活着”感知。
2. **队列拥塞策略**：`EventChannel` 满载时做低优先级 delta 限流，避免内存膨胀。
3. **流式 tool-call 策略增强**：对 provider 差异（字段缺失/finish_reason 异常）补更细容错。
4. **`run`/`run_stream` 内核收敛**：进一步抽共享核心，降低双路径维护成本。

