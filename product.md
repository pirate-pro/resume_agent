
你这个产品不是普通“简历优化工具”，更像是一个 **个人求职成长 Agent**。

它的核心不是一次性帮用户改简历，而是长期陪用户完成：

```text
认识自己
  ↓
提炼经历和优势
  ↓
确定职业方向
  ↓
匹配岗位
  ↓
优化简历
  ↓
准备面试
  ↓
记录面试反馈
  ↓
继续修正个人画像和求职策略
```

所以这个 ToC 产品的 Agent 设计，应该围绕 **个人画像 + 求职策略 + 简历优化 + 面试复盘 + 长期记忆** 来做。

---

# 1. 产品定位

## 1.1 产品一句话

```text
一个面向求职者的个人职业 Agent，基于简历、经历、技能、兴趣、面试记录和长期互动，持续帮助用户找到更合适的岗位、优化简历、准备面试并复盘成长。
```

---

## 1.2 核心用户

第一版建议聚焦这几类人：

```text
1. 应届生 / 研究生 / 转行者
2. 1-3 年工作经验的初中级求职者
3. 想投多个方向但不知道怎么选的人
4. 简历内容很多但不会包装的人
5. 面试多但缺少系统复盘的人
```

你自己的背景其实也很适合这个产品原型：

```text
有简历
有多个意向方向
有技术经历
需要判断投什么岗位
需要针对岗位优化简历
需要准备面试
需要记录面试问题和反馈
```

---

# 2. 产品核心闭环

这个产品最重要的是闭环，不是单点能力。

```text
用户上传简历
  ↓
解析简历结构
  ↓
生成个人求职画像
  ↓
分析兴趣 / 性格 / 技能 / 经历 / 学历
  ↓
匹配岗位方向
  ↓
给出岗位推荐和投递优先级
  ↓
针对岗位优化简历
  ↓
生成面试准备方案
  ↓
记录面试题、回答、心情、反馈
  ↓
更新用户画像和求职策略
  ↓
下一次推荐更准
```

这个闭环里，**记忆系统非常关键**。

因为用户不是一次性使用，而是持续使用：

```text
今天改简历
明天投岗位
后天面试
面试后记录问题
下周继续优化方向
```

---

# 3. 第一版先做 Agent 部分

你现在可以先不做完整知识库，但 Agent 体系要预留知识库接口。

第一版可以是：

```text
用户上传简历
  ↓
Agent 解析并生成画像
  ↓
用户手动输入意向公司 / 岗位 JD
  ↓
Agent 分析匹配度
  ↓
Agent 优化简历
  ↓
Agent 生成面试准备
  ↓
用户记录面试题 / 心情 / 反馈
  ↓
Agent 更新 notes / memory
```

知识库后面再接：

```text
岗位知识库
公司知识库
面经知识库
行业知识库
薪资/招聘趋势知识库
```

---

# 4. Agent 总体架构

我建议第一版不要搞太多 Agent，先做：

```text
MainCareerAgent
ResumeAgent
ProfileAgent
JobFitAgent
ResumeOptimizeAgent
InterviewAgent
DiaryMemoryAgent
ReviewAgent
```

其中核心是：

```text
MainCareerAgent
  总控，负责和用户聊天、调度其他 Agent。

ResumeAgent
  负责简历解析和结构化。

ProfileAgent
  负责个人画像分析。

JobFitAgent
  负责岗位匹配和方向判断。

ResumeOptimizeAgent
  负责简历优化。

InterviewAgent
  负责面试准备和复盘。

DiaryMemoryAgent
  负责记录笔记、面试题、心情、聊天重点、长期记忆。

ReviewAgent
  负责审查建议是否靠谱，防止瞎推荐。
```

---

# 5. Agent 分工设计

## 5.1 MainCareerAgent：主 Agent

### 定位

用户主要和它对话。

它负责：

```text
理解用户意图
决定调用哪个 Agent
管理当前任务状态
组织多 Agent 输出
给用户最终答案
维护用户长期求职目标
```

### 工具

```text
resume_parse
profile_get
profile_update
memory_search
note_search
note_write
job_jd_analyze
agent_spawn
agent_result_get
artifact_create
artifact_get
```

