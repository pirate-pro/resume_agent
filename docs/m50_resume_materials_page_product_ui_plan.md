# M50 简历资料页产品化重构方案

日期：2026-06-01

目标：把「简历资料」页从“求职资产列表里的简历分组”重构成一个围绕基础简历、岗位定制版本、简历诊断和优化动作的简历管理工作台。本文只整理产品逻辑、页面结构、交互语义和 UI 细则，不直接改代码。

## 1. 当前实现的真实情况

当前简历相关展示主要在：

```text
flutter_app/lib/features/career/career_assets_panel.dart
flutter_app/lib/core/providers/career_assets_provider.dart
flutter_app/lib/core/models/api_models.dart
```

现有资产面板 `CareerAssetsPanel` 会加载：

```text
ResumeProfileView
CareerProfileView
JDAnalysisView
JobFitReportView
ResumeVersionView
CareerApplicationView
```

当前和简历资料直接相关的数据对象：

```text
ResumeProfileView
├── resume_profile_id
├── basic_info
├── education
├── work_experience
├── project_experience
├── skills
├── certificates
├── awards
├── self_evaluation
├── raw_text_artifact_id
└── diagnosis_artifact_id

ResumeVersionView
├── resume_version_id
├── base_resume_profile_id
├── target_jd_analysis_id
├── title
├── format
├── artifact_id
├── change_summary
├── keyword_strategy
└── risk_notes

CareerApplicationView
├── resume_profile_id
├── jd_analysis_id
├── job_fit_report_id
└── resume_version_ids
```

当前页面问题：

```text
1. 简历资料被混在“求职资产”里，用户感知不到这是一个独立产品模块。
2. ResumeProfile 和 ResumeVersion 的关系不清楚：基础简历、诊断、岗位定制版本、历史版本混在一起。
3. “生成简历 / 优化简历 / 查看报告”动作不够就地化，容易跳 Agent 或跳其他页面。
4. 用户不知道当前版本是给哪个岗位用的，也不知道为什么要优化。
5. 简历正文、AI 诊断、关联岗位、版本历史的层级不稳定，像资产展示，不像简历工作台。
```

## 2. 页面产品定位

「简历资料」页不是一个文件列表，也不是单纯的简历编辑器。它应该是：

> 围绕目标岗位，管理基础简历、定制版本、诊断建议和投递材料的求职材料工作台。

用户进入页面后应该立刻知道四件事：

```text
1. 我当前有哪些简历版本？
2. 当前版本服务哪个岗位，匹配度如何？
3. 这份简历还有哪些风险和优化点？
4. 下一步是预览、编辑、对比、生成岗位定制版，还是导出投递？
```

页面核心不是“有多少条 ResumeVersion”，而是：

```text
哪一版简历能投？
哪一版最适合当前岗位？
我应该怎么把简历优化成更强的求职材料？
```

## 3. 核心用户任务

简历资料页需要支持 6 个主任务：

```text
1. 查看当前基础简历画像和结构化事实。
2. 管理不同岗位对应的定制简历版本。
3. 预览简历正文和诊断报告。
4. 查看 AI 对当前版本的评分、亮点、缺失和风险。
5. 对比不同版本，理解每一版改了什么。
6. 从当前岗位或匹配报告生成新的定制简历草案，用户确认后落库。
```

明确边界：

```text
简历资料页负责简历材料的读、改、比、导出。
JD 匹配页负责解释岗位要求和匹配差距。
求职项目页负责跟踪岗位进度。
学习计划页负责把短板转成学习任务。
Agent 只负责生成草案或建议，不默认跳转聊天页，不直接替用户覆盖当前简历。
```

## 4. 对象语义先理清

页面里必须把这几个概念区分清楚：

| 对象 | 中文名 | 产品含义 | 页面展示方式 |
| --- | --- | --- | --- |
| `ResumeProfile` | 简历画像 | 从原始简历提取出的稳定事实，作为所有定制版本的基础 | 作为“基础简历 / 画像”卡，不直接当投递版本 |
| `ResumeVersion` | 简历版本 | 面向某个岗位或目标生成的可投递简历正文 | 作为版本列表和主预览对象 |
| `diagnosis_artifact_id` | 诊断报告 | 对基础简历的分析和改进建议 | 放在 AI 洞察 / 诊断入口中 |
| `artifact_id` | 简历正文文件 | 具体可预览、复制、导出的 Markdown/PDF 内容 | 中间主舞台预览 |
| `CareerApplication` | 关联岗位 | 当前简历版本服务的求职项目 | 右侧关联岗位和版本标签 |
| `JobFitReport` | 匹配报告 | 解释为什么要这样优化 | 右侧匹配依据和推荐动作 |

