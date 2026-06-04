# M49 笔记页产品化重构方案

日期：2026-05-30

目标：把笔记页从“笔记列表 + 编辑器 + 若干 Agent 入口”重构成一个围绕求职项目的知识沉淀工作台。这个文档先写产品逻辑和 UI 细则，不直接改代码。后续开发时按本文逐项落地，避免继续出现按钮语义混乱、Agent 到处跳转、用户不知道内容怎么触发的问题。

## 1. 当前实现的真实情况

当前笔记页入口在：

```text
flutter_app/lib/features/notes/notes_library_page.dart
```

现有页面结构是：

```text
NotesLibraryPage
├── _NotesHeader
├── _NotesMetricStrip
├── _NotesListPanel
├── _NotesEditorPanel
└── _NotesRightRail
```

桌面端当前布局：

```text
顶部 Header
统计条
三列内容
├── 左侧 330px：笔记列表
├── 中间：笔记编辑 / 预览
└── 右侧 340px：当前笔记、推荐动作、关联项目、来源引用
```

移动端当前顺序：

```text
Header
统计条
右侧栏
笔记列表
编辑器
```

当前数据来源：

```text
CareerWorkbenchProvider
├── loadNotes()
├── createNote()
├── updateNote()
├── selectedApplicationSummary
└── selectedApplicationDetail
```

当前前端已接入的笔记写操作：

```text
createNote
updateNote
```

后端已有能力但当前前端未暴露完整产品动作：

```text
POST /api/notes/{note_id}/append
POST /api/notes/{note_id}/archive
```

当前笔记类型只有三类：

```text
note      记录
learning  学习
resource  资料
```

当前右侧推荐动作：

```text
新建自由笔记
整理面试复盘
转成学习任务
```

这里的问题是：动作有价值，但语义和位置不够准确。“整理面试复盘”是 Agent 草案生成，“转成学习任务”现在只是跳转学习计划页，不是把当前笔记转成任务。用户看到这些按钮时，不知道点完会在当前页产生什么变化。

## 2. 笔记页的产品定位

笔记页不是一个普通 Markdown 编辑器，也不是一个 Agent 聊天入口。它应该是：

> 围绕求职项目，把面试反馈、学习记录、资料摘录和 Agent 生成内容沉淀为可复用知识资产的工作台。

用户进入笔记页时，最关心的是四件事：

```text
1. 我已经沉淀了哪些关键内容？
2. 这些笔记分别服务哪个求职项目、岗位、学习任务或面试复盘？
3. 哪些笔记可以继续转成行动，例如学习任务、短板、复盘、简历素材？
4. 我如何快速写一条高质量、可检索、可复用的笔记？
```

所以页面要回答的不是“这里有多少条笔记”，而是：

```text
我保存了什么知识？
这些知识有什么用？
下一步我该继续写、整理、复盘，还是转成任务？
```

## 3. 页面核心用户任务

笔记页应该支持 5 个主任务：

```text
1. 快速浏览最近和重要笔记。
2. 新建或编辑一条求职相关笔记。
3. 查看某条笔记的来源、关联项目和引用证据。
4. 从笔记中提取可执行动作，例如学习任务、短板、复盘。
5. 使用 Agent 辅助整理，但结果必须留在当前上下文里，由用户确认后落库。
```

明确边界：

```text
笔记页负责沉淀和管理知识。
学习计划页负责推进任务。
求职项目页负责跟踪岗位进度。
Agent 负责辅助生成内容，不负责把用户直接带离当前页面。
```

## 4. 信息层级

笔记页的信息层级应该是：

```text
一级注意力
  当前笔记库状态、最近更新、当前选中笔记、主操作。

二级注意力
  笔记列表、阅读/编辑区、来源引用、关联项目。

三级注意力
  统计数字、标签筛选、推荐动作、相关资产。

四级注意力
  内部 note_id、source_session_id、完整 evidence_refs、归档记录。
```

页面上不应该每个卡片都一样重。具体原则：

```text
中间阅读/编辑区是主舞台。
左侧列表负责导航，不抢正文注意力。
右侧栏负责解释和下一步，不堆长文本。
Agent 动作只在它能改变当前笔记或当前上下文时出现。
```

## 5. 页面整体布局

桌面端建议继续采用三栏，但层级要更明确：

```text
NotesPage
├── Sidebar
├── MainWorkspace
│   ├── TopHeader
│   ├── NotesStatusBar
│   └── NotesContentGrid
│       ├── NotesListPanel
│       ├── NoteReaderEditor
│       └── NoteContextRail
```