### Skill

```text
任务拆解
多 Agent 调度
求职目标澄清
结果综合
追问用户缺失信息
```

### 典型对话

用户：

```text
我上传了简历，你帮我看看适合投什么岗位。
```

MainCareerAgent 应该做：

```text
1. 调用 ResumeAgent 解析简历
2. 调用 ProfileAgent 生成画像
3. 调用 JobFitAgent 评估方向
4. 调用 ReviewAgent 审查推荐是否合理
5. 输出岗位方向排序和原因
```

---

## 5.2 ResumeAgent：简历解析 Agent

### 定位

负责把 PDF / Word 简历解析成结构化数据。

### 输入

```text
PDF
Word
图片简历
用户手动输入的经历
```

### 输出

```json
{
  "basicInfo": {},
  "education": [],
  "workExperience": [],
  "projectExperience": [],
  "skills": [],
  "certificates": [],
  "awards": [],
  "selfEvaluation": "",
  "rawText": ""
}
```

### 工具

```text
file_upload_read
pdf_text_extract
docx_text_extract
resume_section_detect
resume_schema_save
artifact_create
```

### Skill

```text
简历结构识别
经历抽取
技能抽取
项目经历抽取
学历信息抽取
时间线修复
简历缺失项识别
```

### 关键能力

ResumeAgent 不只是提取文本，还要识别：

```text
用户做过什么
用了什么技术
解决了什么问题
有什么成果
哪些经历可以包装
哪些内容太弱
哪些内容不适合写
```

---

## 5.3 ProfileAgent：个人画像 Agent

### 定位

负责综合简历、聊天、笔记、面试记录，形成用户职业画像。

### 画像维度

```text
兴趣方向
技能结构
项目经验
行业经验
学历背景
学校背景
性格倾向
求职偏好
职业目标
短板风险
成长潜力
表达风格
面试表现
```

### 特别说明：面相 / 生辰八字

这部分可以做，但建议定位为：

```text
娱乐化 / 文化参考 / 自我探索辅助
```

不要把它作为严肃岗位匹配依据。

也就是说，可以叫：

```text
趣味性格探索
传统文化参考
自我认知问卷
```

不要说：

```text
根据面相判断你适合什么职业
根据八字判断你性格一定怎样
```

更稳妥的产品表达是：

```text
面相和生辰八字仅作为趣味维度，最终职业建议以简历、技能、经历、兴趣和岗位要求为主。
```

### 工具

```text
resume_profile_read
memory_search
note_search
interest_questionnaire
personality_questionnaire
bazi_input_record
face_image_optional_record
profile_update
```

### Skill

```text
经历归纳
技能画像
兴趣提炼
性格分析
职业倾向分析
优势/短板总结
求职定位生成
```

### 输出示例

```markdown
# 个人求职画像

## 核心优势
- 有 Agent / RAG / 后端系统设计经验。
- 对 memory、context、tool、runtime 等 Agent 底座有深入思考。
- 具备技术文档和架构抽象能力。

## 适合方向
1. AI 应用开发工程师
2. Agent/RAG 工程师
3. 后端开发工程师
4. AI 产品技术型岗位

## 风险点
- 前端能力需要 AI 辅助。
- 嵌入式经验较弱。
- 某些 C/C++ 方向需要重新准备。

## 性格/兴趣倾向
- 偏结构化思考。
- 喜欢系统设计和底层机制。
- 不太适合纯重复业务开发。
```

---

## 5.4 JobFitAgent：岗位匹配 Agent

### 定位

负责根据用户画像和岗位要求判断：

```text
适合投什么
优先投什么
不建议投什么
怎么补短板
简历该怎么针对性调整
```

### 第一版没有岗位知识库怎么办？

可以先支持：

```text
用户上传 JD
用户输入公司/岗位描述
用户输入几个岗位截图
用户手动录入意向方向
```

然后 JobFitAgent 做匹配。

### 后续接知识库

后面它再接：

```text
岗位库
公司库
面经库
招聘趋势库
```

### 工具

```text
job_jd_parse
profile_get
resume_schema_get
job_fit_score
memory_search
artifact_create
```

### Skill

