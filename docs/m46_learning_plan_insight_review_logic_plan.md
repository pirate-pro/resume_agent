# M46：学习计划短板与复盘产品逻辑补全方案

> 状态：待确认。目标是补全学习计划页中「短板与证据缺口」和「复盘安排」的产品逻辑与用户体验。原则：先讲清产品价值和用户路径，再补业务闭环，最后做页面表达；不把触发规则继续散落在 runtime、页面按钮或 Agent prompt 里。

## 1. 当前问题

现在这两个模块已经有数据模型和展示位，但产品逻辑不完整：

```text
短板与证据缺口
  当前只是展示 learning.weaknesses 中 active 且非 resolved 的记录。
  用户不知道这些短板从哪里来，也不知道什么时候会出现。
  ignored 状态目前也会展示，语义不严谨。
  “转任务”入口存在，但缺少“为什么转、转完状态怎么变”的闭环。

复盘安排
  当前只是展示 learning.reviews。
  后端已有 ReviewSchedule API，但 Agent 工具层没有 review create/update。
  完成学习任务后不会稳定生成复盘安排。
  用户不知道复盘和任务完成、阶段完成、面试复盘之间是什么关系。
```

所以这不是单纯 UI 问题。页面上看到空态时，用户不知道怎么触发；看到有内容时，也不知道它在整个学习流程里承担什么职责。

## 2. 产品定位

这两个模块的角色要明确：

```text
短板与证据缺口 = 为什么要学
  来自 JD 匹配、面试复盘、简历诊断或 Agent 诊断。
  用来解释当前学习任务背后的岗位差距。
  它不是任务本身，而是任务和简历证据的来源。

复盘安排 = 学完后什么时候回看
  来自任务完成、阶段完成、面试复盘或用户主动安排。
  用来把一次学习沉淀成可回顾、可验证的节奏。
  它不是学习任务本身，而是任务完成后的巩固动作。
```

对用户的解释应该变成：

```text
短板：系统从岗位匹配和复盘中发现你还缺什么。
复盘：完成任务后，系统帮你安排何时回顾和验证。
```

这两个功能不是为了“多放两个卡片”，而是为了把学习计划从普通任务列表变成求职教练式工作台。

```text
没有短板：
  用户只看到一堆任务，不知道为什么要做这些任务。

有短板：
  用户知道这些任务来自岗位差距、面试暴露问题或简历证据缺口。
  它回答的是：我为什么要补这个？

没有复盘：
  用户完成任务后流程就结束，学习容易变成一次性打卡。

有复盘：
  用户完成任务后会被引导回看、验证、沉淀成面试表达或简历证据。
  它回答的是：我学完后怎么确认真的有用？
```

所以学习计划页的产品骨架应该是：

```text
学习状态 Hero
  告诉用户现在整体处于什么阶段。

学习路线 Roadmap
  告诉用户长期方向是什么。

学习任务 Kanban
  告诉用户今天具体推进什么。

短板与证据缺口
  告诉用户为什么这些任务重要。

复盘安排
  告诉用户完成后如何巩固和验证。
```

如果只做 Agent 入口和任务卡，用户进入页面会感觉这是“聊天工具附带一个列表”。如果补上短板和复盘的解释层，用户会感觉这是“围绕目标岗位推进的求职学习系统”。

## 2.1 用户价值

### 短板与证据缺口

用户痛点：

```text
我不知道自己到底缺什么。
我不知道为什么系统让我学这个。
我不知道这些学习任务和目标岗位有什么关系。
我完成任务后，不知道能不能转化成简历或面试证据。
```

产品价值：

```text
把 JD 匹配、面试复盘、简历诊断里的差距沉淀成可跟踪对象。
把“泛泛地学习”变成“补齐某个岗位要求的证据”。
帮助用户判断哪些任务更优先，哪些任务只是锦上添花。
```

用户看这个模块时应该得到的信息：

```text
1. 我当前最缺什么。
2. 这个短板来自哪里。
3. 它影响哪个岗位或面试环节。
4. 我应该把它转成任务、忽略，还是等待已有任务推进。
```

### 复盘安排

用户痛点：

```text
我完成了任务，但不知道有没有掌握。
我学完后没有回顾节奏，很快忘掉。
我不知道哪些学习成果应该沉淀成面试表达。
我不知道什么时候该重新检查自己的准备状态。
```

产品价值：

```text
把“完成任务”后面的验证动作补上。
把学习结果转成复盘记录、面试表达、简历证据或下一轮任务。
让用户从一次性任务推进，进入可持续提升节奏。
```

用户看这个模块时应该得到的信息：

```text
1. 哪些内容需要回顾。
2. 为什么现在该复盘。
3. 复盘要验证什么。
4. 复盘后会影响哪些任务、短板或求职材料。
```

