# M22 候选版人工演示验收报告

## 结论

M22 第一轮候选版验收结论：

```text
后端健康检查：通过
前端首页截图：旧 web-server 首次空白，重启后通过
真实低批次链路：产品数据链路通过，质量门禁通过
发现并修复：学习任务用户主动添加边界
候选版状态：可以作为候选版基线继续人工试用
```

本轮没有新增产品功能，只修正了候选版验收中暴露的 P1 级契约问题。

## 启动与截图

后端健康检查：

```bash
curl http://127.0.0.1:8000/health
```

结果：通过。

前端首次截图：

```text
data/m22_demo_acceptance_screenshots/home_1440x1000.png
data/m22_demo_acceptance_screenshots/home_390x844.png
```

结果：空白页。

处理：

- 停止旧 Flutter web-server。
- 重新执行 38765 端口前端启动。

重启后截图：

```text
data/m22_demo_acceptance_screenshots/home_1440x1000_after_restart.png
data/m22_demo_acceptance_screenshots/home_390x844_after_restart.png
```

结果：通过。

观察：

- 桌面首页可渲染。
- 工作台入口可见。
- 输入区可见。
- 右侧求职资产栏可见。
- 窄屏首页可用。

## 真实低批次链路

执行命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action m20_learning_entries \
  --data-dir data/live_career_smoke_m22_demo_acceptance
```

第一轮结果：

```text
data_dir: data/live_career_smoke_m22_demo_acceptance/run_001
quality_gate: 通过
record_counts:
  ResumeProfile: 1
  CareerProfile: 1
  JDAnalysis: 1
  JobFitReport: 1
  ResumeVersion: 1
  CareerApplication: 1
  Note: 1
  LearningTask: 1
  ProgressCheckin: 1
```

失败点：

- 用户主动添加学习任务时，模型复用了系统推荐的相似任务，没有创建独立任务。

判断：

- 这是 P1 产品语义问题。
- 用户在工作台主动点击“新建任务”时，默认应创建独立 `LearningTask`。
- 系统推荐任务可以去重，但用户主动新建不能被系统推荐去重规则吞掉。

## 修复一

修复内容：

- `agent_main` 契约明确：
  - 用户主动添加默认创建独立 `LearningTask`。
  - 不套用系统推荐任务的去重规则。
  - 只有用户明确要求合并、去重或继续已有任务时，才复用已有任务。
- 工作台“新建任务”提示词同步该语义。
- live smoke 提示词同步该语义。
- 补充确定性测试覆盖。

复跑命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action m20_learning_entries \
  --data-dir data/live_career_smoke_m22_demo_acceptance_fix
```

第二轮结果：

```text
data_dir: data/live_career_smoke_m22_demo_acceptance_fix/run_001
quality_gate: 通过
LearningTask: 3
ProgressCheckin: 1
```

失败点：

- 模型把 session 证据写成 `session:sess_...`，不符合当前 `evidence_refs` 校验。
- 用户主动新建任务阶段顺手调用了 `learning_task_update_state`。

判断：

- 这是契约表达不够明确。
- M1/M10 当前 evidence ref 使用字符串前缀校验，session ref 应使用原始 `sess_...`。
- 新建任务阶段只应创建待办任务，打卡和状态更新属于单独动作。

## 修复二

修复内容：

- `agent_main` 契约明确：
  - session 证据使用原始 `sess_...`，不要写成 `session:sess_...`。
  - 新建任务阶段不要顺手调用 `learning_checkin_create` 或 `learning_task_update_state`。
- 工作台“新建任务”提示词同步该规则。
- live smoke 提示词同步该规则。
- live smoke 检查器允许打卡动作通过 `retrieval_search` / `retrieval_context_pack` 定位 `LearningTask`，不强制只能使用 `learning_task_get/list`。

复跑命令：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action m20_learning_entries \
  --data-dir data/live_career_smoke_m22_demo_acceptance_fix2
```

第三轮结果：

```text
data_dir: data/live_career_smoke_m22_demo_acceptance_fix2/run_001
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

链路观察：

- 用户主动添加阶段已创建独立 `LearningTask`。
- session evidence ref 使用 `sess_...`，未再出现 `session:sess_...`。
- 用户主动添加阶段未再调用 `learning_task_update_state`。
- 打卡阶段通过 `retrieval_search` 定位学习任务后，创建 `ProgressCheckin` 并更新任务状态。
- 质量门禁通过。

第三轮报告仍失败的原因：

- 检查器只认可 `learning_task_get/list` 作为“定位 LearningTask”。
- 实际 Agent 使用 `retrieval_search` 定位到了 `LearningTask`，并成功完成打卡和状态更新。

处理：

- 修正检查器口径：`learning_task_get/list`、`retrieval_search`、`retrieval_context_pack` 都可作为打卡前定位动作。
- 增加确定性测试覆盖该口径。
- 为节省真实模型调用，本轮没有继续跑第四次 live smoke。

## 验证

已通过：

```bash
uv run pytest tests/test_career_live_smoke_report.py tests/test_learning_agent_flow.py -q
cd /home/ubunt/resume_agent/flutter_app
/home/ubunt/resume_agent/flutter/bin/flutter analyze
/home/ubunt/resume_agent/flutter/bin/flutter test
cd /home/ubunt/resume_agent
uv run mypy
```

结果：

```text
pytest: 24 个测试通过
flutter analyze: 通过
flutter test: 23 个测试通过
mypy: 通过，234 个 source files 无类型错误
```

说明：

- `file_picker` 仍输出上游平台插件 warning，不影响 analyze/test 结果。
- `career_resume_version_create` 保护性拒绝仍可能出现一次，但后续可恢复，按已知 warning 处理。

## 当前已知问题

- 旧 Flutter web-server 偶发空白页，重启可恢复。
- 真实模型单 run 仍需要数分钟。
- ResumeVersion 保护性拒绝后的 prompt 仍可继续优化，但不阻断候选版。
- 本轮没有做完整 UI 点击式自动化演示，只完成首页截图和真实低批次产品链路验证。

## 完成判断

M22 第一轮达到候选版基线条件：

```text
1. 后端可用。
2. 前端重启后可用。
3. 真实低批次产品数据链路可跑通。
4. 用户主动添加学习任务边界已修正。
5. 没有未解决 P0。
6. 当前 P1 均已处理或降为已知运行注意项。
```

下一步可以进入候选版人工试用；如果试用中继续发现 P0 / P1，再按 M22 规则修复。