```text
岗位要求拆解
技能匹配
经历匹配
学历/学校匹配
风险识别
投递优先级排序
补强建议
```

### 匹配维度

```text
技能匹配度
项目经历匹配度
行业背景匹配度
学历匹配度
岗位成长空间
竞争风险
简历可包装空间
用户兴趣匹配度
面试准备难度
```

### 输出格式

```markdown
# 岗位匹配分析

## 推荐结论

最推荐：
1. Agent/RAG 应用开发
2. AI 后端开发
3. AI 产品工程化

谨慎投递：
1. 嵌入式 C/C++
2. 纯前端
3. 传统车载底层软件

## 匹配评分

| 岗位 | 匹配度 | 原因 | 风险 | 建议 |
|---|---:|---|---|---|

## 简历优化方向

## 面试准备重点
```

---

## 5.5 ResumeOptimizeAgent：简历优化 Agent

### 定位

负责针对岗位优化简历。

不是简单润色，而是：

```text
提炼亮点
重写项目经历
调整关键词
强化结果表达
针对 JD 改写
生成多版本简历
检查 ATS 友好性
```

### 工具

```text
resume_schema_get
resume_version_create
resume_section_rewrite
jd_keyword_extract
ats_keyword_match
artifact_create
docx_export
pdf_export
```

### Skill

```text
STAR 法则
项目经历包装
技术关键词优化
岗位定制简历
简历问题诊断
简历版本管理
```

### 简历版本

你可以设计：

```text
通用版
AI 应用开发版
Agent/RAG 版
后端开发版
车载软件版
前端辅助版
```

每个版本都单独保存：

```text
data/resumes/
  resume_base.json
  versions/
    ai_agent_resume.md
    backend_resume.md
    vehicle_app_resume.md
```

---

## 5.6 InterviewAgent：面试 Agent

### 定位

负责面试准备、模拟面试、面试复盘。

### 功能

```text
根据岗位生成面试题
根据简历生成追问题
模拟 HR 面
模拟技术面
评价用户回答
优化回答
记录面试题
记录面试表现
生成复盘报告
```

### 工具

```text
profile_get
resume_schema_get
job_jd_get
interview_question_generate
interview_record_write
answer_evaluate
note_write
memory_write_candidate
artifact_create
```

### Skill

```text
技术面试准备
HR 面准备
STAR 回答优化
项目追问生成
面试复盘
弱点定位
```

### 面试记录结构

```json
{
  "interviewId": "int_001",
  "date": "2026-04-30",
  "company": "某公司",
  "position": "AI 应用开发工程师",
  "round": "一面",
  "questions": [
    {
      "question": "介绍一下你的 RAG 项目。",
      "userAnswer": "...",
      "feedback": "...",
      "score": 7
    }
  ],
  "mood": "紧张但还可以",
  "result": "待反馈",
  "summary": ""
}
```

---

## 5.7 DiaryMemoryAgent：笔记 / 记忆 Agent

### 定位

这是你产品体验的核心之一。

它负责：

```text
记录用户日记
记录面试题
记录面试心情
从聊天中提炼重点
让用户手动选择内容存入笔记
维护长期用户画像
维护求职进展
```

你说的这个想法非常好：

```text
记录面试题这一部分，可以归类为日记一样的东西。
什么都可以记录。
聊天里可以提炼重点，记录在笔记某个位置。
用户也可以手动选择聊天内容存入笔记某些位置。
并且可以自由编辑。
```

这就是你的产品长期价值所在。

### 笔记分类

建议第一版做这些 notebook：

```text
daily/
  每日求职日记

interviews/
  面试记录

questions/
  面试题库

answers/
  我的回答库

companies/
  公司记录

positions/
  岗位记录

resume_notes/
  简历优化记录

self_profile/
  自我认知和职业画像
```

### Markdown 结构

```text
notes/
  daily/
    2026-04-30.md
  interviews/
    company_x_ai_engineer_round1.md
  questions/
    rag_questions.md
  answers/
    project_intro_answers.md
  profile/
    career_profile.md
```

### 工具

```text
note_create
note_get
note_update_section
note_append
note_search
note_link_chat
note_extract_from_chat
note_manual_save_selection
memory_write_fact
memory_search
```

