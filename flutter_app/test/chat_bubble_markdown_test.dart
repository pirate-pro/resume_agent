import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/providers/chat_provider.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/shared/widgets/career_report.dart';
import 'package:resume_agent_app/shared/widgets/chat_bubble.dart';

void main() {
  testWidgets('Agent 工作区普通聊天不展示执行进度卡片', (tester) async {
    final message = ChatMessage(
      role: 'assistant',
      content: '你好，张明。',
      sourceKind: 'direct_answer',
      progressEvents: [
        _event('run_started'),
        _event('run_finished'),
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: ChatBubble(
              message: message,
              style: ChatBubbleStyle.agentWorkspace,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('你好，张明'), findsOneWidget);
    expect(find.textContaining('多 Agent'), findsNothing);
    expect(find.text('执行阶段'), findsNothing);
    expect(find.text('执行动态'), findsNothing);
  });

  testWidgets('Agent 工作区只有真实 workflow 事件才展示执行卡片', (tester) async {
    final message = ChatMessage(
      role: 'assistant',
      content: '投递前检查已完成。',
      sourceKind: 'direct_answer',
      progressEvents: [
        _event('run_started'),
        _event('tool_call', payload: {'name': 'career_application_get'}),
        _event('tool_result', payload: {
          'tool_name': 'career_application_get',
          'success': true,
        }),
        _event('run_finished'),
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: ChatBubble(
              message: message,
              style: ChatBubbleStyle.agentWorkspace,
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.textContaining('投递前检查已完成'), findsOneWidget);
    expect(find.textContaining('多 Agent'), findsOneWidget);
    expect(find.text('执行阶段'), findsOneWidget);
  });

  testWidgets('流式兜底执行过程渲染为业务动态卡片', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: SizedBox(
              width: 760,
              child: StreamingBubble(
                buffer: '',
                thinkingLines: [
                  '[10:12:01] 开始执行任务',
                  '[10:12:02] 调用工具 session_read_artifact',
                  '[10:12:03] 工具成功 session_read_artifact',
                  '[10:12:04] 调用工具 career_job_fit_report_save',
                ],
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('执行动态'), findsOneWidget);
    expect(find.text('正在整理上下文、工具结果和最终回答'), findsOneWidget);
    expect(find.text('读取文件内容'), findsWidgets);
    expect(find.text('文件内容已读取'), findsOneWidget);
    expect(find.text('保存岗位匹配报告'), findsOneWidget);
    expect(find.text('运行中'), findsWidgets);
    expect(find.textContaining('session_read_artifact'), findsNothing);
    expect(find.textContaining('career_job_fit_report_save'), findsNothing);
  });

  testWidgets('求职报告结构化卡片渲染 Markdown 而不是展示源码', (tester) async {
    final message = ChatMessage(
      role: 'assistant',
      content: '''
# 张明 - 简历诊断报告
简历诊断完成。以下是核心结论：
整体匹配度：72/100
**诊断目标岗位方向：** AI Agent 后端工程师 / 平台研发工程师 / 后端工程师

## 诊断摘要
| 维度 | 得分 | 说明 |
| --- | --- | --- |
| 技术栈 | 85 | Python / FastAPI / PostgreSQL |
| Agent 经验 | 78 | 有 Runtime 和工具调用经验 |

## 核心优势
1. **LLM Agent 应用落地经验（强）**：从零设计 `Agent Runtime`，支持 **SSE 流式对话** 和 tool calling。
2. 技术栈：Python / FastAPI / PostgreSQL / Redis

## 风险点
| 风险项 | 等级 | 说明 |
| --- | --- | --- |
| **LLM 经验表达偏弱** | 中 | 需要补充 **RAG** 和 `MLOps` 细节 |

## 关键改进建议
1. **补充架构决策**：说明 Runtime vs LangChain 的取舍
''',
      answerFormat: 'markdown',
      renderHint: 'markdown',
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: ChatBubble(message: message),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('**'), findsNothing);
    expect(find.textContaining('# 张明'), findsNothing);
    expect(find.textContaining('```'), findsNothing);
    expect(find.textContaining('诊断目标岗位方向'), findsWidgets);
    expect(find.textContaining('先看判断'), findsOneWidget);
    expect(find.text('推荐判断'), findsOneWidget);
    expect(find.text('报告导览'), findsOneWidget);
    expect(find.textContaining('4 个重点模块'), findsOneWidget);
    expect(find.textContaining('匹配度'), findsWidgets);
    expect(find.textContaining('72'), findsWidgets);
    expect(find.textContaining('技术栈'), findsWidgets);
    expect(find.textContaining('LLM Agent 应用落地经验'), findsWidgets);
    expect(find.textContaining('补充架构决策'), findsWidgets);
  });

  testWidgets('报告预览使用轻量阅读目录，不占用完整导览卡片', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CareerReportView(
              readerMode: true,
              content: '''
岗位匹配报告

匹配结论
- **结论：** 候选人与岗位整体匹配，建议优先补齐 RAG 项目描述。

一、核心匹配点
1. 后端工程能力与岗位要求一致

二、主要风险点
1. RAG 深度实践不足（中风险）

三、关键改进建议
1. 补充检索链路和评估指标
''',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('阅读目录'), findsOneWidget);
    expect(find.textContaining('个章节'), findsOneWidget);
    expect(find.text('报告导览'), findsNothing);
    expect(find.textContaining('模块 01'), findsOneWidget);
    expect(find.textContaining('后端工程能力'), findsWidgets);
    expect(find.textContaining('补充检索链路'), findsWidgets);
  });

  testWidgets('中文序号标题的真实诊断报告进入结构化视图', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CareerReportView(
              content: '''
张明_简历诊断报告
诊断目标岗位方向：后端工程师 / AI Agent 后端工程师 / 平台研发工程师

一、核心优势
1. LLM Agent 应用落地经验（强）
- 从零设计并实现 Agent Runtime，支持流式对话、工具调用、文件上传与会话事件审计。
- SSE 首字延迟从 4.2s 优化至 1.1s，文件解析失败率从 8% 降至 1.5%。

二、风险点
1. RAG 全链路经验描述缺失（高风险）
- 简历中技能列表有 RAG，但没有完整检索链路、chunk 策略和评估体系。

三、关键改进建议
1. 补充 Agent Runtime 架构决策说明
2. 增加 RAG 检索、评估和生产稳定性指标
''',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('先看判断'), findsOneWidget);
    expect(find.text('推荐判断'), findsOneWidget);
    expect(find.textContaining('模块 01'), findsOneWidget);
    expect(find.textContaining('LLM Agent 应用落地经验'), findsWidgets);
    expect(find.textContaining('RAG 全链路经验描述缺失'), findsWidgets);
    expect(find.textContaining('补充 Agent Runtime 架构决策说明'), findsWidgets);
  });

  testWidgets('报告前置资产表不进入正文，评分表转为结构化模块', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CareerReportView(
              content: '''
多 Agent 协作已完成。以下是完整汇总。
| 类型 | ID | 说明 |
| --- | --- | --- |
| ResumeProfile | resume_profile_zhangming_003 | 复用已有，本次未重复创建 |
| 简历诊断报告 artifact | artifact_bca3abb64ae8 | 张明-简历诊断报告 |
| JDAnalysis | jd_artifact_8df79bc7a8d0 | 岗位分析记录 |
| JobFitReport | fit_zhangming_staragent_001 | 岗位匹配报告记录 |

整体匹配度：72/100（谨慎推荐）
| 维度 | 得分 |
| --- | --- |
| 技术栈匹配 | 85 |
| RAG 经验 | 42 |

一、核心匹配点
1. 硬性技术栈全覆盖
- Python / FastAPI / PostgreSQL / Redis，超过 JD 的 3 年门槛。

二、主要风险点
1. RAG 全链路经验缺失（高风险）
- JD 第二项核心职责要求文档解析到向量化召回再到评估的完整链路。
''',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('完整汇总'), findsNothing);
    expect(find.textContaining('ResumeProfile'), findsNothing);
    expect(find.textContaining('resume_profile_zhangming_003'), findsNothing);
    expect(find.textContaining('artifact_bca3abb64ae8'), findsNothing);
    expect(find.textContaining('匹配评分'), findsWidgets);
    expect(find.textContaining('技术栈匹配'), findsWidgets);
    expect(find.textContaining('RAG 经验'), findsWidgets);
    expect(find.textContaining('硬性技术栈全覆盖'), findsWidgets);
    expect(find.textContaining('RAG 全链路经验缺失'), findsWidgets);
  });

  testWidgets('多 Agent 流程说明不挤入报告顶部，匹配结论成为结构化模块', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CareerReportView(
              content: '''
已按你要求启动多 Agent 协作，并完成可复用求职产品记录和可预览匹配报告的落地。
已完成的产品记录
匹配结论
综合匹配度：77/100（谨慎推荐）
- **结论：** 候选人核心后端能力和 Agent 平台经验与目标岗位高度匹配，主要短板在 RAG 深度实践和部分加分框架经验。

一、核心匹配点
1. Python + FastAPI 全栈能力与岗位技术栈完全吻合

二、主要风险点
1. RAG 深度实践不足（中风险）
''',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('已按你要求启动'), findsNothing);
    expect(find.textContaining('已完成的产品记录'), findsNothing);
    expect(find.text('综合匹配度'), findsNothing);
    expect(find.textContaining('77/100'), findsNothing);
    expect(find.text('匹配结论'), findsWidgets);
    expect(find.textContaining('候选人核心后端能力'), findsWidgets);
    expect(find.textContaining('模块 01'), findsOneWidget);
    expect(find.textContaining('Python + FastAPI'), findsWidgets);
    expect(find.textContaining('RAG 深度实践不足'), findsWidgets);
  });

  testWidgets('风险表里的数字不被误判成评分模块', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CareerReportView(
              content: '''
岗位匹配报告

匹配结论
- **结论：** 候选人与岗位整体匹配，但 RAG 实践需要补强。

一、核心匹配点
1. 后端工程能力与岗位要求一致

二、主要风险点
| 风险项 | 等级 | 说明 |
| --- | --- | --- |
| RAG 实践不足 | 中 | JD 提到 3 年以上检索增强经验，候选人描述偏少 |

三、关键改进建议
1. 补充检索链路和评估指标
''',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('模块 03 · 投递前风险'), findsOneWidget);
    expect(find.textContaining('模块 03 · 量化判断'), findsNothing);
    expect(find.textContaining('RAG 实践不足'), findsWidgets);
    expect(find.textContaining('3 年以上检索增强经验'), findsWidgets);
  });

  testWidgets('匹配报告中的概况表和证据表保持表格渲染并隐藏技术 ID', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: CareerReportView(
              content: '''
张明-匹配报告-星河智能AI Agent后端工程师
目标岗位：星河智能 · AI Agent 后端工程师
JD 分析 ID：jd_b8e6607b59a6
推荐等级：谨慎推荐（cautious）

一、候选人概况
| 维度 | 信息 |
| --- | --- |
| 学历 | 上海理工大学 · 软件工程本科（2016-2020） |
| 工作年限 | 4 年后端研发经验 |
| 核心技术栈 | Python / FastAPI / PostgreSQL / Redis / Elasticsearch / Docker |

二、岗位核心要求 vs 候选人能力
| 硬性要求 | 候选人状态 | 匹配度 |
| --- | --- | --- |
| 3年以上 Python 后端经验 | ✅ 4年经验，超出要求 | ✅ 完全匹配 |
| 消息队列 / 异步任务 / 事件驱动架构 | ⚠️ 有 Celery 经验，但未明确 Kafka/RabbitMQ | ⚠️ 部分匹配 |

三、核心匹配点
1. **技术栈匹配度：高（85/100）**
- 候选人 Python + FastAPI + PostgreSQL + Redis 全链路能力与 JD 硬性要求高度吻合。
- 关键证据：
| 匹配项 | 证据来源 | 匹配度 |
| --- | --- | --- |
| Agent Runtime 设计 | 上海云启科技 · Agent Runtime 项目 | ✅ 直接匹配 |
| 多 Agent 协作 | multi-agent 委派机制 | ✅ 直接匹配 |

四、关键改进建议
6. 补充技术影响力
- 即使小型项目也能体现技术深度
- 可考虑添加技术博客或 GitHub 项目
---
关键匹配证据
| 匹配项 | 证据来源 | 匹配度 |
| --- | --- | --- |
| 文件解析 | 文件解析优化 | ✅ 间接匹配 |
| RAG 全链路 | 无直接项目证据 | ❌ 缺失 |
报告生成时间：2026-05-10
数据来源：resume_profile_zhangming_003 + jd_b8e6607b59a6 + career_profile_default
''',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('| 匹配项 |'), findsNothing);
    expect(find.textContaining('| --- |'), findsNothing);
    expect(find.textContaining('jd_b8e6607b59a6'), findsNothing);
    expect(find.textContaining('resume_profile_zhangming_003'), findsNothing);
    expect(find.text('候选人概况'), findsWidgets);
    expect(find.text('岗位要求对照'), findsWidgets);
    expect(find.text('结构化明细'), findsNothing);
    expect(find.textContaining('上海理工大学'), findsWidgets);
    expect(find.text('关键匹配证据'), findsWidgets);
    expect(find.textContaining('Agent Runtime 设计'), findsWidgets);
    expect(find.textContaining('RAG 全链路'), findsWidgets);
    expect(find.textContaining('补充技术影响力'), findsWidgets);
  });

  testWidgets('求职资产结果区默认隐藏长 ID', (tester) async {
    final message = ChatMessage(
      role: 'assistant',
      content: '''
已创建的求职资产：
- 简历画像：resume_profile_zhangming_003
- 匹配报告：fit_zhangming_staragent_001
''',
    );

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ChatBubble(message: message),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('已创建的求职资产'), findsOneWidget);
    expect(find.text('结果已整理为可预览、可继续处理的资产'), findsOneWidget);
    expect(find.text('2 项'), findsOneWidget);
    expect(find.text('建议下一步：生成定制简历'), findsOneWidget);
    expect(find.text('生成定制简历'), findsOneWidget);
    expect(find.text('简历画像'), findsWidgets);
    expect(find.text('匹配报告'), findsWidgets);
    expect(find.textContaining('resume_profile_zhangming_003'), findsNothing);
    expect(find.textContaining('fit_zhangming_staragent_001'), findsNothing);
    expect(find.text('复制'), findsWidgets);
  });

  testWidgets('学习建议消息支持确认加入学习任务', (tester) async {
    final api = _FakeChatBubbleApiService();
    final message = ChatMessage(
      role: 'assistant',
      content: '''
## 面试准备建议

1. 优先补齐 RAG 评估方案，整理召回率、准确率和 chunk 策略。
2. 准备 Agent Runtime 与 LangGraph 的架构取舍说明。

建议把第一项加入学习任务，持续推进。
''',
      answerFormat: 'markdown',
      renderHint: 'markdown',
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiServiceProvider.overrideWithValue(api)],
        child: MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: ChatBubble(message: message),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('可以加入学习任务'), findsOneWidget);
    expect(find.text('加入学习任务'), findsOneWidget);

    await tester.tap(find.text('加入学习任务'));
    await tester.pumpAndSettle();
    expect(find.text('交给 Agent 创建'), findsOneWidget);

    await tester.tap(find.text('交给 Agent 创建'));
    await tester.pumpAndSettle();

    expect(api.sentMessages, hasLength(1));
    expect(api.sentMessages.single, contains('请把下面这条 Assistant 建议加入学习任务'));
    expect(api.sentMessages.single, contains('调用'));
    expect(api.sentMessages.single, contains('learning_task'));
    expect(api.sentMessages.single, contains('不要自动写 Note'));
    expect(api.sentMessages.single, contains('不要重复创建'));
  });
}