重要原则：

```text
ResumeProfile 不等于可投递简历。
ResumeVersion 才是可投递版本。
ResumeVersion 必须能追溯到 base_resume_profile_id 和 target_jd_analysis_id。
没有 target_jd_analysis_id 的版本，是通用版本或手动版本，不能假装是岗位定制版。
```

## 5. 页面整体布局

桌面端采用三栏布局：

```text
ResumeMaterialsPage
├── Sidebar
├── MainWorkspace
│   ├── TopHeader
│   └── ResumeContentGrid
│       ├── ResumeVersionPanel
│       ├── ResumeMainStage
│       └── ResumeContextRail
```

CSS 结构建议：

```css
.resume-page-layout {
  display: grid;
  grid-template-columns: 260px minmax(980px, 1fr);
  height: 100vh;
  background: #F6FAF8;
}

.resume-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.resume-content-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 320px minmax(560px, 1fr) 340px;
  gap: 14px;
  padding: 14px 18px 18px;
  overflow: hidden;
}
```

三栏职责：

| 区域 | 宽度 | 职责 |
| --- | ---: | --- |
| 左侧版本库 | 320px | 版本列表、筛选、基础简历入口、回收站 |
| 中间主舞台 | 自适应 | 当前简历预览、编辑、对比、生成草案确认 |
| 右侧上下文 | 340px | AI 洞察、推荐动作、关联岗位、关联资产 |

不要把所有东西都做成同等卡片。视觉权重：

```text
中间主舞台最高。
左侧版本库用于切换，不抢阅读。
右侧栏解释“为什么”和“下一步”。
底部版本历史只做辅助，不压过主版本。
```

## 6. 全局视觉 Token

沿用学习计划页和笔记页的产品 Token。

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

  --shadow-soft: 0 4px 16px rgba(15, 35, 25, 0.04);
  --shadow-card: 0 8px 24px rgba(15, 35, 25, 0.06);
  --shadow-dialog: 0 24px 70px rgba(15, 35, 25, 0.18);
}
```

## 7. 顶部 Header

Header 不要放太多业务动作，只保留全局动作：

```text
左侧：简历资料 + 说明
中间：全局搜索
右侧：刷新 / 导出 / 新建版本
```

推荐文案：

```text
标题：简历资料
副标题：管理基础简历、岗位定制版本和优化建议
搜索 placeholder：搜索简历版本、岗位、技能或修改记录...
```

Header 按钮：

```text
刷新
导出
新建版本
```

按钮语义：

```text
刷新：重新拉取 ResumeProfile / ResumeVersion / Application / FitReport。
导出：导出当前选中的 ResumeVersion。
新建版本：打开“创建简历版本”流程，不直接跳 Agent。
```

样式：

```css
.resume-header {
  height: 64px;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #E2ECE7;
  background: rgba(255, 255, 255, 0.9);
  backdrop-filter: blur(16px);
}

.resume-title {
  font-size: 22px;
  font-weight: 700;
  color: #1F2933;
}

.resume-subtitle {
  margin-top: 3px;
  font-size: 13px;
  color: #667085;
}

.resume-header-button {
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid #CFE3DA;
  background: #FFFFFF;
  color: #0F9F6E;
  font-size: 13px;
  font-weight: 600;
}

.resume-header-button.primary {
  background: #0F9F6E;
  color: #FFFFFF;
  border-color: #0F9F6E;
}
```

## 8. 顶部概览指标

Header 下方保留轻量指标条，回答“当前简历资产规模”。

指标建议：

```text
简历版本：ResumeVersion 数
已优化次数：ResumeVersion 中岗位定制版本数或版本历史数
针对岗位版本：target_jd_analysis_id 非空的版本数
最近更新：最新 ResumeProfile / ResumeVersion 更新时间
```

样式：

```css
.resume-metric-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 14px 18px 0;
}

