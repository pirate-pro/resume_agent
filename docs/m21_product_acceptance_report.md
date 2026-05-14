# M21 产品候选版验收报告

## 结论

M21 第一轮候选版验收结论：主链路具备候选版演示条件，但仍有两个需要记录的观察项。

```text
自动化回归：通过
前端基础回归：通过
低批次真实 smoke：产品数据链路通过，存在 1 条已恢复 warning
前端截图：重启 web-server 后通过
候选版状态：可以继续进入候选版收口，不新增功能
```

## 自动化回归

执行命令：

```bash
uv run pytest -q
uv run mypy
```

结果：

```text
pytest: 通过
mypy: 通过，234 个 source files 无类型错误
```

## 前端基础回归

执行命令：

```bash
cd /home/ubunt/resume_agent/flutter_app
/home/ubunt/resume_agent/flutter/bin/flutter analyze
/home/ubunt/resume_agent/flutter/bin/flutter test
```

结果：

```text
flutter analyze: 通过
flutter test: 通过，23 个测试全部通过
```

说明：

- `file_picker` 仍输出上游平台插件警告，不影响 analyze/test 结果。

## 低批次真实 smoke

执行命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action m20_learning_entries \
  --data-dir data/live_career_smoke_m21_candidate
```

原始 run：

```text
data_dir: data/live_career_smoke_m21_candidate/run_001
elapsed: 241.35s
quality_gate: 通过
record_counts:
  ResumeProfile: 1
  CareerProfile: 1
  JDAnalysis: 1
  JobFitReport: 1
  ResumeVersion: 1
  CareerApplication: 1
  Note: 1
  LearningTask: 2
  ProgressCheckin: 1
```

原始报告失败原因：

```text
career_resume_version_create 首次写入时，
change_summary 使用了“未使用任何占位表达”这类否定说明，
触发 ResumeVersion 元数据保护性拒绝。
```

实际链路观察：

- 工具拒绝了脏元数据，没有污染 `CareerProductStore`。
- 模型随后移除违规表述，并成功创建 ResumeVersion。
- 质量门禁通过。
- 学习任务入口链路完整：
  - 只问建议时未创建 LearningTask。
  - 确认加入建议时创建 1 个推荐 LearningTask。
  - 用户主动添加时创建 1 个 LearningTask。
  - 打卡时创建 1 个 ProgressCheckin，并把任务标记为 done。

处理结果：

- 不放松工具校验。
- smoke 报告新增“已恢复的工具保护性拒绝”warning。
- 对已成功恢复且质量门禁通过的保护性拒绝，不再按数据损坏或链路失败处理。

本地复检结果：

```text
success: true
errors: []
warnings:
  - 已恢复的工具保护性拒绝: career_resume_version_create -> ResumeVersion change_summary contains forbidden placeholder or replacement wording...
quality_gate: true
```

## 前端截图检查

截图目录：

```text
data/m21_ui_screenshots/
```

第一次截图结果：

```text
home_1440x1000.png: 空白页
home_390x844.png: 空白页
```

原因判断：

- 38765 端口上的 Flutter web-server 是旧进程。
- 页面 HTML 正常返回，但 Flutter app 没有完成渲染。
- 重启 web-server 后恢复。

重启命令：

```bash
cd /home/ubunt/resume_agent/flutter_app
/home/ubunt/resume_agent/flutter/bin/flutter run \
  -d web-server \
  --web-hostname 0.0.0.0 \
  --web-port 38765
```

重启后截图：

```text
home_1440x1000_after_restart.png: 通过
home_390x844_after_restart.png: 通过
```

观察：

- 桌面端首页不是空白页。
- 工作台入口可见。
- 输入区可见，没有底部硬色块遮挡。
- 右侧求职资产栏可见，资产卡片能展示当前项目和报告入口。
- 窄屏首页可用，顶部工具入口和输入区可见。

## 发现的问题

### P1：ResumeVersion 首次写入仍可能触发保护性拒绝

现象：

- 模型会在 `change_summary` 写“未使用任何占位表达”这类自检句。
- 工具会拒绝，模型能自我修正并成功保存。

当前处理：

- 保持工具硬拦截。
- smoke 报告列为 warning。
- 后续可继续优化定制简历 prompt，减少一次失败重试带来的延迟。

### P1：前端旧 dev server 可能出现空白页

现象：

- 旧 Flutter web-server 进程返回 HTML，但 app 未渲染。
- 重启服务后恢复。

当前处理：

- M21 验收前必须重启前端服务。
- 该问题暂不判断为代码缺陷，但作为候选版运行手册注意项。

## 当前不处理的问题

- 真实模型单 run 耗时仍在 4 分钟左右。
- `file_picker` 上游平台插件警告。
- ResumeVersion 保护性拒绝后的 prompt 进一步优化。
- 前端局部视觉细节继续打磨。
- memory 自动写入、提醒系统、外部知识库和 RAG / MCP。

## 下一步

建议下一步继续 M21 收口：

```text
1. 不新增主功能。
2. 再做一轮工作台关键交互自查：报告预览、笔记编辑、学习任务详情和打卡入口。
3. 只修 P0 / P1 问题。
4. 汇总候选版运行手册和演示路径。
```