CSS 结构建议：

```css
.notes-page-layout {
  display: grid;
  grid-template-columns: 260px minmax(880px, 1fr);
  height: 100vh;
  background: #F6FAF8;
}

.notes-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.notes-content-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 330px minmax(520px, 1fr) 340px;
  gap: 14px;
  padding: 14px 18px 18px;
  overflow: hidden;
}
```

三栏宽度：

| 区域 | 宽度 | 用途 |
| --- | ---: | --- |
| 左侧笔记列表 | 330px | 筛选、搜索、快速切换笔记 |
| 中间阅读/编辑 | 自适应 | 当前笔记主体，是主工作区 |
| 右侧上下文 | 340px | 来源、关联、下一步动作 |

注意：

```text
中间编辑区不能过窄。
右侧栏不要超过 340px。
列表卡片不要做得太宽，避免像后台表格。
```

## 6. 全局视觉 Token

沿用学习计划页已收敛的产品 Token。

```css
:root {
  --bg-page: #F6FAF8;
  --bg-card: #FFFFFF;
  --bg-card-soft: #F9FCFA;

  --primary: #0F9F6E;
  --primary-hover: #0B8A5F;
  --primary-light: #E8F7F0;
  --primary-lighter: #F1FBF6;

  --blue: #3B82F6;
  --blue-light: #EEF5FF;

  --purple: #7C3AED;
  --purple-light: #F3EEFF;

  --orange: #F59E0B;
  --orange-light: #FFF7E8;

  --danger: #EF4444;
  --danger-light: #FFF1F1;

  --text-main: #1F2933;
  --text-secondary: #667085;
  --text-tertiary: #98A2B3;

  --border: #E2ECE7;
  --border-strong: #CFE3DA;

  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;

  --shadow-soft: 0 4px 16px rgba(15, 35, 25, 0.04);
  --shadow-card: 0 8px 24px rgba(15, 35, 25, 0.06);
  --shadow-dialog: 0 24px 70px rgba(15, 35, 25, 0.18);
}
```

笔记类型颜色：

| 类型 | 文案 | 主色 | 浅底 | 用途 |
| --- | --- | --- | --- | --- |
| note | 随记 | `#F59E0B` | `#FFF7E8` | 想法、过程记录、杂项 |
| learning | 学习笔记 | `#7C3AED` | `#F3EEFF` | 学习总结、知识点、短板沉淀 |
| resource | 资料摘记 | `#0F9F6E` | `#E8F7F0` | 面经、文章、链接、报告摘录 |
| interview | 面试复盘 | `#3B82F6` | `#EEF5FF` | 后续建议新增类型 |
| action | 行动项 | `#0F9F6E` | `#F1FBF6` | 从笔记提取的任务草案 |

当前后端只有 `note / learning / resource`，`interview` 可以先在 UI 文档中定义为后续扩展，不在第一阶段强依赖。

## 7. 顶部 Header

Header 的目标是告诉用户当前在哪个页面，并提供少量确定性动作。

当前 Header 里有：

```text
刷新
复盘整理
新建笔记
```

建议改成：

```text
刷新
新建笔记
```

`复盘整理` 不应该放在页面 Header，因为它不是全局确定性动作。它应该出现在：

```text
1. 面试复盘空态中。
2. 当前笔记类型是面试/记录且内容像面试反馈时。
3. 右侧上下文的“从当前笔记生成复盘草案”动作里。
```

Header 结构：

```text
NotesHeader
├── title: 笔记
├── subtitle: 沉淀面试准备、复盘和资料摘记
├── optional project chip
└── actions
    ├── 刷新
    └── 新建笔记
```

样式：

```css
.notes-header {
  height: 64px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #E2ECE7;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(16px);
}

.notes-title {
  font-size: 22px;
  font-weight: 700;
  color: #1F2933;
}

.notes-subtitle {
  margin-top: 3px;
  font-size: 13px;
  color: #667085;
}

.notes-header-actions {
  display: flex;
  gap: 10px;
}
```

按钮：

```css
.notes-action-button {
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid #CFE3DA;
  background: #FFFFFF;
  color: #0F9F6E;
  font-size: 13px;
  font-weight: 600;
}

.notes-action-button.primary {
  background: #0F9F6E;
  border-color: #0F9F6E;
  color: #FFFFFF;
}

.notes-action-button:hover {
  background: #E8F7F0;
}

.notes-action-button.primary:hover {
  background: #0B8A5F;
}
```

## 8. 笔记状态条

当前 `_NotesMetricStrip` 展示：

