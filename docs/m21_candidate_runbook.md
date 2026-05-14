# M21 候选版运行手册

## 目标

这份手册用于候选版演示和本地试用，不定义新功能。

演示目标：

```text
用户上传简历 -> 分析 JD -> 生成匹配报告和定制简历 -> 进入工作台查看资产 -> 记录笔记 -> 加入学习任务 -> 打卡更新进度
```

演示时重点观察三件事：

- 用户是否知道下一步该做什么。
- 结果是否能在工作台、资料预览、笔记和学习任务里找到。
- Agent 是否只写对应产品记录，不越界写 memory。

## 启动前检查

确认 `.env` 已配置模型网关：

```bash
cd /home/ubunt/resume_agent
test -f .env
```

后端健康检查：

```bash
curl http://127.0.0.1:8000/health
```

如果后端未启动：

```bash
cd /home/ubunt/resume_agent
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端启动：

```bash
cd /home/ubunt/resume_agent/flutter_app
/home/ubunt/resume_agent/flutter/bin/flutter run \
  -d web-server \
  --web-hostname 0.0.0.0 \
  --web-port 38765
```

访问地址：

```text
http://127.0.0.1:38765
```

如果页面空白，优先处理方式是停止旧的 Flutter web-server 后重新执行前端启动命令。M21 验收已确认旧进程可能返回 HTML 但 Flutter app 未完成渲染，重启后恢复。

## 演示资料

简历文件：

```text
sample_files/测试简历_后端工程师_张明.md
```

演示 JD 可以直接粘贴：

```text
星河智能招聘 AI Agent 后端工程师，负责企业级 AI Agent 平台后端能力建设，包括 Agent Runtime、tool calling、RAG 检索链路、异步任务、文件解析、审计日志和可观测性。

岗位要求：
1. 3 年以上 Python 后端开发经验，熟悉 FastAPI、SQLAlchemy、PostgreSQL、Redis。
2. 有 LLM 应用或 Agent 工程经验，理解工具调用、任务编排、上下文管理和流式输出。
3. 熟悉 RAG 基础链路，包括文档解析、chunk 策略、向量检索、召回评估和结果重排。
4. 有异步任务、消息队列或事件驱动系统经验，熟悉 Celery、Kafka、RabbitMQ 之一。
5. 有工程质量意识，能补充测试、日志、错误处理和性能优化。
6. 加分项：了解 LangChain / LangGraph，做过 AI 平台或智能体产品。
```

## 最短演示路径

### 1. 新建会话并上传简历

操作：

- 点击「新会话」。
- 上传 `sample_files/测试简历_后端工程师_张明.md`。
- 确认资料已激活。

发送提示词：

```text
请诊断这份简历，生成简历画像、职业画像和诊断报告。诊断报告请保存为用户可预览的 Markdown 文件。
```

预期结果：

- 对话下方能看到 Agent 执行进度。
- 右侧求职资产出现简历画像、职业画像或诊断报告。
- 诊断报告可以预览。

### 2. 粘贴 JD 并生成匹配报告

发送提示词：

```text
这是目标岗位 JD：

星河智能招聘 AI Agent 后端工程师，负责企业级 AI Agent 平台后端能力建设，包括 Agent Runtime、tool calling、RAG 检索链路、异步任务、文件解析、审计日志和可观测性。

岗位要求：
1. 3 年以上 Python 后端开发经验，熟悉 FastAPI、SQLAlchemy、PostgreSQL、Redis。
2. 有 LLM 应用或 Agent 工程经验，理解工具调用、任务编排、上下文管理和流式输出。
3. 熟悉 RAG 基础链路，包括文档解析、chunk 策略、向量检索、召回评估和结果重排。
4. 有异步任务、消息队列或事件驱动系统经验，熟悉 Celery、Kafka、RabbitMQ 之一。
5. 有工程质量意识，能补充测试、日志、错误处理和性能优化。
6. 加分项：了解 LangChain / LangGraph，做过 AI 平台或智能体产品。