## 2.2 注意力层级

学习计划页不能让所有卡片都一样重要。页面注意力应该这样分配：

```text
一级注意力：当前学习状态 + 今日最该做的任务
  位置：Hero、右侧今日推进、任务看板中进行中/待推进首位。
  样式：更大标题、更强 CTA、更明显进度。

二级注意力：路线阶段和待推进任务
  位置：Roadmap、Kanban 主体。
  样式：标准卡片、清晰状态、可拖动、可查看详情。

三级注意力：短板和复盘
  位置：任务看板下方，作为解释和巩固层。
  样式：比任务卡更轻，不抢主任务，但有异常时提升权重。

四级注意力：历史、已解决、已忽略、已取消
  位置：详情页、筛选入口或历史视图。
  样式：不在主工作台常驻展示。
```

短板和复盘什么时候应该提升权重：

```text
高优先短板未转任务
  -> 在 Hero 判断里提示“优先补齐高风险短板”。
  -> 在右侧今日推进出现一条建议。

复盘今天到期
  -> 在右侧今日推进出现。
  -> 复盘模块第一条高亮“今天到期”。

任务全部完成但没有复盘
  -> 复盘模块从低权重空态提升为提示态。

没有任何短板
  -> 保持低权重解释，不要制造焦虑。
```

## 2.3 页面位置为什么这样放

短板与复盘不应该放在页面最顶部。

原因：

```text
用户进入学习计划页，第一需求是知道当前状态和今天做什么。
短板解释“为什么做”，复盘解释“做完怎么巩固”，它们是任务流的上下文，不是第一操作入口。
```

建议位置：

```text
Hero
  只摘取最重要的一条短板或复盘提醒，不展示完整列表。

右侧今日推进
  展示“今天该处理”的短板或到期复盘。

Kanban 下方
  展示完整的短板与复盘模块。
  用户看完任务后，自然能理解任务来源和完成后的闭环。
```

移动端：

```text
顺序为：
  当前学习状态
  今日推进
  学习任务
  短板与证据缺口
  复盘安排
  关联资料

原因：
  移动端屏幕短，先保证用户能看到“今天做什么”，再看解释和复盘。
```

## 3. 不按百分比触发

这两个模块不应该按“学习进度达到 30% / 70% / 100%”触发。

原因：

```text
短板来源于事实差距，不来源于进度百分比。
复盘来源于完成动作和回顾节奏，不来源于总进度百分比。
```

正确触发方式应该是事件驱动：

```text
JD 匹配保存 -> 生成或更新短板
面试复盘保存 -> 生成或更新短板 / 复盘安排
学习任务创建 -> 可关联短板
学习任务推进 -> 更新短板状态
学习任务完成 -> 生成复盘安排
复盘完成 -> 更新复盘状态，必要时推动短板 resolved
```

## 4. 短板状态机

现有状态：

```text
open
improving
resolved
ignored
```

建议语义：

```text
open
  已发现差距，但还没有明确任务或证据在处理。

improving
  已有关联学习任务、笔记、练习或项目补强正在处理。

resolved
  已有足够证据证明短板被补齐，例如任务完成、复盘通过、简历证据已更新。

ignored
  用户确认暂不处理，不再出现在主工作台。
```

页面展示规则：

```text
主卡片只展示：
  active + open
  active + improving

不展示：
  resolved
  ignored
  archived

后续可以在详情/历史里查看 resolved 和 ignored。
```

状态流转：

```text
JD 匹配发现 gap
  -> open

用户点击“转任务”或 Agent 创建关联任务
  -> improving

关联任务完成，但还没有可验证成果
  -> improving，提示需要复盘或沉淀证据

关联任务完成 + 有 check-in / note / resume_version / project evidence
  -> resolved

用户点击“暂不处理”
  -> ignored
```

## 5. 复盘状态机

现有状态：

```text
scheduled
done
skipped
cancelled
```

建议语义：

```text
scheduled
  已安排，等待到期。

due
  不新增数据库状态，用 next_review_at <= now 在展示层计算。

done
  用户已经完成复盘。

skipped
  用户跳过本次复盘，可重新安排下一次。

cancelled
  复盘安排取消，不再显示在主工作台。
```

页面展示规则：

```text
优先展示：
  due
  scheduled

弱化展示：
  skipped

不展示：
  done
  cancelled
  archived
```

触发规则：

```text
学习任务从 todo/doing/blocked -> done
  -> 如果没有 active review，自动创建 ReviewSchedule

任务 check-in 显示“已完成/掌握/产出完成”
  -> 如果任务被同步为 done，也创建 ReviewSchedule

面试复盘 Note 创建
  -> 创建 interview_rehearsal 类型复盘

阶段路线完成
  -> 可创建阶段复盘，但第一版先不自动做，避免过度打扰
```