### Skill

```text
聊天重点提炼
面试记录整理
日记生成
笔记归类
长期记忆提取
情绪记录
复盘总结
```

---

# 6. 用户笔记系统设计

这是你产品和普通简历工具的差异点。

## 6.1 笔记不是 memory，但会产生 memory

关系：

```text
聊天记录
  ↓
用户选择 / AI 提炼
  ↓
笔记
  ↓
长期有价值内容
  ↓
memory facts / profile
```

比如用户面试后写：

```text
今天一面被问到了 RAG 的 chunk 策略，我回答得不好，有点紧张。
```

这应该写入：

```text
daily note
interview note
question bank
```

然后提炼出长期 memory：

```text
用户在 RAG chunk 策略相关问题上回答不够熟练，需要加强准备。
```

---

## 6.2 手动保存聊天内容

你可以做一个交互：

```text
用户选中一段聊天
  ↓
点击“存入笔记”
  ↓
选择笔记类型：
      面试题
      简历亮点
      项目经历
      心情日记
      公司记录
      待办事项
  ↓
选择位置：
      新建笔记
      追加到已有笔记
      放到某个 section
  ↓
AI 自动整理格式
  ↓
用户可编辑
```

这是非常 ToC 的功能。

---

## 6.3 自动提炼聊天重点

每轮对话结束后，DiaryMemoryAgent 可以给出建议：

```text
我发现这轮对话有 3 条内容值得保存：

1. 你确定 memory_v3 使用三层结构。
2. 你希望 agent 私有记忆进入 shared 必须 promote。
3. 你计划后续做面经知识库。

是否保存到求职产品设计笔记？
```

用户可以：

```text
全部保存
只保存第 1 条
修改后保存
不保存
```

这样比自动乱写 memory 更好。

---

# 7. 你的 memory 体系如何适配这个产品

你之前的三层设计可以直接用。

```text
short_term = session events + state
mid_term   = notes / daily / interview records
long_term  = user profile + facts
```

但这里建议稍微换个产品化命名：

```text
short_term
  当前聊天和任务状态

notes
  用户可见、可编辑的日记/面试/简历笔记

profile_memory
  系统维护的长期画像和事实
```

底层目录可以仍然是：

```text
data/
  sessions/
  notes/
  memory_v3/
```

---

# 8. 求职画像数据结构

长期画像建议拆成：

```json
{
  "userProfile": {
    "careerGoal": "",
    "targetRoles": [],
    "preferredIndustries": [],
    "preferredCities": [],
    "workContext": "",
    "personalStyle": "",
    "strengths": [],
    "weaknesses": [],
    "interests": [],
    "skills": [],
    "education": [],
    "experienceSummary": "",
    "interviewWeaknesses": [],
    "resumeIssues": []
  }
}
```

facts 记录原子事实：

```json
{
  "id": "fact_001",
  "key": "career.target_role",
  "value": "Agent/RAG 应用开发工程师",
  "content": "用户当前倾向投递 Agent/RAG 应用开发相关岗位。",
  "category": "career_goal",
  "confidence": 0.9,
  "source": {
    "type": "chat",
    "sessionId": "sess_001",
    "eventIds": ["evt_100"]
  },
  "status": "active"
}
```

---

# 9. 产品功能模块

## 9.1 简历上传与解析

```text
上传 PDF / Word
自动解析结构
生成简历画像
发现缺失项
输出简历诊断
```

---

## 9.2 个人画像分析

```text
经历分析
技能分析
兴趣方向
性格倾向
学历/学校背景
求职优势
短板风险
```

面相 / 八字建议作为：

```text
趣味自我探索模块
```

不要作为严肃岗位匹配主依据。

---

## 9.3 岗位匹配

第一版：

```text
用户上传 JD
用户输入意向岗位
用户输入意向公司
Agent 分析匹配度
```

后续：

```text
接岗位知识库
接公司知识库
接面经知识库
```

---

## 9.4 简历优化

```text
通用优化
针对岗位优化
关键词增强
项目经历重写
生成多个版本
导出 PDF / Word
```

---

## 9.5 面试准备