```text
全部笔记
关联项目
资料引用
今日更新
```

这个方向可以保留，但视觉不要太重。它的作用是“快速概览笔记库状态”，不是主功能。

建议改成：

```text
全部笔记
项目笔记
学习笔记
资料摘记
今日更新
```

如果空间不足，桌面只展示 4 个，移动端横向滚动。

结构：

```text
NotesStatusBar
├── MetricChip: 全部笔记
├── MetricChip: 项目笔记
├── MetricChip: 学习笔记
├── MetricChip: 资料摘记
└── MetricChip: 今日更新
```

样式：

```css
.notes-status-bar {
  margin: 14px 18px 0;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.note-metric-card {
  height: 72px;
  padding: 14px;
  border-radius: 16px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
  display: flex;
  align-items: center;
  gap: 12px;
}

.note-metric-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
}

.note-metric-value {
  font-size: 22px;
  font-weight: 700;
  color: #1F2933;
}

.note-metric-label {
  margin-top: 2px;
  font-size: 12px;
  color: #667085;
}
```

交互：

```text
点击“全部笔记”清空筛选。
点击“学习笔记”切换到 learning。
点击“资料摘记”切换到 resource。
点击“今日更新”按更新时间筛选今天更新的笔记。
```

所有可点击统计卡都需要 hover：

```css
.note-metric-card.clickable {
  cursor: pointer;
}

.note-metric-card.clickable:hover {
  border-color: #BFE5D4;
  transform: translateY(-1px);
}
```

## 9. 左侧笔记列表

左侧列表的产品任务：

```text
帮助用户快速找到和切换笔记。
```

它不是主编辑区域，所以视觉要轻、密度适中、信息足够。

### 9.1 列表 Panel

结构：

```text
NotesListPanel
├── SectionHeader
│   ├── title: 笔记库
│   ├── subtitle: 按类型、项目和更新时间筛选
│   └── NewNoteIconButton
├── SearchInput
├── TypeFilterBar
├── SortRow
└── NoteList
    ├── NoteTile
    └── EmptyState
```

样式：

```css
.notes-list-panel {
  min-height: 0;
  padding: 14px;
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
  display: flex;
  flex-direction: column;
}

.notes-list-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}

.notes-list-title {
  font-size: 16px;
  font-weight: 700;
  color: #1F2933;
}

.notes-list-subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: #667085;
}
```

### 9.2 搜索与筛选

当前只有类型筛选。建议补一个轻量搜索：

```text
搜索标题、摘要、标签
```

搜索框样式：

```css
.note-search {
  height: 36px;
  padding: 0 12px;
  border-radius: 999px;
  border: 1px solid #E2ECE7;
  background: #F9FCFA;
  display: flex;
  align-items: center;
  gap: 8px;
}

.note-search input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: #1F2933;
}
```

筛选条：

```text
全部
随记
学习
资料
面试复盘（后续）
```

样式：

```css
.note-filter-bar {
  margin-top: 10px;
  display: flex;
  gap: 7px;
  overflow-x: auto;
}

.note-filter-chip {
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  color: #667085;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.note-filter-chip.active {
  background: #E8F7F0;
  border-color: #BFE5D4;
  color: #0F9F6E;
}
```

### 9.3 NoteTile

每条笔记卡片必须显示：

```text
类型图标
标题
摘要
更新时间
关联项目 chip
标签
来源：手写 / Agent 整理
```

卡片不应该显示过多正文，摘要最多两行。

样式：

```css
.note-tile {
  padding: 12px;
  border-radius: 14px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all 0.16s ease;
}

.note-tile:hover {
  border-color: #BFE5D4;
  box-shadow: 0 8px 20px rgba(15, 35, 25, 0.06);
}

.note-tile.selected {
  background: #F1FBF6;
  border-color: #0F9F6E;
}

.note-tile-title {
  font-size: 13px;
  line-height: 19px;
  font-weight: 700;
  color: #1F2933;
}

.note-tile-summary {
  margin-top: 5px;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.note-tile-meta {
  margin-top: 9px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 11px;
  color: #98A2B3;
}
```

### 9.4 列表空态

不要只写“暂无笔记”。空态必须解释用途。

无任何笔记：

```text
还没有笔记
你可以记录面试反馈、学习心得或资料摘录。笔记会作为后续简历优化、学习计划和面试准备的上下文。

[新建笔记] [从当前项目生成复盘草案]
```

筛选后无结果：

```text
没有符合筛选条件的笔记
可以切换类型，或新建一条当前类型的笔记。

[清空筛选] [新建此类型笔记]
```

