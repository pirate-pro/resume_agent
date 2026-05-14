# M21 产品候选版验收计划

## 目标

M21 不新增主功能，目标是把当前已经完成的求职产品闭环做成一个可以稳定演示、可以真实试用的候选版。

这一步要回答三个问题：

```text
1. 用户能不能顺畅完成一条完整求职路径？
2. 产品记录、文件资产、笔记和学习任务之间是否一致、可追溯？
3. 前端是否达到“用户愿意继续试”的基本体感？
```

M21 的工作方式是验收和修正，不是继续扩功能。只修 P0 / P1 问题，避免把新里程碑变成新功能堆叠。

## 当前前置状态

已完成：

- `CareerProductStore`：求职产品资产事实源。
- `SessionArtifact`：上传文件和生成文件事实源。
- `CareerApplication`：求职项目闭环。
- `NoteService`：用户笔记和面试复盘。
- `LearningService`：学习计划、学习任务、进度打卡和短板跟踪。
- `RetrievalService`：按项目召回求职资产、笔记、学习任务和资料。
- 工作台页面：求职项目、资料库、笔记、学习任务入口。
- M20 低批次真实 smoke 已通过：学习建议、推荐转任务、主动添加任务、打卡更新链路已跑通。

暂不进入：

- memory 自动写入策略。
- 日历、提醒和通知系统。
- 外部面经知识库写入工具。
- RAG / MCP 知识库接入。
- typed evidence ref 迁移。
- 多用户权限和账号系统。

## 候选版用户路径

M21 验收以一个真实用户路径为主线：

```text
1. 用户新建会话。
2. 上传简历文件。
3. 让 Agent 诊断简历并生成简历画像、职业画像和诊断报告。
4. 用户粘贴或上传 JD。
5. Agent 分析 JD，生成匹配报告，并创建求职项目。
6. 用户生成一版定制简历。
7. 用户打开工作台查看项目、简历、JD、匹配报告和生成文件。
8. 用户创建或编辑一条笔记。
9. 用户让 Agent 根据复盘或匹配短板给出准备建议。
10. 用户确认把建议加入学习任务。
11. 用户主动添加一个学习任务。
12. 用户记录一次学习进度，并更新任务状态。
13. 用户回到工作台确认资产、笔记、任务和时间线都能找到。
```

这条路径通过后，当前产品才算达到候选版主线闭环。

## 验收矩阵

### 1. 后端事实源

检查项：

- 简历原文和诊断报告必须有 `SessionArtifact`。
- JD 原文必须先进入 `SessionArtifact`，再进入 JD 分析。
- 匹配报告、定制简历等用户可查看内容必须以 artifact 为准。
- `CareerProductStore` 只保存结构化产品记录和 artifact 引用。
- `NoteService` 保存用户笔记和复盘，不写入 memory。
- `LearningService` 保存学习任务和进度，不更新 CareerApplication，除非用户明确要求项目状态变化。
- `events` 能追踪关键工具调用。

通过标准：

- 产品记录 ID 完整。
- `source_session_id`、`source_artifact_id`、`evidence_refs` 格式正确。
- 没有脏路径暴露给 Agent。
- 质量门禁通过。

### 2. Agent 行为

检查项：

- 简历诊断能委派或调用正确 Agent。
- JD 匹配能复用已有简历画像和职业画像。
- 生成定制简历时不编造缺失事实。
- 只问建议时不自动创建学习任务。
- 用户确认加入学习任务后才创建 LearningTask。
- 用户主动添加学习任务时不强制依赖求职项目。
- 打卡时先定位 LearningTask，再创建 ProgressCheckin。
- 默认不写 memory。

通过标准：

- 工具调用符合职责边界。
- 没有越权写 Note、CareerApplication、WeaknessTracker 或 memory。
- 真实 smoke 至少一把通过。

### 3. 前端主路径

检查项：

- 首页不是空白页。
- 上传、激活资料、发送消息入口明确。
- Agent 执行进度可见，不像卡死。
- 报告 Markdown 渲染正常，不泄漏大段原始 Markdown。
- 报告预览、下载、复制 ID 等调试入口不干扰普通用户。
- 工作台入口可见。
- 工作台能找到项目、报告、简历、笔记、学习任务。
- 笔记可以进入、编辑和 Markdown 预览。
- 学习任务可以新建、推荐加入和打卡。
- 桌面端和窄屏没有明显遮挡、溢出和底部硬色块。

通过标准：

- 桌面主链路可演示。
- 关键弹层可打开和关闭。
- 常用动作有反馈。
- 没有 P0/P1 视觉问题。

### 4. 性能和稳定性

检查项：

- Python 测试通过。
- mypy 通过。
- Flutter analyze / test 通过。
- 低批次 live smoke 通过。
- 关键页面截图自查。
- 不扩大并发压力测试批次。

通过标准：

- 没有损坏 JSON。
- 没有 tmp 残留。
- live smoke 单 run 可以完成。
- 已知耗时问题记录下来，不在 M21 强行优化模型速度。

## 建议执行命令

后端回归：

```bash
uv run pytest -q
uv run mypy
```

前端回归：

```bash
cd /home/ubunt/resume_agent/flutter_app
/home/ubunt/resume_agent/flutter/bin/flutter analyze
/home/ubunt/resume_agent/flutter/bin/flutter test
```

M21 低批次真实 smoke：

```bash
uv run python tools/smoke_career_live_flow.py \
  --runs 1 \
  --concurrency 1 \
  --max-tool-rounds 10 \
  --retrieval-action m20_learning_entries \
  --data-dir data/live_career_smoke_m21_candidate
```

前端启动：

```bash
cd /home/ubunt/resume_agent/flutter_app
/home/ubunt/resume_agent/flutter/bin/flutter run \
  -d web-server \
  --web-hostname 0.0.0.0 \
  --web-port 38765
```

## P0 / P1 问题定义

P0 必须修：

- 页面空白或无法启动。
- 主链路工具失败。
- 产品记录无法落库或损坏。
- 用户可见文件无法预览。
- 学习任务、笔记、项目等核心记录丢失。
- Agent 越界写 memory 或错误更新事实源。

P1 优先修：

- 关键入口找不到。
- 报告 Markdown 大面积渲染失败。
- 工作台核心区域明显遮挡或溢出。
- 同一份资产重复展示导致用户无法判断哪个是最新。
- 任务、笔记、报告之间跳转不清晰。
- 调试信息压过用户信息。

P2 记录但暂不修：

- 局部样式不够精致。
- 非主路径的小按钮文案。
- 移动端轻微排版拥挤。
- 单 run 真实模型耗时偏长。
- 来源标签推断不够精细。

## 交付物

M21 完成时需要产出：

```text
1. docs/m21_product_acceptance_report.md
2. 一组通过的测试命令记录
3. 一把通过或明确失败原因的低批次 live smoke
4. 关键 UI 截图检查结论
5. P0/P1 修复提交
6. 候选版已知问题列表
```

## 完成标准

M21 完成后，项目应该达到：

- 可以给用户演示完整求职路径。
- 用户能理解上传资料后下一步做什么。
- 工作台能承载求职项目、笔记、学习任务和报告资产。
- 后端事实源边界清楚，没有混用 memory。
- 真实模型低批次链路能跑通。
- 已知问题可控，不阻断候选版试用。

## 下一步

如果这份计划通过审核，开发顺序建议是：

```text
1. 跑自动化回归。
2. 跑 M21 低批次 live smoke。
3. 启动前端并做桌面截图自查。
4. 只修 P0 / P1 问题。
5. 记录 M21 验收报告。
```
