# M18 质量验收与压力测试报告

## 目标

本轮目标是对当前求职 Agent MVP 主闭环做一次质量验收，覆盖：

- 后端 store / API / tools / runtime 回归。
- Agent 确定性链路。
- memory / flush / compaction 本地压力测试。
- Flutter 前端静态分析和组件测试。
- 桌面与移动端 UI 截图检查。
- 低批次真实模型 live smoke。

## 自动化回归结果

已通过：

```bash
uv run pytest -q
uv run mypy
/home/ubunt/resume_agent/flutter/bin/flutter analyze
/home/ubunt/resume_agent/flutter/bin/flutter test
```

说明：

- Python 全量测试通过。
- 类型检查通过。
- Flutter analyze 通过。
- Flutter widget tests 通过。
- `file_picker` 仍会输出上游平台插件警告，但不影响 analyze/test 结果。

## 本地压力测试结果

执行：

```bash
uv run python tools/stress_memory_pipeline.py
```

结果摘要：

```text
multi-session 并发最高 24：0 失败
same-session 锁竞争最高 24：0 失败
memory write consistency：800 / 800 成功
flush + compaction race sweep：最高并发 12，0 失败
invalid_json_files：0
tmp_files：0
```

观察：

- 多会话并发 24 时 P95 约 421ms。
- 同会话锁竞争 24 时 P95 约 1377ms，符合串行锁竞争预期。
- 没有发现 memory 文件损坏、flush retry、deferred job 或 tmp 残留。

## 前端截图检查

截图目录：

```text
data/m18_ui_screenshots/
```

已检查：

```text
home_1440x1000.png
workbench_1440x1000.png
report_preview_1440x1000.png
home_390x844.png
workbench_390x844.png
```

结论：

- 桌面主界面、工作台、报告预览整体可用。
- 移动端主界面没有空白页、明显遮挡或底部渐隐硬块。
- 报告预览 Markdown 渲染正常，没有观察到大面积原始 Markdown 泄漏。
- 移动端工作台横向 Tab 在窄屏会被截断，但表现接近横向滚动导航，暂列为低优先级体验观察。

## 真实模型 smoke

最终通过命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 8 \
  --retrieval-action interview_review \
  --data-dir data/live_career_smoke_m18_final
```

最终结果：

```text
运行数: 1
成功数: 1
失败数: 0
耗时: 214.28s
质量门禁: 通过
```

最终链路：

```text
简历诊断与画像沉淀
-> JD 匹配分析
-> 定制简历版本
-> M16 面试复盘更新项目
```

最终产物：

```text
ResumeProfile: 1
CareerProfile: 1
JDAnalysis: 1
JobFitReport: 1
ResumeVersion: 1
CareerApplication: 1
Note: 1
LearningTask: 0
```

符合预期：

- 面试复盘先召回上下文。
- 创建复盘 Note。
- 更新 CareerApplication。
- 没有误建 LearningTask。
- 没有误写 memory。
- 质量门禁通过。

## 真实 smoke 暴露并修复的问题

### 1. Retrieval source type 别名不够宽容

问题：

真实模型会传入 `career_job_fit_report`、`resume` 这类口语化或工具名风格的 `source_types`，原工具只接受严格枚举，导致失败。

修复：

- Retrieval 工具增加常见别名：
  - `resume`
  - `jd`
  - `fit`
  - `career_job_fit_report`
  - `job_fit_reports`
  - 以及对应复数和 career 前缀别名

### 2. CareerApplication 不能引用复盘 Note 作为证据

问题：

M16 复盘链路里，系统先创建 Note，再更新 CareerApplication。真实模型把 `note_` 放入 `career_application_merge.evidence_refs`，但 Career evidence ref 校验不接受 `note_`。

修复：

- Career 产品记录 `evidence_refs` 支持 `note_` 格式。
- 只做格式校验，不引入跨 store 存在性校验。

### 3. ResumeVersion 元数据禁用词没有前置拦截

问题：

模型在 `change_summary` 中写出禁用表达，数据已保存后才被质量门禁拦截。

修复：

- `career_resume_version_create` 在写入前检查 `title/content/change_summary/keyword_strategy/risk_notes`。
- 如果包含占位或替换类表达，工具直接拒绝写入，避免污染产品记录。
- 同步收紧 main-agent 和 smoke prompt，避免模型复述禁用词说明。

## 当前结论

当前 MVP 主闭环已经通过一轮完整质量验收：

```text
上传/读取简历
-> 简历画像
-> JD 分析
-> 匹配报告
-> 定制简历
-> 求职项目
-> 面试复盘 Note
-> 更新项目进展
-> 不自动创建学习任务
```

还需要继续观察：

- 真实模型耗时偏长，单 run 约 3.5 分钟。
- 同会话高并发下延迟会随锁竞争线性上升。
- 移动端工作台窄屏导航仍有优化空间。

下一步建议：

```text
1. 不继续扩功能，先保持主闭环稳定。
2. 增加 M17 真实 smoke：复盘建议默认只回答，用户确认后才转 LearningTask。
3. 后续再做工作台“建议转任务”的显式交互。
```