## 10. 中间阅读/编辑区

中间区域是笔记页的主舞台。当前 `_NotesEditorPanel` 的问题是：即使是已有笔记，也容易看起来像“编辑表单”，阅读态的产品感不够。

建议采用“阅读优先，编辑显式进入”的模式。

### 10.1 状态设计

```text
无选中笔记
  显示欢迎/空态，引导新建或选择笔记。

选中已有笔记
  默认阅读态，展示标题、摘要、正文、标签、来源。

点击编辑
  进入编辑态，展示标题、摘要、标签、类型、Markdown 正文。

新建笔记
  直接进入编辑态，标题输入框自动聚焦。
```

### 10.2 阅读态结构

```text
NoteReader
├── Header
│   ├── type icon
│   ├── title
│   ├── type tag
│   ├── origin tag
│   ├── updated time
│   └── actions: 编辑 / 更多
├── SummaryBox
├── MarkdownBody
├── Tags
└── FooterActions
    ├── 编辑
    ├── 复制引用
    ├── 转为学习任务
    └── 归档
```

样式：

```css
.note-reader-panel {
  min-height: 0;
  padding: 18px;
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
  overflow-y: auto;
}

.note-reader-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.note-title {
  font-size: 24px;
  line-height: 32px;
  font-weight: 700;
  color: #1F2933;
}

.note-meta-row {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.note-summary-box {
  padding: 14px 16px;
  border-radius: 14px;
  background: #F9FCFA;
  border: 1px solid #E2ECE7;
  color: #4B5563;
  font-size: 13px;
  line-height: 21px;
  margin-bottom: 16px;
}

.note-markdown-body {
  padding: 18px;
  border-radius: 16px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  font-size: 14px;
  line-height: 1.7;
  color: #1F2933;
}
```

Markdown 正文要求：

```text
标题层级清楚。
代码块、列表、引用块样式稳定。
长链接可换行。
移动端不横向溢出。
```

### 10.3 编辑态结构

```text
NoteEditor
├── TitleInput
├── TypeSelector
├── TagsInput
├── SummaryInput
├── BodyModeSwitch: 编辑 / 双栏 / 预览
├── MarkdownEditor
└── Footer
    ├── 取消
    └── 保存笔记
```

编辑态样式：

```css
.note-editor-panel {
  min-height: 0;
  padding: 18px;
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
  overflow-y: auto;
}

.note-form-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
}

.note-input {
  min-height: 42px;
  border-radius: 12px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  padding: 10px 12px;
  font-size: 13px;
  color: #1F2933;
}

.note-body-editor {
  min-height: 520px;
  border-radius: 14px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  padding: 14px;
  font-size: 13px;
  line-height: 1.56;
}
```

编辑模式切换：

```text
编辑：只显示 Markdown 输入。
双栏：左编辑，右预览。
预览：只显示渲染结果。
```

按钮语义：

```text
保存笔记：确定性保存 createNote/updateNote。
取消：新建草稿则丢弃，已有笔记则回到阅读态。
归档：后续接入 archiveNote，需要确认弹窗。
```

## 11. 右侧上下文栏

右侧栏的目标：

```text
解释当前笔记从哪里来、关联什么、下一步能变成什么。
```

不是把所有 Agent 入口堆在一起。

建议右侧栏固定为 4 张卡：

```text
1. 当前笔记上下文
2. 推荐下一步
3. 关联项目
4. 来源引用
```

### 11.1 当前笔记上下文

显示：

```text
类型
来源：手写 / Agent 整理
更新时间
关联项目
标签
来源数量
```

样式：

```css
.note-context-card {
  padding: 16px;
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
  margin-bottom: 14px;
}

.note-context-title {
  font-size: 15px;
  font-weight: 700;
  color: #1F2933;
  margin-bottom: 12px;
}

.note-context-row {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
}

.note-context-label {
  color: #98A2B3;
}

.note-context-value {
  color: #1F2933;
  font-weight: 500;
}
```

### 11.2 推荐下一步

这里必须按当前笔记类型和内容决定，不要展示一组泛化动作。

推荐动作规则：

```ts
if (note == null) {
  actions = [
    "新建笔记",
    "从当前项目生成复盘草案"
  ];
}

if (note.noteType == "learning") {
  actions = [
    "转为学习任务",
    "生成复盘问题",
    "提取关键知识点"
  ];
}

if (note.noteType == "resource") {
  actions = [
    "生成资料摘要",
    "提取面试题",
    "关联到求职项目"
  ];
}

if (note.noteType == "note") {
  actions = [
    "整理成复盘",
    "提取行动项",
    "转为学习任务"
  ];
}
```