默认复盘时间：

```text
普通任务：完成后 3 天
高优先短板关联任务：完成后 1 天
面试复盘：当天或次日
长期路线任务：完成后 7 天
```

第一版可以保守实现：

```text
所有任务完成后默认 next_review_at = completed_at + 3 days
如果任务关联 high weakness，则 next_review_at = completed_at + 1 day
```

## 6. 后端落地结构

新增一个领域服务，不放在 runtime，也不放在 Flutter：

```text
app/learning/insight_service.py
```

职责：

```python
class LearningInsightService:
    def sync_weaknesses_from_job_fit(application_id, fit_report) -> list[WeaknessTracker]:
        ...

    def mark_weaknesses_improving_for_task(task) -> list[WeaknessTracker]:
        ...

    def resolve_weaknesses_from_completed_task(task, evidence_refs) -> list[WeaknessTracker]:
        ...

    def ensure_review_for_completed_task(task) -> ReviewSchedule | None:
        ...

    def schedule_review_from_interview_note(note, application_id) -> ReviewSchedule | None:
        ...
```

这个服务只做确定性同步，不调用模型。

### 6.1 短板生成

第一版从 `JobFitReport.gaps` 和 `JobFitReport.recommendation == cautious/not_recommended` 提取短板。

去重键：

```text
application_id + source_report_id + normalized_gap_title
```

生成规则：

```text
gap 文本为空 -> 跳过
同源同标题已存在 -> 更新 last_observed_at / severity / evidence_refs
不存在 -> 创建 WeaknessTracker
```

严重度第一版规则：

```text
包含“核心/必须/硬性/关键/缺少/不足/风险” -> high
包含“建议/补充/优化/提升” -> medium
其他 -> medium
```

后续可以把 LLM 诊断结果接入，但第一版不依赖模型判断。

### 6.2 任务与短板关联

当任务创建或状态更新时：

```text
如果 task.weakness_ids 非空：
  对应 weakness 从 open -> improving

如果 task.state == done 且 evidence_refs 足够：
  对应 weakness 可从 improving -> resolved
```

第一版不要自动 resolved 太激进：

```text
只有用户完成复盘或提供 check-in 证据时，才自动 resolved。
单纯把任务拖到 done，只把短板保持 improving，并提示“需要复盘或证据沉淀”。
```

### 6.3 复盘生成

当任务状态更新为 `done`：

```text
查找 active review:
  learning_task_id == task.learning_task_id
  state in scheduled/skipped

如果存在：
  不重复创建

如果不存在：
  创建 ReviewSchedule
```

生成字段：

```text
title: 复盘：{task.title}
learning_task_id: task.learning_task_id
learning_plan_id: task.learning_plan_id
weakness_id: 如果任务关联单个 weakness，则填入
review_type: spaced_repetition
state: scheduled
next_review_at: completed_at + 3 days
evidence_refs: task.evidence_refs + task_id + plan_id
summary: 完成任务后自动安排，用于检查掌握程度和面试表达。
```

## 7. 后端改动点

第一批建议改这些位置：

```text
app/learning/insight_service.py
  新增领域服务。

app/tools/builtin_tools/career.py
  career_job_fit_report_save 成功后调用 sync_weaknesses_from_job_fit。

app/tools/builtin_tools/learning.py
  learning_task_create 成功后标记关联 weakness improving。
  learning_task_update_state 到 done 后 ensure_review_for_completed_task。
  learning_checkin_create 成功后根据 check-in 内容更新任务/短板/复盘。

app/api/learning.py
  admin 创建/更新 task 时也调用同一套 LearningInsightService，避免只有 Agent 路径生效。

app/runtime/tool_catalog.py
  暂不新增复盘工具。第一版复盘由确定性服务生成。
```

第二批再考虑：

```text
LearningReviewCreateTool
LearningReviewUpdateTool
LearningWeaknessIgnoreTool
LearningWeaknessResolveTool
```

先不急着把这些暴露给模型，避免又把可控产品逻辑变成 Agent 自由发挥。

## 8. 前端用户体验改造

### 8.1 模块标题与说明

当前标题可以保留，但必须增加解释文案。

短板模块：

```text
标题：短板与证据缺口
副标题：从 JD 匹配和面试复盘中沉淀，说明当前最该补齐的能力证据。
```

复盘模块：

```text
标题：复盘安排
副标题：完成学习任务后自动生成，用来回看掌握程度和面试表达。
```

### 8.2 空态

短板空态：

```text
当前暂无短板。
当你完成 JD 匹配、简历诊断或面试复盘后，系统会把关键差距沉淀到这里。

按钮：
  分析 JD 匹配
  从复盘提取短板
```

按钮行为：

