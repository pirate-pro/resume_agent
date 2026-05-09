# 求职资产面板 UI 重设计方案

## 目标

本阶段优化右侧「求职资产」面板的信息层级和预览体验，让用户在等待简历诊断、JD 分析、匹配报告生成后，能快速理解已有资产、打开详情、预览或下载对应文件。

核心目标：

- 降低右侧面板视觉噪音，避免统计、筛选、卡片信息重复堆叠。
- 隐藏默认无意义的调试 ID，把 ID 放入详情或预览弹层中。
- 点击「预览」后立即给出可见反馈，并打开可阅读的 Markdown 预览弹层。
- 保留调试能力：详情弹层和预览弹层仍提供记录 ID、artifact ID、复制入口。

## 布局结构

### 1. `CareerAssetsPanel`

右侧资产面板根组件。

职责：

- 负责加载求职资产数据。
- 监听聊天流式输出结束后刷新资产。
- 承载顶部栏、筛选条、资产列表。

结构：

```text
CareerAssetsPanel
  -> CareerAssetsHeader
  -> CareerAssetTabBar
  -> CareerAssetList
```

不再在列表底部长期放置 `CareerAssetDetailPane` 和 `ArtifactPreviewPanel`，详情与预览改为按需弹出。

### 2. `CareerAssetsHeader`

面板顶部。

展示内容：

- 图标：求职资产。
- 标题：求职资产。
- 副标题：总记录数、最近更新时间或刷新状态。
- 操作：刷新、关闭。

目标效果：

- 顶部信息紧凑，避免和筛选条重复展示分类数量。
- 刷新中用动态图标或轻量 loading 状态。

### 3. `CareerAssetTabBar`

单行横向筛选条。

Tab：

- 全部
- 简历
- 画像
- JD
- 匹配
- 版本

每个 Tab 显示数量，例如 `简历 4`。选中态使用更强底色和边框，不再额外保留一行统计卡片。

### 4. `CareerAssetList`

资产列表容器。

职责：

- 根据当前 Tab 生成资产卡片。
- 空状态显示当前分类暂无记录。
- 将详情和预览动作传给卡片。

视觉要求：

- 列表卡片间距控制在 8-10px。
- 卡片高度比当前版本更紧凑。
- 不展示长 ID，避免用户误以为是错误信息。

### 5. `CareerAssetCard`

统一资产卡片外壳，替代各类型卡片重复布局。

卡片信息：

- 类型图标。
- 类型标签。
- 主标题。
- 状态徽标。
- 更新时间。
- 2-3 个摘要指标。
- 操作区：详情、预览。

不同资产的摘要：

```text
简历画像：技能数、项目数、经历数
职业画像：目标岗位、城市、优势数量
JD 分析：必备技能、关键词、风险信号
匹配报告：总分、推荐结论、差距数量
简历版本：格式、变更摘要数量、风险提示数量
```

卡片交互：

- 点击「详情」打开详情弹层。
- 点击「预览」读取 artifact 并打开预览弹层。
- 卡片整体点击不再承担隐式详情行为，避免误触。

### 6. `CareerAssetDetailSheet`

详情弹层。

职责：

- 展示结构化产品记录。
- 展示调试信息。

内容结构：

```text
标题区：
  类型、标题、状态

摘要区：
  关键字段

调试信息：
  record_id
  source_session_id
  source_artifact_id
  evidence_refs
  created_at
  updated_at
```

调试信息默认可见但弱化样式，后续正式版本可以折叠或隐藏。

### 7. `ArtifactPreviewSheet`

Artifact 文件预览弹层。

职责：

- 展示 artifact 正文。
- 提供复制 ID、下载、关闭操作。

内容结构：

```text
标题区：
  文件标题
  artifact_id
  字符数 / 是否截断

操作区：
  复制 ID
  下载
  关闭

正文区：
  Markdown 渲染内容
```

交互要求：

- 点击预览后立刻显示 loading 弹层。
- 读取成功后替换为正文。
- 读取失败后在弹层内展示错误。
- Markdown 正文必须渲染标题、加粗、列表、表格、行内代码。

## 预览链路

资产记录仍然只保存 artifact 引用，不直接读取文件路径。

预览参数：

```text
source_session_id
artifact_id
```

前端调用：

```text
CareerAssetsProvider.previewArtifact(
  sourceSessionId,
  artifactId,
)
```

成功后使用 `SessionArtifactContentView` 渲染 `ArtifactPreviewSheet`。

下载使用后端下载 URL：

```text
/api/sessions/{session_id}/artifacts/{artifact_id}/download
```

## 验收标准

- 右侧面板不再出现两行重复分类统计。
- 资产卡片默认不展示长 ID。
- 点击「预览」能立即看到 loading 反馈。
- 预览成功后弹层展示 Markdown 渲染后的正文。
- 预览弹层提供复制 artifact ID 和下载入口。
- 点击「详情」能查看完整记录字段和调试信息。
- `flutter analyze` 通过。