第一阶段建议只保留确定性强的 3 个：

```text
新建笔记
整理成复盘草案
提取行动项
```

按钮文案不要用：

```text
生成
Agent
建议
查看
```

要用：

```text
新建
整理
提取
转任务
```

推荐动作样式：

```css
.note-action-tile {
  min-height: 58px;
  padding: 10px 12px;
  border-radius: 12px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  display: grid;
  grid-template-columns: 34px 1fr auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 8px;
  cursor: pointer;
}

.note-action-tile:hover {
  background: #F6FAF8;
  border-color: #BFE5D4;
}

.note-action-title {
  font-size: 13px;
  font-weight: 700;
  color: #1F2933;
}

.note-action-subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: #667085;
  line-height: 17px;
}

.note-action-button {
  height: 28px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid #BFE5D4;
  background: #FFFFFF;
  color: #0F9F6E;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
```

### 11.3 关联项目

当前实现已经有“关联项目”。建议保留，但增强语义：

```text
这条笔记当前服务哪个求职项目？
它能否作为该项目的面试准备、学习计划或简历优化上下文？
```

显示：

```text
项目标题
公司 / 岗位
项目阶段
匹配度或当前状态
查看项目按钮
```

如果未关联：

```text
未关联求职项目
关联后，这条笔记会参与该项目的简历优化、面试准备和学习建议。

[关联项目]
```

### 11.4 来源引用

来源引用是笔记页的产品价值之一，应该保留。

显示：

```text
来源类型
来源标题
引用片段
跳转入口
```

第一阶段如果不能跳转来源，至少要清楚显示来源是什么。

来源类型映射：

```text
artifact              来源文件
career_application    求职项目
resume_profile        简历画像
career_profile        职业画像
jd_analysis           JD 分析
job_fit_report        匹配报告
resume_version        简历版本
```

空态：

```text
暂无来源引用
手写笔记可以不带来源；Agent 整理或资料摘录会在这里显示来源，方便后续追溯。
```

## 12. Agent 动作设计

核心原则：

```text
Agent 动作必须就地生成草案，不跳转聊天页。
Agent 只负责生成内容，用户确认后才写入笔记、任务或复盘。
```

### 12.1 整理成复盘草案

触发位置：

```text
右侧推荐动作
笔记阅读态 Footer
空态中“从当前项目生成复盘草案”
```

输入：

```text
当前笔记内容
当前求职项目
当前 source_refs
当前 session_id
```

输出：

```text
复盘草案
├── 面试背景
├── 被问到的问题
├── 回答表现
├── 暴露短板
├── 后续行动
└── 可转学习任务
```

展示方式：

```text
打开 NoteDraftDialog，不跳转会话。
用户可以编辑、采纳为新笔记、追加到当前笔记或取消。
```

弹窗样式：

```css
.note-draft-dialog {
  width: min(760px, calc(100vw - 40px));
  max-height: min(760px, calc(100vh - 72px));
  padding: 22px;
  border-radius: 20px;
  background: #FFFFFF;
  box-shadow: 0 24px 70px rgba(15, 35, 25, 0.18);
  overflow-y: auto;
}

.note-draft-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.note-draft-title {
  font-size: 20px;
  font-weight: 700;
  color: #1F2933;
}

.note-draft-desc {
  margin-top: 6px;
  font-size: 13px;
  line-height: 21px;
  color: #667085;
}
```

生成中状态：

```text
正在整理复盘草案
正在分析当前笔记、关联项目和来源引用...
```

失败状态：

```text
复盘草案生成失败
可以重试，或手动新建一条复盘笔记。
```

### 12.2 提取行动项

产品意义：

```text
把笔记里的“我需要做什么”提取为可执行动作。
```

输出不应该直接创建任务，而是生成草案：

```text
行动项草案
├── 标题
├── 为什么要做
├── 预计耗时
├── 优先级
├── 关联短板
└── 建议去向：学习任务 / 复盘 / 项目备注
```

用户动作：

```text
采纳为学习任务
追加到当前笔记
忽略
编辑
```

### 12.3 生成资料摘要

只对 `resource` 类型常驻。

产品意义：

```text
把长资料变成可检索、可复用的摘要。
```

输出：

```text
核心观点
关键技术点
面试可用表达
可转学习任务
来源链接或引用
```

### 12.4 Agent 动作当前实现落地方式