.resume-metric-card {
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

.resume-metric-value {
  font-size: 22px;
  font-weight: 700;
  color: #1F2933;
}

.resume-metric-label {
  font-size: 12px;
  color: #667085;
}
```

点击行为：

```text
简历版本 → 清空筛选，显示全部版本。
已优化次数 → 只看有 change_summary 的版本。
针对岗位版本 → 只看 target_jd_analysis_id 非空版本。
最近更新 → 按更新时间倒序。
```

## 9. 左侧版本库

左侧不是普通列表，而是“版本库”。

结构：

```text
ResumeVersionPanel
├── 标题：版本库
├── 筛选：全部 / 当前使用 / 岗位定制 / 通用版本 / 归档
├── 新建版本按钮
├── 版本列表
└── 回收站 / 历史版本入口
```

筛选 Chip：

```css
.resume-filter-chip {
  height: 28px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  color: #667085;
  font-size: 12px;
  font-weight: 600;
}

.resume-filter-chip.active {
  background: #E8F7F0;
  border-color: #BFE5D4;
  color: #0F9F6E;
}
```

### 9.1 版本卡片

每个版本卡片展示：

```text
标题
用途标签：当前使用 / 岗位定制 / 通用版本
匹配度或 AI 评分
更新时间
目标岗位或关联项目
变更摘要前 1-2 条
```

卡片样式：

```css
.resume-version-tile {
  padding: 14px;
  border-radius: 14px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  margin-bottom: 10px;
  cursor: pointer;
  transition: all 0.16s ease;
}

.resume-version-tile:hover {
  border-color: #BFE5D4;
  box-shadow: 0 8px 20px rgba(15, 35, 25, 0.06);
  transform: translateY(-1px);
}

.resume-version-tile.selected {
  background: #F1FBF6;
  border-color: #0F9F6E;
}

.resume-version-title {
  font-size: 14px;
  line-height: 20px;
  font-weight: 700;
  color: #1F2933;
}

.resume-version-subtitle {
  margin-top: 5px;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
```

### 9.2 基础简历卡

基础简历 `ResumeProfile` 应该单独放在版本库顶部或列表首位。

展示：

```text
基础简历画像
姓名 / 技能数 / 项目数 / 经历数
诊断报告状态
更新时间
按钮：查看画像 / 预览诊断
```

注意：

```text
基础简历不是投递版本，视觉上不能和 ResumeVersion 完全一样。
应该用“画像 / 基础材料”的语气，而不是“当前简历版本”。
```

## 10. 中间主舞台

中间区域是用户最重要的阅读和编辑空间。

默认状态：

```text
ResumeMainStage
├── 当前版本头部
│   ├── 标题
│   ├── 版本标签
│   ├── 关联岗位
│   ├── 更新时间
│   └── 主操作
├── 简历预览
├── AI 修改摘要
└── 底部操作
```

### 10.1 当前版本头部

展示：

```text
标题：前端开发工程师 - 字节跳动 v3.2
标签：当前使用 / 岗位定制 / Markdown / 更新于
关联项目：字节跳动 · 前端开发工程师
评分：85 匹配度 / 优秀
```

按钮：

```text
预览简历
优化此版本
对比版本
生成新版本
```

按钮语义：

```text
预览简历：打开 artifact_id 内容，不修改数据。
优化此版本：打开“优化草案”弹窗，用户确认后才生成新版本。
对比版本：进入版本对比态。
生成新版本：从当前 ResumeProfile 和目标岗位创建一个新 ResumeVersion 草案。
```

样式：

```css
.resume-stage-panel {
  min-height: 0;
  padding: 18px;
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
  overflow-y: auto;
}

.resume-stage-title {
  font-size: 24px;
  line-height: 32px;
  font-weight: 700;
  color: #1F2933;
}

.resume-stage-meta {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
```

### 10.2 简历预览正文

简历正文展示来自 `ResumeVersion.artifact_id`。

预览区域：

```css
.resume-preview-body {
  margin-top: 16px;
  padding: 20px;
  border-radius: 16px;
  border: 1px solid #E2ECE7;
  background: #FFFFFF;
  font-size: 14px;
  line-height: 1.72;
  color: #1F2933;
}
```

如果 artifact 未加载：

```text
正在加载简历正文...
```

如果 artifact 缺失：

```text
当前版本缺少可预览正文
可以重新生成版本，或检查关联 artifact。
```

按钮：

```text
重新生成
查看详情
```

### 10.3 AI 修改摘要

`ResumeVersion.change_summary`、`keyword_strategy`、`risk_notes` 不要塞到右侧小卡里，应该在主舞台内有一个“版本说明”区域。

结构：

```text
版本说明
├── 本版改动
├── 关键词策略
└── 风险提醒
```

样式：

```css
.resume-version-summary {
  margin-top: 16px;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.resume-summary-card {
  padding: 14px;
  border-radius: 14px;
  background: #F9FCFA;
  border: 1px solid #E2ECE7;
}

.resume-summary-title {
  font-size: 13px;
  font-weight: 700;
  color: #1F2933;
}

.resume-summary-list {
  margin-top: 8px;
  font-size: 12px;
  line-height: 18px;
  color: #667085;
}
```

## 11. 右侧上下文栏

右侧固定四块：

```text
ResumeContextRail
├── AI 洞察
├── 推荐动作
├── 关联岗位
└── 关联资产
```

右侧栏样式：

```css
.resume-right-rail {
  min-height: 0;
  overflow-y: auto;
}

.resume-right-card {
  padding: 16px;
  border-radius: 18px;
  background: #FFFFFF;
  border: 1px solid #E2ECE7;
  box-shadow: 0 4px 16px rgba(15, 35, 25, 0.04);
  margin-bottom: 14px;
}
```

### 11.1 AI 洞察

作用：

```text
告诉用户当前简历版本能不能投、主要优势是什么、缺什么。
```

展示：

```text
整体评分：85 / 优秀
亮点：项目经验丰富、技术栈匹配度高
缺失：工程化指标、业务价值表达不足
推荐改写：把“负责开发”改成“支撑 xx 指标提升”
```

数据来源：

```text
优先：JobFitReport.resume_optimization_direction / gaps / matched_evidence
其次：ResumeProfile.diagnosis
再次：ResumeVersion.risk_notes / change_summary
```

注意：

```text
如果没有 JobFitReport，不要假装有匹配评分。
展示“尚未关联岗位，无法给出岗位匹配评分”。
```

### 11.2 推荐动作

动作要具体，不要泛化叫“AI 建议”。

推荐动作列表：

```text
优化项目描述
补充开源项目与技术栈证据
生成针对该岗位的求职信
对比当前版本与基础版本
导出投递版本
```

动作规则：

| 条件 | 推荐动作 |
| --- | --- |
| 有 `JobFitReport.gaps` | `根据差距优化简历` |
| 有 `ResumeVersion.risk_notes` | `处理风险提醒` |
| 没有定制版本但有 JD | `生成岗位定制简历` |
| 有多个版本 | `对比版本` |
| 有 artifact | `导出当前版本` |

推荐动作卡片：

```css
.resume-action-tile {
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

.resume-action-tile:hover {
  background: #F6FAF8;
  border-color: #BFE5D4;
}
```

### 11.3 关联岗位

展示当前版本服务的岗位：

```text
星河智能 · AI Agent 后端工程师
匹配度：78 / 良好
阶段：准备投递 / 面试准备
按钮：查看项目
```

如果一个 ResumeVersion 被多个 `CareerApplication.resume_version_ids` 引用，应展示最近或当前选中项目，并提供：

```text
查看全部关联岗位
```

### 11.4 关联资产

展示：

```text
基础简历画像
原始简历 artifact
诊断报告 artifact
JD 分析
匹配报告
生成简历 artifact
```

每个资产条目只显示：

```text
图标 / 标题 / 类型 / 更新时间 / 查看
```

不要在右侧显示长 ID。

## 12. 版本历史

版本历史应该放在主舞台下方或左侧底部，不要和当前版本抢主视觉。

结构：

```text
版本历史
├── v3.2 当前
├── v3.1 项目描述优化
├── v3.0 技术栈与亮点补充
├── v2.1 针对岗位优化
└── v1.8 基础版
```

每个历史项：

```text
版本标题
变更摘要
更新时间
按钮：预览 / 对比 / 恢复为当前
```

交互：

```text
预览：只切换主舞台预览，不改变当前使用版本。
对比：进入版本对比态。
恢复为当前：需要确认，并更新当前应用关联的 resume_version_ids 或当前版本标记。
```

## 13. 页面状态设计

### 状态 A：没有简历画像

空状态文案：

```text
还没有简历资料
上传一份简历后，系统会解析基础画像、生成诊断，并支持针对岗位生成定制版本。
```

按钮：

```text
上传简历
粘贴简历文本
```

不要显示空的版本库、空的 AI 洞察和空的历史时间线。

### 状态 B：有 ResumeProfile，但没有 ResumeVersion

展示：

```text
基础简历已解析
还没有可投递版本
```

主按钮：

```text
生成通用简历版本
选择岗位生成定制版本
```

右侧推荐动作：

```text
查看简历诊断
生成岗位定制简历
补充缺失信息
```

### 状态 C：有通用版本，没有关联岗位

展示：

```text
当前是通用版本
可以关联岗位后生成定制版，提高匹配度。
```

按钮：

```text
关联求职项目
生成岗位定制版
```

### 状态 D：有岗位定制版本

默认展示最新或当前使用版本。

主舞台：

```text
预览当前定制简历
展示版本说明
展示 AI 洞察
```

推荐动作：

```text
优化此版本
导出投递
对比基础版
准备面试表达
```

### 状态 E：草案生成中

点击“生成岗位定制简历”或“优化此版本”后，不要跳聊天页。

显示内联状态：

```text
AI 正在生成简历草案
正在分析：基础简历、目标岗位、匹配报告、当前版本和风险提醒...
```

生成完成后打开草案确认弹窗。

### 状态 F：生成失败

展示：

```text
生成失败，可能是缺少基础简历、JD 分析或匹配报告。
```

按钮：

```text
重试
查看缺失材料
```

不要无提示地回到原页面。

## 14. 新建 / 优化简历版本流程

页面级 AI 动作必须是“草案 → 用户确认 → 落库”。

### 14.1 生成岗位定制简历

触发位置：

```text
Header 新建版本
右侧推荐动作
空状态主按钮
求职项目关联卡
```

流程：

```text
选择目标岗位
↓
确认基础简历与匹配报告
↓
AI 生成简历草案
↓
用户预览与编辑
↓
保存为 ResumeVersion
↓
更新 CareerApplication.resume_version_ids
```

草案弹窗结构：

```text
ResumeVersionDraftDialog
├── 标题：生成岗位定制简历
├── 目标岗位
├── 草案正文预览
├── 修改摘要
├── 关键词策略
├── 风险提醒
└── 底部按钮
    ├── 取消
    ├── 继续编辑
    └── 保存为新版本
```

### 14.2 优化此版本

触发位置：

```text
当前版本头部
AI 洞察风险项
推荐动作
```

流程：

```text
选择优化方向
↓
AI 生成优化草案
↓
用户对比原版本
↓
保存为新版本，不覆盖原版本
```

优化方向：

```text
强化项目量化成果
补充岗位关键词
压缩冗余经历
突出工程化能力
优化面试表达
```

注意：

```text
默认不能覆盖当前 ResumeVersion。
每次优化都应该生成新的 ResumeVersion，保留版本历史。
```

### 14.3 对比版本

对比内容：

```text
左：原版本
右：新版本 / 目标版本
底部：AI 总结差异
```

对比维度：

```text
项目描述变化
关键词变化
风险变化
篇幅变化
投递岗位适配度
```

## 15. 按钮语义统一

避免继续出现泛化按钮：

```text
AI 建议
Agent
生成
更多操作
```

改成明确动作：

| 旧文案 | 新文案 | 含义 |
| --- | --- | --- |
| AI 建议 | 查看优化建议 | 看诊断，不落库 |
| 生成 | 生成岗位定制版 | 创建草案 |
| 优化 | 优化此版本 | 基于当前版本生成新草案 |
| Agent 执行 | AI 生成草案 | 就地生成，不跳聊天 |
| 预览 | 预览简历 | 只读 artifact |
| 导出 | 导出投递版 | 下载当前 ResumeVersion |
| 对比 | 对比版本 | 进入对比态 |

按钮大小：

```css
.resume-primary-button {
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  background: #0F9F6E;
  color: #FFFFFF;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid #0F9F6E;
}

.resume-secondary-button {
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  background: #FFFFFF;
  color: #0F9F6E;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid #BFE5D4;
}

.resume-danger-button {
  height: 36px;
  padding: 0 14px;
  border-radius: 10px;
  background: #FFFFFF;
  color: #EF4444;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid #FECACA;
}
```

hover：

```css
.resume-primary-button:hover {
  background: #0B8A5F;
}

.resume-secondary-button:hover {
  background: #E8F7F0;
}

.resume-danger-button:hover {
  background: #FFF1F1;
}
```

## 16. 数据动作映射

当前已有读能力：

| UI 内容 | 数据来源 |
| --- | --- |
| 基础简历画像 | `listCareerResumeProfiles()` |
| 职业画像 | `listCareerProfiles()` |
| 简历版本 | `listCareerResumeVersions()` |
| 关联岗位 | `listCareerApplications()` |
| JD 分析 | `listCareerJobs()` |
| 匹配报告 | `listCareerJobFitReports()` |
| 预览正文 | `fetchArtifactContent(sourceSessionId, artifactId)` |

需要补或明确的写能力：

| UI 动作 | 后端 / Agent 目标 |
| --- | --- |
| 上传简历 | artifact upload + resume profile creation workflow |
| 生成岗位定制版 | 结构化 draft API 或 project action `custom_resume` |
| 保存为新版本 | `career_resume_version_create` 或专用 API |
| 关联到项目 | `career_application_merge(resume_version_ids)` |
| 归档版本 | 后续补 `archive ResumeVersion` |
| 导出当前版本 | artifact 下载 |

第一阶段可以继续复用 Agent workflow，但前端必须就地显示：

```text
生成中状态
草案确认弹窗
保存成功提示
刷新版本库
```

不再让用户点了按钮后跳到聊天页才知道发生了什么。

## 17. 组件拆分建议

后续不要继续把简历页塞在 `career_assets_panel.dart` 里。建议拆成：

```text
flutter_app/lib/features/resumes/
├── resume_materials_page.dart
├── widgets/
│   ├── resume_header.dart
│   ├── resume_metric_strip.dart
│   ├── resume_version_panel.dart
│   ├── resume_version_tile.dart
│   ├── resume_profile_tile.dart
│   ├── resume_main_stage.dart
│   ├── resume_preview.dart
│   ├── resume_version_summary.dart
│   ├── resume_context_rail.dart
│   ├── resume_insight_card.dart
│   ├── resume_recommended_actions.dart
│   ├── resume_related_applications.dart
│   ├── resume_related_assets.dart
│   ├── resume_version_history.dart
│   ├── resume_version_draft_dialog.dart
│   └── resume_compare_dialog.dart
└── models/
    └── resume_ui_models.dart
```

页面主组件只负责组装：

```text
ResumeMaterialsPage
├── ResumeHeader
├── ResumeMetricStrip
└── ResumeContentGrid
```

## 18. UI 状态与交互反馈

### 刷新

按钮内显示 spinner，不要全页闪。

```text
刷新中...
```

### 预览加载

中间主舞台内显示 skeleton：

```text
正在加载简历正文...
```

### 生成草案

在主舞台顶部插入内联状态卡：

```css
.resume-inline-agent-status {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #F3EEFF;
  border: 1px solid #DDD0FF;
  color: #4C1D95;
  font-size: 13px;
}
```

### 保存成功

```text
已保存为新简历版本
[查看版本] [导出]
```

### 失败

```text
生成失败：缺少目标岗位或基础简历画像
[补充材料] [重试]
```

## 19. 移动端布局

移动端不要先显示右侧栏。顺序应该是：

```text
Header
概览指标
当前版本主舞台
版本库
AI 洞察
推荐动作
关联岗位
版本历史
关联资产
```

CSS：

```css
@media (max-width: 900px) {
  .resume-content-grid {
    display: block;
    padding: 12px;
    overflow-y: auto;
  }

  .resume-version-panel,
  .resume-stage-panel,
  .resume-right-card {
    margin-bottom: 12px;
  }

  .resume-metric-strip {
    display: flex;
    overflow-x: auto;
  }

  .resume-metric-card {
    min-width: 160px;
  }

  .resume-version-summary {
    grid-template-columns: 1fr;
  }
}
```

## 20. 实施顺序

### 第一阶段：产品语义和页面框架

```text
1. 从 career_assets_panel 中抽出简历资料独立页面。
2. 顶部改为“简历资料”Header。
3. 左侧改为版本库。
4. 中间改为当前简历主舞台。
5. 右侧固定为 AI 洞察 / 推荐动作 / 关联岗位 / 关联资产。
```

### 第二阶段：读能力产品化

```text
1. ResumeProfile 独立展示为基础简历画像。
2. ResumeVersion 作为可投递版本展示。
3. 支持 artifact 预览。
4. 支持版本历史和版本切换。
5. 支持关联岗位识别。
```

### 第三阶段：动作就地化

```text
1. 新建版本不跳聊天页，打开选择岗位和草案流程。
2. 优化版本不覆盖原版本，生成新版本草案。
3. 对比版本在当前页打开对比弹窗。
4. 导出当前版本直接下载 artifact。
```

### 第四阶段：AI 草案结构化

```text
1. 设计 ResumeVersion draft API。
2. draft 返回正文、change_summary、keyword_strategy、risk_notes。
3. 用户确认后保存 ResumeVersion。
4. 保存后自动 merge 到 CareerApplication.resume_version_ids。
```

## 21. 旧页面到新页面的替换表

| 当前内容 | 新页面处理 |
| --- | --- |
| 求职资产面板里的“简历”Tab | 独立简历资料页 |
| ResumeProfileCard | 基础简历画像卡 |
| ResumeVersionCard | 版本库条目 + 主舞台预览 |
| 预览诊断 | 右侧 AI 洞察 / 诊断入口 |
| 预览简历 | 中间主舞台正文 |
| 历史版本按钮 | 版本历史区 |
| custom_resume prompt action | 就地生成简历版本草案 |
| ID 展示 | 默认隐藏，详情里展示 |

## 22. 验收标准

改完后，用户应该能明确知道：

```text
左侧是简历版本库。
中间是当前可投递简历。
右侧是当前简历为什么好、哪里差、下一步做什么。
基础简历画像不是投递版本。
岗位定制版本必须和目标岗位关联。
AI 生成的是草案，用户确认后才保存为新版本。
每次优化都有版本历史，不覆盖旧版本。
```

页面体验目标：

```text
一眼知道当前简历是否可投。
一眼知道当前版本适配哪个岗位。
一眼知道还能优化什么。
一眼找到导出、预览、对比和新建版本。
```

## 23. 后端能力边界

这页后续开发时要特别区分“当前已有能力”和“产品需要补的真实能力”，不要用前端预设数据伪装成 AI 生成结果。

当前已有能力偏读取和资产预览：

```text
listCareerResumeProfiles
listCareerResumeVersions
listCareerApplications
listCareerJobFitReports
fetchArtifactContent
```

这些能力足够支撑：

```text
版本库
基础简历画像
简历版本预览
诊断报告入口
关联岗位
关联资产
```

但以下能力如果没有真实接口，就不能在 UI 上表现成“已经自动生成完成”：

```text
AI 生成岗位定制简历草案
AI 优化当前版本草案
保存人工编辑后的新 ResumeVersion
归档 / 恢复 ResumeVersion
导出 PDF / DOCX 投递版
版本 diff
```

第一阶段可以复用现有 Agent workflow，但必须保持产品诚实：

```text
点击后显示真实生成中状态。
结果必须来自后端或 Agent 返回，不使用固定 mock 草案。
如果没有结构化结果，展示失败和重试，不静默塞默认文案。
保存前必须给用户预览和编辑。
保存后才刷新版本库。
```

长期建议补专用接口：

```text
POST /api/resume-version-drafts/generate
POST /api/resume-version-drafts/{draft_id}/accept
POST /api/resume-versions
PATCH /api/resume-versions/{resume_version_id}
POST /api/resume-versions/{resume_version_id}/archive
POST /api/resume-versions/{resume_version_id}/export
```

## 24. 参考图还原重点

这页的视觉目标应接近用户给的简历资料参考图，核心不是堆满信息，而是让三件事一眼可见：

```text
当前选中的是哪一版简历。
这版简历为什么适合或不适合目标岗位。
用户下一步应该预览、优化、对比、导出，还是生成新版本。
```

必须优先还原的视觉结构：

```text
左侧：版本列表，不是普通资产列表。
中间：简历正文预览，占据最大面积。
右侧：AI 洞察和推荐动作，不放长篇正文。
底部：版本历史，不抢当前版本主视觉。
```

按钮层级：

```text
主按钮：生成岗位定制版 / 保存为新版本 / 导出投递版。
次按钮：预览 / 对比 / 编辑 / 查看项目。
危险按钮：归档 / 删除草案。
```

视觉细节：

```text
当前版本卡要有明显 selected 状态。
基础简历画像和可投递版本必须用不同标签区分。
评分、匹配度、风险、变更摘要要短，不要变成报告正文。
推荐动作每行只做一件事，文案必须是动词开头。
所有 Agent 动作都应该在当前页生成草案，不跳转到聊天界面。
```

最关键的一句话：

> 简历资料页要从“简历资产列表”，升级成“可投递材料的版本管理与优化工作台”。
