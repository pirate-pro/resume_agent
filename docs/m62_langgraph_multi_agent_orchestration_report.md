# M62 LangGraph 多 Agent 编排解决报告

> 状态：实现完成，已通过本地后端、Flutter 和 P0 live-smoke 验证。待代码审阅后合入主线。

## 1. 当前阶段

本分支已经把首条确定性多 Agent 求职流程迁到 LangGraph：

```text
prepare_inputs
  -> resume_analysis + jd_analysis 并发
  -> job_fit_analysis
  -> project_confirmation interrupt
  -> career_application_create
  -> completed
```

已经具备：

- 静态任务图，不让模型生成 DAG；
- ResumeProfile / JDAnalysis 并发执行；
- JobFitReport 只在前置任务成功后启动；
- 任务失败后进入可恢复 interrupt；
- 用户重试时只重跑失败任务；
- 已完成任务通过 GraphAgentTaskStore 复用；
- SQLite 任务账本和 LangGraph checkpoint 分离；
- 前端展示多 Agent 进度、失败任务、重试入口和确认入口；
- 旧 `delegate_agents` 路径保持兼容。

## 2. 方向判断

方向是合适的，但边界要收住。

LangGraph 适合承接“长流程、可暂停、可恢复、可重试、有人审确认”的确定性 workflow。M62 迁移的求职分析链路正好满足这些条件：节点固定、依赖清晰、产物明确、最终写入需要用户确认。

不建议把普通聊天、简单 RAG 读取、单次工具调用都塞进 LangGraph。否则会把短链路复杂化，并且让模型对话状态、工具幂等状态、产品记录状态混在一起。

## 3. LangGraph 边界

LangGraph 负责：

- workflow phase；
- fan-out / join；
- checkpoint；
- interrupt / resume；
- 失败任务选择；
- 依赖任务调度；
- 最终确认和结束条件。

Child Agent 负责：

- 专业推理；
- 工具调用；
- 单个任务 attempt 内的执行闭环；
- 产物生成。

GraphAgentTaskStore 负责：

- task attempt；
- queued / running / completed / failed 状态；
- lease；
- child_run_id；
- output artifact refs / product refs。

ToolGateway / ToolCallLedger 负责：

- 工具参数校验；
- 副作用幂等；
- 业务写入事实；
- 写入护栏。

ProductStore / SessionArtifact 负责：

- 最终可展示、可复用的产品记录；
- 用户可预览 artifact；
- 工作台真实状态。

明确不做：

- 不恢复 child-agent 内部某一轮 LLM/tool loop；
- 不开放用户自定义 DAG；
- 不让模型提交 `depends_on`；
- 不把 LangGraph checkpoint 当产品数据源；
- 不用 LangGraph 替换所有 Agent runtime。

## 4. 已发现并修复的问题

1. Graph retry 复用了旧 ResumeProfile。
   - 原因：`WorkflowRuntimeGuard` 的业务去重会在 graph task retry 时复用旧产品记录。
   - 处理：graph task attempt 绕过相关 save 工具的旧记录复用，让重试真正生成新 ResumeProfile / JDAnalysis / JobFitReport。

2. ResumeProfile 质量门失败后不能有效推进。
   - 现象：教育经历缺失后重试仍拿到同一个旧 profile。
   - 处理：修复 attempt-scoped 写入复用后，重试成功生成包含教育经历的新 profile。

3. JobFitReport 使用了过宽的 product refs。
   - 原因：子任务执行器把 child run 中读到的所有产品引用都记入任务结果。
   - 处理：按任务输出合同过滤，只持久化本任务应产出的 refs。

4. 前端重试/确认提交中状态不清晰。
   - 处理：interrupt panel 提交期间显示“流程正在执行，当前确认项会在执行完成后自动更新。”

5. Flutter 测试仍断言旧产品页文案。
   - 处理：对齐当前产品工作区真实文案和“生成岗位定制简历”确认弹窗流程。

6. 模型容量错误不可观测。
   - 现象：上游返回 `Selected model is at capacity. Please try a different model.` 时，前端只看到失败，不知道是哪个模型/端点。
   - 处理：LLM 客户端现在会把 429、503 和 capacity/rate-limit/overloaded 类 provider detail 归类为“模型暂不可用，可重试或切换模型”，并带上 `model` 与脱敏 `endpoint`。
   - 当前判断：该问题发生在主模型 `mimo-v2.5-pro` 调用链路，不是 LangGraph 或 RAG 自身逻辑错误。

## 5. Live-smoke 证据

M62 手工全链路：

- session: `sess_de56fe3b358a`
- workflow: `wf_c6f755e3bb32`
- 修复后 resume attempt 7 成功；
- 新 ResumeProfile: `resume_profile_81881b96854d`
- JobFitReport: `fit_8b1a76fa8289`
- 匹配分：82/100，recommendation: recommended；
- 用户确认后创建 `application_wf_c6f755e3bb32`；
- Workbench API 可读到 1 条 active application。