短期可以继续使用：

```text
sendCareerPromptAction(...)
```

但前端不能只显示一个全局 loading 条。需要在触发位置显示状态：

```text
右侧动作 tile -> loading
弹窗内 -> 生成中
完成后 -> 草案结果
```

长期建议新增结构化接口：

```text
POST /api/notes/{note_id}/draft-review
POST /api/notes/{note_id}/extract-actions
POST /api/notes/{note_id}/summarize-resource
```

前端拿到结构化 draft 后再由用户确认：

```text
createNote
appendNote
createLearningTask
```

## 13. 新建笔记流程

当前 `_startDraft` 会在中间编辑器创建 `note_draft`，这个方向是对的。

建议保留，但强化体验：

```text
点击新建笔记
↓
中间区域进入新建编辑态
↓
标题输入自动聚焦
↓
默认类型跟当前筛选一致
↓
默认关联当前求职项目
```

新建笔记默认值：

```text
title: ""
noteType: 当前筛选类型，若为全部则 note
summary: ""
tags: []
bodyMarkdown: ""
relatedApplicationId: 当前 selectedApplication
origin: user
```

不要默认生成：

```text
# 新建笔记
```

原因：用户保存时容易留下无意义标题或正文。更好的做法是 placeholder。

编辑器 placeholder：

```text
记录面试反馈、学习心得、资料摘录或求职过程中的关键想法...
```

保存校验：

```text
标题不能为空。
正文不能为空。
类型必须为 note / learning / resource。
标签最多 8 个。
```

保存成功：

```text
Toast: 笔记已保存
列表选中新笔记
右侧上下文刷新
关联项目详情刷新
```

## 14. 归档 / 删除逻辑

用户后续肯定会需要删除或归档笔记。后端已有 `archive_note`，当前前端没有完整入口。

建议 UI 文案使用：

```text
归档笔记
```

不要直接叫“删除”，因为后端是 archive，不是 hard delete。

位置：

```text
阅读态右上更多菜单
编辑态底部低权重危险按钮
NoteTile 更多菜单
```

确认弹窗：

```text
归档这条笔记？
归档后默认不会在笔记库和检索结果中显示，但可以在归档记录中恢复。

[取消] [归档]
```

第一阶段如果没有恢复功能，就不要承诺恢复，只写：

```text
归档后默认不会显示在笔记库中。
```

## 15. 追加内容逻辑

后端已有 `append_note`。这是笔记产品的重要能力。

推荐场景：

```text
面试后追加复盘。
学习任务完成后追加学习记录。
资料阅读后追加摘录。
Agent 生成摘要后追加到当前笔记。
```

UI 设计：

```text
阅读态 Footer:
  [追加记录]

右侧推荐动作:
  追加今天的进展
```

追加弹窗：

```text
AppendNoteDialog
├── 当前笔记摘要
├── 追加内容输入框
├── 可选标签
├── 可选来源
└── 保存追加
```

保存后：

```text
调用 append_note
正文末尾追加一段带日期的小节
刷新当前笔记
```

追加格式建议：

```markdown
## 2026-05-30 追加记录

...
```

## 16. 短板、学习任务、复盘的联动

笔记页不要替代学习计划页，但可以成为输入来源。

### 16.1 从笔记转学习任务

触发：

```text
右侧推荐动作：提取行动项
草案弹窗：采纳为学习任务
```

不要直接跳转到学习计划页。

流程：

```text
提取行动项
↓
展示任务草案
↓
用户采纳 / 编辑 / 忽略
↓
调用 createLearningTask
↓
提示：已创建学习任务
↓
可选跳转：查看学习计划
```

### 16.2 从笔记生成短板

触发：

```text
面试复盘笔记
学习笔记里出现“不会、薄弱、没答好、缺少经验”等内容
```

输出：

```text
短板草案
├── 短板标题
├── 证据句子
├── 影响岗位匹配原因
├── 推荐学习任务
```

第一阶段可以不做常驻按钮，只在复盘草案结果里带“可转短板”。

### 16.3 从笔记生成复盘

触发：

```text
用户有面试反馈或学习记录。
```

输出：

```text
复盘笔记草案
```

用户确认后：

```text
createNote(noteType: note 或后续 interview)
```

## 17. 右侧栏动作命名表

替换当前模糊动作：

