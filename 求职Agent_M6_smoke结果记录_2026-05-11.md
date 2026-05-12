# 求职 Agent M6 Smoke 结果记录

日期：2026-05-11

## 记录规则

只记录摘要，不粘贴完整模型回答。

每次真实 smoke 记录以下字段：

```text
时间：
命令：
runs / concurrency / max_tool_rounds：
data_dir：
总耗时：
结果：通过 / 失败
产品记录数量：
artifact 数量：
一致性检查：
质量门禁：
失败阶段：
失败工具：
关键错误：
下一步：
```

## L1 低成本真实链路

默认命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 8 \
  --data-dir data/live_career_smoke_quick
```

一致性检查：

```bash
uv run python tools/check_career_product_store.py \
  --data-dir data/live_career_smoke_quick/run_001
```

说明：M6-1 后，live smoke 会在每个 run 结束时自动执行质量门禁。独立一致性检查命令主要用于复验历史数据或排查失败。

## 记录 001

```text
时间：2026-05-11 13:33:02 +08:00
命令：uv run python tools/smoke_career_live_flow.py --runs 1 --concurrency 1 --max-tool-rounds 8 --data-dir data/live_career_smoke_quick
runs / concurrency / max_tool_rounds：1 / 1 / 8
data_dir：data/live_career_smoke_quick/run_001
session_id：sess_live_career_001_ea0a3734
总耗时：126.98s
结果：通过
产品记录数量：ResumeProfile 1，CareerProfile 1，JDAnalysis 1，JobFitReport 1，ResumeVersion 1
artifact 数量：5
一致性检查：通过，无 error finding
失败阶段：无
失败工具：无
关键错误：无
补充观察：memory facts/pending_promotions 为空，long_term 为空模板；本次只有 memory_retrieval 事件，hit_count=0，未写入求职产品内容到 memory。
下一步：不扩大批次；先分析这次输出质量和是否存在可优化的主链路问题。
```

## 记录 001 复盘补充

```text
时间：2026-05-11 13:52:00 +08:00
复盘结论：功能链路和产品记录数量通过，但定制简历版本存在可信度问题。
具体问题：ResumeVersion 的元数据包含“占位/替换为真实数据”表达；生成的简历正文出现了源材料未明确提供的量化指标，例如 85%+、<2s。
修复动作：增强 main-agent 求职产品契约，要求定制简历正文只能使用 ResumeProfile、原始简历 artifact、JDAnalysis、JobFitReport 中已经明确出现的事实；增强 checker，检查 ResumeVersion 占位表达和未证实量化指标。
复验命令：uv run python tools/check_career_product_store.py --data-dir data/live_career_smoke_quick/run_001
复验结果：失败，符合预期。旧 run 被标记出 resume_version_placeholder_text 和 resume_version_unverified_metric。
下一步：不立刻扩大 smoke 批次；先让后续低成本 L1 重新验证“可投递简历版本不能含占位和未证实指标”。
```

## M6-1 质量门禁接入

```text
时间：2026-05-11 14:10:00 +08:00
开发结论：live smoke 已接入 CareerProductStore checker。每个 run 结束后会自动检查产品记录完整性、artifact 引用、一致性 finding，以及 ResumeVersion 占位表达和未证实量化指标。
报告变化：新增“质量门禁”摘要，失败时输出 quality_error_codes，便于区分产品记录缺失、工具失败和最终简历可信度失败。
回归测试：uv run pytest tests/test_career_live_smoke_report.py tests/test_career_product_store_checker.py tests/test_career_agent_flow.py::test_career_agent_contracts_capture_live_smoke_stability_rules
测试结果：9 passed
补充验证：python -m py_compile tools/smoke_career_live_flow.py tests/test_career_live_smoke_report.py
下一步：暂不扩大 smoke 批次；下一次 L1 只跑 runs=1 concurrency=1 max_tool_rounds=8，验证模型在新契约下是否能产出可信 ResumeVersion。
```

## M7 项目动作链路验证

```text
时间：2026-05-12 08:46:18 +08:00
命令：uv run python tools/smoke_career_live_flow.py --runs 1 --concurrency 1 --max-tool-rounds 8 --project-action checklist --data-dir data/live_career_smoke_m7_project_action
runs / concurrency / max_tool_rounds：1 / 1 / 8
project_action：checklist
data_dir：data/live_career_smoke_m7_project_action/run_001
session_id：sess_live_career_001_03a5e9a8
总耗时：142.03s
结果：失败
产品记录数量：ResumeProfile 1，CareerProfile 1，JDAnalysis 1，JobFitReport 1，ResumeVersion 1，CareerApplication 1
artifact 数量：7
项目动作观察：通过。投递前检查阶段调用了 career_application_get、session_create_text_artifact、career_application_merge，并回写当前求职项目。
质量门禁：失败
失败阶段：产品数据一致性检查
失败工具：无
关键错误：ResumeVersion artifact 和 risk_notes 中出现“待补”占位表达。
修复动作：统一 main-agent 契约、前端快捷动作 prompt 和 smoke prompt，要求 ResumeVersion 的 content、change_summary、keyword_strategy、risk_notes 都不能包含“占位 / 待填 / 待补 / 待完善 / TODO / TBD”等需替换表达；缺失事实写为“未提供 / 缺少 / 需用户提供”，并进入 CareerApplication 的 risks / next_actions。
```

```text
时间：2026-05-12 08:52:44 +08:00
命令：uv run python tools/smoke_career_live_flow.py --runs 1 --concurrency 1 --max-tool-rounds 8 --project-action checklist --data-dir data/live_career_smoke_m7_project_action_retry
runs / concurrency / max_tool_rounds：1 / 1 / 8
project_action：checklist
data_dir：data/live_career_smoke_m7_project_action_retry/run_001
session_id：sess_live_career_001_ad6891c3
总耗时：158.87s
结果：通过
产品记录数量：ResumeProfile 1，CareerProfile 1，JDAnalysis 1，JobFitReport 1，ResumeVersion 1，CareerApplication 1
artifact 数量：6
项目动作观察：通过。投递前检查阶段调用 career_application_get、career_application_merge、session_create_text_artifact，并创建检查报告 artifact。
一致性检查：通过，无 error finding
质量门禁：通过
失败阶段：无
失败工具：无
关键错误：无
下一步：M7 主线闭环可以进入收尾；后续不扩大 live smoke 批次，转入 M8 NoteService 设计前先做一次代码提交和工作区清理。
```