```text
根据简历生成面试题
根据岗位生成面试题
模拟面试
评价回答
优化回答
生成复习计划
```

---

## 9.6 面试日记 / 笔记

```text
记录面试题
记录回答
记录心情
记录反馈
记录结果
AI 自动复盘
沉淀题库
更新画像
```

---

## 9.7 聊天内容存入笔记

```text
用户手动选择聊天片段
AI 自动归类
存入指定笔记
支持自由编辑
支持后续检索
```

---

# 10. 第一版 MVP 建议

不要一上来做太大。

## MVP 目标

```text
让用户上传简历后，系统能：
1. 解析简历
2. 生成个人画像
3. 分析适合岗位方向
4. 根据一个 JD 优化简历
5. 记录一次面试复盘
6. 把聊天重点保存到笔记
```

---

## MVP Agent

第一版只需要 5 个：

```text
MainCareerAgent
ResumeAgent
ProfileAgent
ResumeOptimizeAgent
DiaryMemoryAgent
```

`JobFitAgent` 可以先并入 `ProfileAgent`。

`InterviewAgent` 可以先并入 `DiaryMemoryAgent`。

后面再拆。

---

## MVP 工具

```text
file_upload_read
resume_parse
profile_update
profile_get
jd_parse
resume_optimize
note_create
note_append
note_update_section
note_search
memory_write_fact
memory_search
artifact_create
```

---

# 11. 第二阶段

加入：

```text
JobFitAgent
InterviewAgent
ReviewAgent
```

支持：

```text
多岗位对比
岗位匹配评分
模拟面试
面试回答评分
简历审查
```

---

# 12. 第三阶段：知识库

这时再做你说的：

```text
多端数据收集
岗位数据结构化清洗
面经数据结构化清洗
标签体系
向量库 / 混合检索
不同标签不同权重
```

知识库可以支持：

```text
岗位推荐
岗位能力要求分析
面试题预测
公司面经总结
回答参考
```

但这应该是下一步，不要现在就把 Agent 主线拖复杂。

---

# 13. 这个产品最有差异化的点

我觉得不是“简历优化”，而是这三个：

## 13.1 长期求职画像

系统越来越懂用户：

```text
适合什么岗位
害怕什么面试题
哪些项目讲不好
哪些技能需要补
偏好什么公司
简历哪部分反复需要优化
```

---

## 13.2 面试日记 + 题库沉淀

用户每次面试后记录：

```text
被问了什么
怎么答的
哪里答崩了
面试官反馈
当天心情
结果如何
```

系统长期积累后，可以反向优化：

```text
简历
回答模板
岗位选择
技能补强计划
```

---

## 13.3 聊天内容可沉淀为笔记

这很有体验感。

不是 AI 自己偷偷记，而是：

```text
AI 建议保存
用户确认
用户可编辑
用户可查看
用户可搜索
```

这会让用户觉得系统可信。

---

# 14. 推荐最终产品主线

```text
简历中心
  上传 / 解析 / 版本管理 / 优化

职业画像
  技能 / 经历 / 兴趣 / 性格 / 目标

岗位匹配
  JD 分析 / 匹配评分 / 投递建议

面试中心
  面试题 / 回答 / 模拟 / 复盘

求职笔记
  日记 / 面试记录 / 公司记录 / 聊天摘录

长期记忆
  用户画像 / facts / 偏好 / 决策 / 求职进展
```

---

# 15. 一句话总结

你这个产品应该设计成：

```text
一个围绕“简历 → 画像 → 岗位 → 优化 → 面试 → 复盘 → 记忆更新”的长期求职 Agent。
```

第一版先把 Agent 部分做扎实：

```text
ResumeAgent 解析简历
ProfileAgent 生成画像
JobFitAgent 判断方向
ResumeOptimizeAgent 优化简历
InterviewAgent 准备和复盘面试
DiaryMemoryAgent 管理笔记和长期记忆
MainCareerAgent 负责调度和最终交互
```

而你最有潜力的特色是：

```text
面试日记 + 聊天摘录存笔记 + 长期画像持续更新。
```

这会让它不只是“改简历工具”，而是一个真正陪用户求职成长的个人 Agent。