| 旧文案 | 问题 | 新文案 | 行为 |
| --- | --- | --- | --- |
| 新建自由笔记 | “自由”不说明用途 | 新建笔记 | 在中间打开新建编辑态 |
| 整理面试复盘 | 位置泛化 | 整理成复盘草案 | 在当前页弹出复盘草案 |
| 转成学习任务 | 当前只是跳转 | 提取行动项 | 先生成任务草案，再采纳 |
| 生成 | 不知道生成什么 | 整理 / 提取 / 新建 | 根据动作具体命名 |
| 查看 | 不知道查看哪里 | 查看项目 / 查看来源 / 查看学习计划 | 明确目标 |

## 18. 页面空态汇总

### 18.1 无任何笔记

```text
还没有笔记
把面试反馈、学习心得和资料摘录沉淀下来，后续可以用于简历优化、学习计划和面试准备。

[新建笔记] [从当前项目生成复盘草案]
```

### 18.2 未选择笔记

```text
选择一条笔记查看内容
你可以从左侧笔记库选择，也可以新建一条笔记。

[新建笔记]
```

### 18.3 当前筛选无结果

```text
没有符合条件的笔记
当前筛选下没有内容，可以清空筛选或新建一条当前类型的笔记。

[清空筛选] [新建笔记]
```

### 18.4 当前笔记无来源

```text
暂无来源引用
手写笔记可以没有来源。Agent 整理、资料摘录和报告引用会在这里显示来源。
```

### 18.5 当前笔记无关联项目

```text
未关联求职项目
关联项目后，这条笔记会参与该项目的复盘、学习建议和简历优化。

[关联项目]
```

## 19. 移动端布局

当前移动端把右侧栏放在列表前，这会让用户先看到上下文卡片，而不是笔记本身。建议重排。

移动端顺序：

```text
NotesHeader
NotesStatusBar
NotesListPanel
NoteReaderEditor
NoteContextActions
RelatedProject
SourceRefs
```

原因：

```text
移动端用户最需要先找到笔记。
其次阅读或编辑当前笔记。
来源和关联信息可以放后面。
```

CSS：

```css
@media (max-width: 900px) {
  .notes-content-grid {
    display: block;
    padding: 12px;
    overflow-y: auto;
  }

  .notes-list-panel,
  .note-reader-panel,
  .note-context-card {
    margin-bottom: 12px;
  }

  .notes-status-bar {
    display: flex;
    overflow-x: auto;
  }

  .note-metric-card {
    min-width: 160px;
  }
}
```

手机端编辑器：

```text
默认只显示编辑或预览。
不启用双栏实时模式。
底部保存按钮固定在编辑器底部。
```

## 20. 组件拆分建议

最终组件结构：

```text
NotesLibraryPage
├── NotesHeader
├── NotesStatusBar
├── NotesWorkspace
│   ├── NotesListPanel
│   │   ├── NotesSearchBar
│   │   ├── NoteTypeFilterBar
│   │   ├── NoteTile
│   │   └── NotesListEmptyState
│   ├── NoteReaderEditor
│   │   ├── NoteReader
│   │   ├── NoteEditor
│   │   ├── NoteModeSwitch
│   │   └── NoteFooterActions
│   └── NoteContextRail
│       ├── CurrentNoteContextCard
│       ├── NoteNextActionsCard
│       ├── RelatedProjectCard
│       └── SourceRefsCard
├── NoteDraftDialog
├── ExtractActionDraftDialog
├── AppendNoteDialog
└── ArchiveNoteConfirmDialog
```

先不要把所有逻辑塞在 `notes_library_page.dart` 一个文件里。建议后续拆到：

```text
flutter_app/lib/features/notes/
├── notes_library_page.dart
├── widgets/
│   ├── notes_header.dart
│   ├── notes_status_bar.dart
│   ├── notes_list_panel.dart
│   ├── note_reader_editor.dart
│   ├── note_context_rail.dart
│   ├── note_draft_dialog.dart
│   ├── append_note_dialog.dart
│   └── archive_note_confirm_dialog.dart
└── models/
    └── note_ui_models.dart
```

## 21. 数据与动作映射

| UI 动作 | 当前可用 API / Provider | 第一阶段行为 | 后续增强 |
| --- | --- | --- | --- |
| 刷新 | `provider.loadNotes(force: true)` | 刷新列表和当前笔记 | 保留 |
| 新建笔记 | `provider.createNote` | 中间编辑态新建 | 支持模板 |
| 编辑笔记 | `provider.updateNote` | 修改标题、正文、摘要、标签、类型 | 支持关联项目修改 |
| 归档笔记 | 后端 `/api/notes/{id}/archive` | 需要补 ApiService/provider | 支持恢复 |
| 追加记录 | 后端 `/api/notes/{id}/append` | 需要补 ApiService/provider | 支持来源引用 |
| 整理复盘草案 | `sendCareerPromptAction` | 当前页显示生成中，结果作为草案 | 后续结构化 draft API |
| 提取行动项 | `sendCareerPromptAction` | 当前页显示草案，用户采纳 | 后续 createLearningTaskFromDraft |
| 关联项目 | API 已支持 related_application_id | 当前 provider updateNote 未暴露 relatedApplicationId | 增加关联项目选择器 |
| 来源跳转 | 当前仅显示 sourceRefs | 先显示来源 | 后续可跳转到源对象 |

