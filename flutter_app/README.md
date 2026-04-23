# Agent Runtime Flutter 前端应用

这是一个基于Flutter构建的跨平台聊天应用，支持iOS、Android和Web平台。应用采用现代化的架构设计，具有以下特点：

- ✅ 响应式设计，适配不同屏幕尺寸
- ✅ 暗色主题，符合GPT简约风格
- ✅ 流式消息处理，AI打字机效果
- ✅ 技能选择功能（输入框/选择，支持多选）
- ✅ 文件上传和管理
- ✅ 调试面板
- ✅ 错误处理和状态管理

## 🚀 快速开始

### 1. 环境准备

确保你的系统已经安装了Flutter SDK：

```bash
# 检查Flutter是否安装
flutter --version

# 如果未安装，可以从官网下载
https://flutter.dev/docs/get-started/install
```

### 2. 克隆项目

```bash
git clone <your-repo-url>
cd flutter_app
```

### 3. 获取依赖

```bash
flutter pub get
```

### 4. 运行应用

#### 运行Web版本
```bash
flutter run -d chrome
```

#### 运行Android版本
```bash
flutter run -d android
```

#### 运行iOS版本
```bash
flutter run -d ios
```

#### 启动开发服务器
```bash
flutter run -d web-server --web-hostname localhost --web-port 8080
```

### 5. 构建发布版本

#### 构建Web版本
```bash
flutter build web --release
```

#### 构建Android版本
```bash
flutter build apk --release
```

#### 构建iOS版本
```bash
flutter build ios --release
```

## 📱 功能使用指南

### 聊天功能
- 在输入框中输入消息，按回车发送
- 支持Shift+Enter换行
- AI会以流式方式回复，显示打字机效果

### 技能选择
- 在输入框中输入 `/` 触发技能选择菜单
- 选择需要的技能（可多选）
- 点击"完成"确认选择

### 快速测试
- 点击"快速测试"按钮发送预设消息
- 包括：记忆偏好、写文件、读文件

### 文件管理
- 查看会话文件列表
- 勾选文件激活状态
- 查看上传状态

### 调试面板
- 右侧面板显示工具调用、Memory命中、Events和Memories
- 实时查看系统状态

### 错误处理
- 错误信息会显示在聊天区域顶部
- 点击刷新按钮重试

## 🛠️ 技术架构

### 核心组件
- **设计令牌系统**：将Tailwind CSS映射到Flutter主题
- **微内核架构**：共享业务逻辑 + 平台适配
- **状态管理**：Riverpod进行状态管理
- **API客户端**：Dio处理网络请求

### 目录结构
```
lib/
├── core/           # 核心功能
│   ├── theme/      # 设计令牌和主题
│   ├── state/      # 状态管理
│   └── constants/  # 常量定义
├── features/       # 功能模块
│   ├── chat/       # 聊天功能
│   ├── sessions/   # 会话管理
│   ├── files/      # 文件功能
│   └── debug/      # 调试功能
├── shared/         # 共享代码
│   ├── models/     # 数据模型
│   ├── utils/      # 工具函数
│   └── api/        # API客户端
└── main.dart       # 主应用入口
```

## 🔧 开发指南

### 添加新功能
1. 在对应的feature目录下创建新组件
2. 更新状态管理
3. 添加到UI中

### 修改主题
1. 编辑 `lib/core/theme/app_theme.dart`
2. 更新颜色、间距、圆角等设计令牌
3. 主题会自动应用到整个应用

### 添加API
1. 在 `lib/shared/api/chat_api.dart` 中添加新方法
2. 更新状态管理以处理新数据
3. 在UI中显示新数据

## 📝 注意事项

- 确保后端API运行正常
- 检查网络连接
- 调试时查看控制台输出
- 使用Flutter Inspector进行UI调试

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个应用！

## 📄 许可证

本项目采用MIT许可证。