请先把这段 JD 作为 session artifact 保存，再基于已有简历画像和职业画像分析匹配度，生成 JD 分析、岗位匹配报告和求职项目。匹配报告请保存为用户可预览的 Markdown 文件，不要写 memory。
```

预期结果：

- JD 原文会以 artifact 形式沉淀。
- 生成 JD 分析、岗位匹配报告和求职项目。
- 工作台能看到对应目标公司、目标岗位、匹配报告和关联资产。

### 3. 生成定制简历

发送提示词：

```text
请基于当前简历画像、职业画像、JD 分析和岗位匹配报告，生成一版面向星河智能 AI Agent 后端工程师岗位的 Markdown 定制简历。不要编造缺失经历，不要写 memory，最终结果请保存为用户可预览的文件。
```

预期结果：

- 生成 ResumeVersion。
- 生成的 Markdown 文件可以预览或下载。
- 如果首次出现 ResumeVersion 元数据保护性拒绝，且随后 Agent 自我修正并成功保存，可以按已知 warning 处理。

### 4. 打开求职工作台

操作：

- 点击顶部或右侧入口进入「求职工作台」。
- 查看项目详情、资料与报告、笔记和学习页。

预期结果：

- 项目页能看到星河智能岗位。
- 资料与报告页能预览简历诊断、JD 原文、匹配报告和定制简历。
- 学习页能看到任务入口：从项目推荐、新建任务、记录进度。

### 5. 保存一条笔记

发送提示词：

```text
请把当前匹配报告里关于 RAG、Agent Runtime、后端工程化的准备建议整理成一条学习类笔记，关联当前求职项目。只写 Note，不要创建学习任务，不要更新 CareerApplication，不要写 memory。
```

预期结果：

- 工作台笔记页出现一条学习类笔记。
- 笔记可以点击进入、编辑和 Markdown 预览。

### 6. 只生成准备建议

发送提示词：

```text
根据当前星河智能岗位、匹配报告和刚才的笔记，给我下一步 3 天准备建议。先只给建议，不要创建学习任务，不要保存新笔记，不要写 memory。
```

预期结果：

- Assistant 给出准备建议。
- 不创建新的 LearningTask。
- 消息底部可以出现「加入学习任务」类确认入口。

### 7. 确认加入学习任务

发送提示词：

```text
把刚才建议里的 RAG 召回评估和 LangChain / LangGraph 框架补强加入学习任务，来源写清楚，关联当前求职项目。不要写 Note、CareerApplication、WeaknessTracker 或 memory。
```

预期结果：

- 创建推荐来源的 LearningTask。
- 工作台学习页能看到任务。
- 任务来源能追溯到当前项目、匹配报告或笔记。

### 8. 用户主动添加一个学习任务

在工作台学习页点击「新建任务」，填写：

```text
任务标题：整理 FastAPI SSE 稳定性案例
任务描述：补充首字延迟、断线重连、事件审计和错误恢复的项目表达。
预计分钟数：45
优先级：中
```

提交给 Agent 创建。

预期结果：

- 创建用户主动添加的 LearningTask。
- `progress_notes` 能表达“来源：用户主动添加”。
- 不强制依赖某个复盘 Note 或匹配报告。

### 9. 记录学习进度

在工作台学习页点击「记录进度」，填写：

```text
进展摘要：今天完成 RAG 召回评估指标整理，补了 precision、recall、hit rate 和人工评估样例。
投入分钟数：35
状态：完成
```

提交给 Agent 记录。

预期结果：

- 创建 ProgressCheckin。
- 对应 LearningTask 状态更新。
- 工作台刷新后能看到任务状态变化。

## 演示验收清单

演示结束后检查：

```text
1. 对话流式输出和 Agent 进度可见。
2. 右侧求职资产栏有当前项目和可预览报告。
3. 工作台项目页能看到公司、岗位、匹配结论和下一步行动。
4. 资料与报告页能预览诊断、JD、匹配报告和定制简历。
5. 笔记页能打开、编辑并渲染 Markdown。
6. 学习页能看到推荐任务、主动任务和打卡记录。
7. 没有自动写 memory。
8. 没有重新解析简历、重复分析 JD 或重复创建核心画像。
```

## 已知问题

- 真实模型单 run 可能需要数分钟，演示时应让用户看到进度面板，避免误以为卡住。
- `career_resume_version_create` 仍可能先拒绝一次带有占位或替换类表达的元数据；如果随后成功恢复，按 warning 记录。
- `file_picker` 在 Flutter analyze / test 中会输出上游平台插件警告，不影响当前结果。
- 旧 Flutter web-server 偶发空白页时，重启前端服务即可恢复。

## 不在 M21 演示范围

- memory 自动写入。
- 外部面经知识库写入工具。
- RAG / MCP 知识库接入。
- 日历、提醒和通知系统。
- 多用户账号、权限和协作。
- 大并发压力测试。