## 22. 交互反馈规范

所有按钮都必须有明确反馈：

```text
点击后立即进入 loading。
成功后说明创建或更新了什么。
失败后说明失败原因和可重试动作。
```

示例：

```text
保存笔记中...
笔记已保存
保存失败，请重试
```

Agent 动作：

```text
正在整理复盘草案...
已生成复盘草案，请确认是否保存
生成失败，可以重试或手动新建笔记
```

Hover：

```css
button:hover {
  transform: translateY(-1px);
}

button:active {
  transform: translateY(0);
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

不允许出现：

```text
按钮可点但没有变化。
按钮灰色但仍然可点。
点了跳转到 Agent 聊天页但当前页面没有任何结果。
多个按钮文案一样但行为不同。
```

## 23. 实施顺序

### 第一阶段：先收语义，不大改架构

目标：用户不再困惑按钮含义。

改动：

```text
1. Header 删除“复盘整理”，只保留“刷新 / 新建笔记”。
2. 右侧“整理面试复盘”改为“整理成复盘草案”。
3. 右侧“转成学习任务”改为“提取行动项”，暂时显示草案或提示能力建设中。
4. 已有笔记默认阅读态，不直接像编辑表单。
5. 新建笔记进入编辑态，保存后回到阅读态。
6. 空态文案补齐用途和触发方式。
```

### 第二阶段：视觉重构

目标：页面像知识工作台，不像后台列表。

改动：

```text
1. 统一 Header、统计卡、列表卡、阅读区、右侧栏样式。
2. 左侧列表增加搜索和更清楚的类型筛选。
3. 中间阅读区加强标题、摘要、Markdown 正文层级。
4. 右侧栏固定为“当前笔记 / 推荐下一步 / 关联项目 / 来源引用”。
5. 移动端重排为列表优先。
```

### 第三阶段：补确定性能力

目标：笔记管理闭环。

改动：

```text
1. 前端接入 archiveNote。
2. 前端接入 appendNote。
3. 支持修改 relatedApplicationId。
4. 支持来源引用点击跳转。
```

### 第四阶段：Agent 草案就地展示

目标：Agent 辅助，但用户确认后落库。

改动：

```text
1. 复盘草案弹窗。
2. 行动项草案弹窗。
3. 资料摘要草案弹窗。
4. 草案支持采纳、编辑、忽略。
```

### 第五阶段：后端结构化升级

目标：减少 prompt 直连页面动作。

建议新增：

```text
POST /api/notes/{note_id}/draft-review
POST /api/notes/{note_id}/extract-actions
POST /api/notes/{note_id}/summarize-resource
```

返回结构化 draft，而不是让前端从聊天结果里猜。

## 24. 验收标准

页面改完后，用户应该能明确知道：

```text
这页是用来沉淀求职知识的。
左侧是找笔记。
中间是读和写当前笔记。
右侧是解释当前笔记有什么用。
Agent 只在当前上下文里生成草案，不把用户带走。
```

具体标准：

```text
1. 新建笔记可以完整完成，不跳转聊天页。
2. 选择笔记后默认阅读态清晰，不像误进入编辑表单。
3. 编辑、保存、取消、归档、追加记录语义清楚。
4. 推荐动作不再出现泛化“生成 / 建议 / Agent”。
5. Agent 生成内容必须在当前页显示状态和结果。
6. 来源引用和关联项目能解释笔记为什么有用。
7. 移动端不横向溢出，阅读和编辑都可用。
8. 所有按钮 hover、loading、disabled、error 状态完整。
```

## 25. 本轮不做的事

这份文档不直接要求本轮实现以下内容：

```text
1. 新增后端结构化 Agent draft API。
2. 新增真正的笔记集合 collection 管理页。
3. 新增全文检索页面。
4. 新增恢复归档笔记 UI。
5. 新增多人用户、头像、权限。
```

这些可以后续做，但不应该阻塞笔记页第一阶段产品化。