```text
分析 JD 匹配
  如果已有求职项目和 JD：打开 JD 匹配页或触发当前页内 Agent 操作选择。
  不直接跳到聊天页。

从复盘提取短板
  如果已有面试复盘 Note：给出可选择的复盘记录。
  如果没有：提示先创建复盘笔记。
```

复盘空态：

```text
暂无复盘安排。
当学习任务完成后，系统会自动安排一次回顾；你也可以手动为重点任务创建复盘。

按钮：
  查看已完成任务
  手动安排复盘
```

如果没有已完成任务：

```text
按钮弱化：完成任务后自动生成
```

### 8.3 非空态卡片

短板卡片应显示：

```text
标题
严重度
来源：JD 匹配 / 面试复盘 / 简历诊断 / 手动
当前状态：待处理 / 处理中
关联任务数
建议动作：转任务 / 查看关联 / 忽略
```

复盘卡片应显示：

```text
标题
复盘类型
到期时间：今天 / 明天 / 具体日期
来源任务或短板
建议动作：开始复盘 / 改时间 / 跳过
```

### 8.4 不自动跳聊天

所有操作遵守 M44 后续修正原则：

```text
页面动作默认留在当前页面。
Agent 操作可以作为选项，但不强制跳转聊天。
生成过程可以以内联状态呈现。
完成后刷新当前模块。
```

## 9. 与学习路线的关系

这次也要顺手修正学习路线的语义，但不要混在同一个算法里。

学习路线进度应该来自任务状态，而不是静态默认值。

规则：

```text
路线阶段 progress = 该阶段关联任务完成数 / 该阶段任务总数
没有关联任务时 progress = 0
不因为“存在 plan”就给 80% 或 100%
```

短板和复盘只影响提示，不直接改路线进度：

```text
短板 high 多 -> 提示优先补短板
复盘 due 多 -> 提示先复盘
任务 done 多 -> 路线进度提升
```

## 10. 验收标准

后端：

```text
1. 保存 JobFitReport 后，能确定性生成或更新 WeaknessTracker。
2. 重复保存同一报告不会重复创建同类短板。
3. 创建关联 weakness 的任务后，weakness 从 open 进入 improving。
4. 任务更新到 done 后，自动创建一个 ReviewSchedule。
5. 重复把任务标记 done 不会重复创建复盘。
6. archived / ignored / resolved 不出现在学习计划主卡片。
```

前端：

```text
1. 两个模块空态能解释“它是什么、什么时候出现、下一步怎么做”。
2. 用户不需要猜“完成到多少进度才触发”。
3. 短板卡片能看到来源、状态和关联任务。
4. 复盘卡片能看到来源、到期时间和可执行动作。
5. 所有动作留在当前学习计划页，不默认跳聊天。
6. 移动端下两个模块纵向堆叠，文字不溢出。
```

测试：

```text
pytest tests/test_learning_insight_service.py
pytest tests/test_learning_api.py
pytest tests/test_career_tools.py -k job_fit
flutter build web
学习计划页手动走查：空态、有短板、有复盘、移动端
```

## 11. 分批落地

### M46-A：确定性领域服务

```text
新增 LearningInsightService。
补短板生成、任务完成复盘生成、去重逻辑。
补单元测试。
```

### M46-B：写入路径接入

```text
career_job_fit_report_save -> sync_weaknesses_from_job_fit
learning_task_create -> mark_weaknesses_improving_for_task
learning_task_update_state(done) -> ensure_review_for_completed_task
admin API 路径复用同一服务
```

### M46-C：前端模块 UX

```text
重写短板空态和复盘空态。
卡片显示来源、状态、关联对象、动作。
过滤 ignored/resolved/cancelled/done。
保留当前页内操作，不默认跳转聊天。
```

### M46-D：路线进度修正

```text
移除“存在 plan 就给高进度”的 fallback。
按任务状态计算路线阶段进度。
没有任务就是 0。
```

### M46-E：验证

```text
跑后端单测。
跑 flutter build web。
用真实页面验证：
  无短板/无复盘
  JD 匹配生成短板
  转任务后短板 improving
  完成任务后生成复盘
  复盘完成后不再主展示
```

## 12. 第一版不做

```text
不引入复杂推荐算法。
不让 Agent 自由决定是否创建复盘。
不把所有 gap 都自动创建成任务。
不自动把任务 done 直接判定短板 resolved。
不做复杂日历集成。
不做用户级通知系统。
不做跨项目全局学习画像。
```

## 13. 关键结论

这两个模块应该从“页面下方两个空卡片”变成学习计划的闭环解释器：

```text
短板告诉用户：为什么要学。
任务告诉用户：今天学什么。
复盘告诉用户：学完怎么巩固。
路线告诉用户：整体推进到哪里。
```

所以下一步不应该继续只调 UI 样式，而是先落 M46-A/B，把触发和状态机补完整，再做 M46-C 的页面表达。