P0 高并发 live-smoke：

```text
tools/smoke_live_matrix.py --all-p0 --runs 1 --concurrency 3 --stream
```

结果：

- 7 runs；
- 7 success；
- 0 failed；
- avg 69.41s；
- max 269.46s；
- harmful_duplicate_runs=0/7；
- hidden_runs=0/7。

覆盖场景：

- chat_only；
- memory_write；
- note_write；
- rag_read_only；
- main_resume_child；
- main_job_child；
- career_full。

最终报告：

- `/tmp/m62_final_p0_matrix_report.json`
- data_dir: `/tmp/resume_agent_m62_final_p0_matrix_20260616`
- `career_full` session: `sess_live_career_001_70d3b1f7`
- `career_full` 创建 `application_ai_8d96483a` 和 `resume_version_a6a98c30683b`

模型切换后轻量 smoke：

```text
tools/smoke_live_matrix.py --scenario chat_only --scenario note_write --runs 1 --concurrency 2 --stream
```

结果：

- 2 runs；
- 2 success；
- 0 failed。

UI 截图：

- `/tmp/m62-ui-desktop.png`
- `/tmp/m62-ui-mobile.png`
- `/tmp/m62-live-project-confirmation-fixed.png`
- `/tmp/m62-live-quality-gate.png`

Release Web UI 验证：

- release 站点：`flutter_app/build/web`
- 截图目录：`/tmp/resume-agent-ui-release-verify-20260616`
- 覆盖页面：总览、Agent 助手、求职项目、简历资料、JD 匹配、学习计划、笔记、移动端总览
- 最终结果：无 console error，无 failed request
- 总览重截：`/tmp/resume-agent-ui-release-verify-20260616/desktop-overview-retry.png`
- Agent 助手：`/tmp/resume-agent-ui-release-verify-20260616/desktop-agent-chat.png`
- 简历资料：`/tmp/resume-agent-ui-release-verify-20260616/desktop-resume.png`
- 移动端：`/tmp/resume-agent-ui-release-verify-20260616/mobile-overview.png`

UI 验证期间发现并修复：

- Agent 助手右侧推荐操作卡片在 1440x1000 下有轻微 RenderFlex overflow；
- 简历资料页摘要卡片高度不足，真实文案下有 RenderFlex overflow；
- 修复提交：`8166393 fix: prevent workspace rail overflow`。

## 6. 本地验证

后端：

```text
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy app tests
```

结果：

- pytest 全量通过；
- mypy 355 个 source files 通过。

LLM 客户端专项：

```text
.venv/bin/python -m pytest tests/test_openai_compatible_client.py tests/test_openai_compatible_client_stream.py -q
.venv/bin/python -m mypy app/infra/llm/openai_response.py app/infra/llm/openai_compatible_client.py tests/test_openai_compatible_client.py
```

结果：

- 10 tests passed；
- mypy passed。

Flutter：

```text
flutter test
flutter analyze
flutter build web --release
```

结果：

- Flutter tests 全量通过；
- analyze 无问题；
- release web build 成功。

UI 修复后补充验证：

```text
flutter test test/home_screen_test.dart test/career_workbench_page_test.dart test/resume_library_page_test.dart
flutter analyze
flutter build web --release
```

结果：

- 7 个相关 Flutter tests 通过；
- analyze 无问题；
- release web build 成功。

已知非阻断告警：

- `file_picker` 的 linux/macos/windows default_package 声明告警；
- web build 的 wasm dry-run 提示 `dart:html` 不兼容；
- root 用户运行 Flutter 的提示。

这些不影响当前测试和 web release build。

## 7. 剩余风险

1. 上游模型容量不可由本服务修复。
   - 现在只能更准确地识别、记录和展示；
   - 真正解决需要切换模型、降并发、限流或增加 provider fallback。

2. M62 已验证首条多 Agent 求职分析 workflow。
   - 定制简历、学习计划、面试复盘还没有迁进 LangGraph；
   - 后续应按“固定流程 + 明确中断点 + 明确最终副作用”的标准逐条迁移。

3. 当前不恢复 child-agent 内部 LLM/tool loop。
   - 进程中断时，恢复粒度是 task attempt；
   - 已完成 task 不重跑，失败或 running 超时 task 重新进入 attempt。

4. RAG MCP 已经具备拆分路径，但普通服务内 Agent 默认路径仍需按场景显式切换。
   - 不应把 M62 和 RAG MCP 的默认路由混为一件事。

## 8. 下一步建议

当前分支不合并到 `main`，先保留为可审阅状态。

后续如果继续处理模型容量问题，建议作为独立任务评估 provider fallback、模型降级、限流和并发控制，不混进 M62。