EventView _event(String type, {Map<String, dynamic> payload = const {}}) {
  return EventView(
    eventId: 'evt_$type',
    sessionId: 'sess_chat_bubble',
    agentId: 'agent_main',
    runId: 'run_chat_bubble',
    eventVersion: 1,
    type: type,
    payload: payload,
    createdAt: DateTime(2026, 5, 28, 10, 30),
  );
}

class _FakeChatBubbleApiService extends ApiService {
  final sentMessages = <String>[];

  _FakeChatBubbleApiService() : super(baseUrl: 'http://localhost');

  @override
  Future<HealthView?> fetchHealth() async {
    return HealthView(status: 'ok', midTermFlush: null);
  }

  @override
  Future<List<SkillOption>> listSkills() async => const [];

  @override
  Future<List<SessionMeta>> listSessions() async => const [];

  @override
  Stream<StreamEvent> chatStream({
    required String message,
    String? sessionId,
    List<String> skillNames = const [],
    int maxToolRounds = 8,
    List<String>? activeArtifactIds,
  }) async* {}

  @override
  Future<ChatResponse> chat({
    required String message,
    String? sessionId,
    List<String> skillNames = const [],
    int maxToolRounds = 8,
    List<String>? activeArtifactIds,
  }) async {
    sentMessages.add(message);
    return ChatResponse(
      sessionId: sessionId ?? 'sess_chat_bubble',
      answer: '已加入学习任务。',
      toolCalls: const [],
      memoryHits: const [],
    );
  }

  @override
  Future<SessionArtifactsResponse> listSessionArtifacts(
    String sessionId,
  ) async {
    return SessionArtifactsResponse(
      sessionId: sessionId,
      activeArtifactIds: const [],
      artifacts: const [],
    );
  }

  @override
  Future<List<ResumeProfileView>> listCareerResumeProfiles({
    bool includeArchived = false,
  }) async =>
      const [];

  @override
  Future<List<CareerProfileView>> listCareerProfiles({
    bool includeArchived = false,
  }) async =>
      const [];

  @override
  Future<List<JDAnalysisView>> listCareerJobs({
    bool includeArchived = false,
  }) async =>
      const [];

  @override
  Future<List<JobFitReportView>> listCareerJobFitReports({
    bool includeArchived = false,
  }) async =>
      const [];

  @override
  Future<List<ResumeVersionView>> listCareerResumeVersions({
    bool includeArchived = false,
  }) async =>
      const [];

  @override
  Future<List<CareerApplicationView>> listCareerApplications({
    bool includeArchived = false,
  }) async =>
      const [];
}
