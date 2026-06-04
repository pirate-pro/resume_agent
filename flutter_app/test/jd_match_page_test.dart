import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_provider.dart';
import 'package:resume_agent_app/features/jd_match/jd_match_page.dart';

void main() {
  testWidgets('JD 匹配页展示匹配分析、差距证据并发送重新分析动作', (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeJDMatchApi();
    String? sentPrompt;
    CareerWorkbenchActionRequest? sentAction;

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          careerWorkbenchProvider.overrideWith(
            (ref) => CareerWorkbenchProvider(api),
          ),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: JDMatchPage(
              onOpenProjects: () {},
              onOpenResumes: () {},
              onOpenLearning: () {},
              onOpenNotes: () {},
              onSendPrompt: (prompt, {action}) async {
                sentPrompt = prompt;
                sentAction = action;
              },
            ),
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('重新分析'), findsOneWidget);
    expect(find.text('星河智能'), findsWidgets);
    expect(find.text('匹配总览'), findsOneWidget);
    expect(find.text('技术栈匹配'), findsOneWidget);
    expect(find.text('当前判断'), findsWidgets);
    expect(find.text('推荐下一步'), findsOneWidget);
    expect(find.text('JD 与匹配记录'), findsOneWidget);

    await tester.tap(find.text('重新分析').first);
    await tester.pump();
    expect(sentPrompt, contains('application_jd_match_staragent'));
    expect(sentAction?.origin, 'jd_match');
    expect(sentAction?.actionType, 'jd_match_analysis');
    ScaffoldMessenger.of(tester.element(find.byType(JDMatchPage)))
        .clearSnackBars();
    await tester.pumpAndSettle();

    await tester.tap(find.text('差距分析'));
    await tester.pumpAndSettle();
    expect(find.text('差距分析'), findsWidgets);
    expect(find.text('关键差距与优先级'), findsOneWidget);
    expect(find.text('优化简历表达'), findsWidgets);
    expect(find.text('创建学习任务'), findsWidgets);

    await tester.tap(find.text('证据依据'));
    await tester.pumpAndSettle();
    expect(find.text('已命中证据'), findsOneWidget);
    expect(find.text('未命中要求'), findsOneWidget);
    expect(find.text('Python'), findsWidgets);
    await tester.tap(find.text('补充证据').first);
    await tester.pumpAndSettle();
    expect(find.text('补充项目证据'), findsWidgets);
    await tester.enterText(
      find.byKey(const Key('jd_evidence_description_field')),
      '在智能客服 Agent 平台中使用 LangGraph 构建多 Agent 状态流，支持任务分派、工具调用和失败重试。',
    );
    await tester.enterText(
      find.byKey(const Key('jd_evidence_skills_field')),
      'LangGraph StateGraph ToolNode',
    );
    await tester.enterText(
      find.byKey(const Key('jd_evidence_outcomes_field')),
      '日均处理会话 18w+，流程失败率低于 0.6%。',
    );
    final saveEvidenceButton = find.byKey(const Key('jd_evidence_save_button'));
    await tester.scrollUntilVisible(
      saveEvidenceButton,
      120,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    await tester.tap(saveEvidenceButton);
    await tester.pumpAndSettle();
    expect(api.createdNotes, hasLength(1));
    final evidenceNote = api.createdNotes.single;
    expect(evidenceNote.origin, 'jd_match');
    expect(evidenceNote.relatedApplicationId, 'application_jd_match_staragent');
    expect(evidenceNote.tags, contains('项目证据'));
    expect(evidenceNote.tags, contains('JD匹配'));
    expect(evidenceNote.bodyMarkdown, contains('LangGraph'));

    await tester.drag(find.byType(Scrollable).first, const Offset(0, 700));
    await tester.pumpAndSettle();
    await tester.tap(find.text('面试准备'));
    await tester.pumpAndSettle();
    expect(find.text('生成面试题'), findsWidgets);
    expect(find.text('高频问题数'), findsOneWidget);

    await tester.tap(find.text('展开要点').first);
    await tester.pumpAndSettle();
    expect(find.text('回答组织'), findsOneWidget);
    await tester.tap(find.text('保存为笔记').last);
    await tester.pumpAndSettle();
    expect(api.createdNotes, hasLength(2));
    expect(api.createdNotes.last.title, contains('面试题'));

    await tester.tap(find.text('模拟问答').first);
    await tester.pump();
    expect(sentAction?.actionType, 'interview_prep');
  });
}

class _FakeJDMatchApi extends ApiService {
  final now = DateTime(2026, 5, 16, 10, 49);
  final List<NoteView> createdNotes = [];

  _FakeJDMatchApi() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_jd_match',
        sourceArtifactId: 'artifact_jd_match_jd',
        evidenceRefs: const ['artifact_jd_match_jd'],
        createdAt: now.subtract(const Duration(days: 2)),
        updatedAt: now,
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_jd_match_staragent',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        location: '深圳 / 南山',
        jobUrl: 'https://example.com/jobs/agent',
        stage: 'screening',
        priority: 'high',
        resumeProfileId: 'resume_profile_jd_match',
        careerProfileId: 'career_profile_default',
        jdAnalysisId: 'jd_match_staragent',
        jobFitReportId: 'fit_jd_match_staragent',
        resumeVersionIds: const ['resume_version_jd_match'],
        summary: '整体匹配良好，但需要补充分布式系统经验。',
        nextActions: const ['优化简历亮点', '准备面试题'],
        risks: const ['大模型工程化证据仍需补强'],
        notes: '',
      );

  JDAnalysisView get _jd => JDAnalysisView(
        meta: _meta,
        jdAnalysisId: 'jd_match_staragent',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        seniority: '3-5 年',
        requiredSkills: const ['Python', 'FastAPI', 'PostgreSQL'],
        preferredSkills: const ['RAG', '多 Agent 系统'],
        responsibilities: const ['负责 AI Agent 平台后端架构设计与开发'],
        keywords: const ['Agent', 'LLM', '工具调用', '任务编排'],
        riskSignals: const ['强调工程化落地和稳定性'],
        interviewFocus: const ['系统设计', 'RAG 优化', 'Agent 通信'],
      );

  JobFitReportView get _report => JobFitReportView(
        meta: _meta,
        jobFitReportId: 'fit_jd_match_staragent',
        jdAnalysisId: 'jd_match_staragent',
        resumeProfileId: 'resume_profile_jd_match',
        careerProfileId: 'career_profile_default',
        overallScore: 78,
        scoreBreakdown: const {
          '技术栈匹配': 85,
          '项目经历匹配': 72,
          'Agent/LLM 经验': 75,
          '工程化能力': 80,
          '面试准备度': 68,
        },
        matchedEvidence: const [
          {'summary': 'Agent 平台后端开发经验匹配'},
          {'summary': 'RAG 知识库项目可作为证据'},
        ],
        gaps: const [
          {'gap': '生产级多 Agent 协作经验描述不够具体'},
          {'gap': '向量数据库调优与检索优化案例偏少'},
        ],
        resumeOptimizationDirection: const [
          {'suggestion': '补充多 Agent 协作项目中的任务编排与状态追踪实践'},
          {'suggestion': '强化 RAG 检索质量评估和优化指标表达'},
        ],
        interviewPreparationFocus: const [
          {'title': '设计一个 Agent 协作系统并解释状态管理方式'},
          {'title': '说明 RAG 检索效果不理想时的排查和优化路径'},
        ],
        recommendation: 'cautious',
        reportArtifactId: 'artifact_fit_report',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 78,
        level: 'good',
        recommendation: 'cautious',
        summary: '整体匹配 78%，具备核心技能基础，建议补强多 Agent 工程化证据。',
        strengths: const ['AI Agent 项目经验匹配', 'Python / FastAPI 技术栈匹配'],
        risks: const ['分布式系统和稳定性实践表达不足'],
        missingMaterials: const ['缺少高并发指标'],
        nextActions: const ['优化简历亮点', '准备系统设计面试题'],
      );

  @override
  Future<CareerWorkbenchListView> getCareerWorkbench({
    bool includeArchived = false,
  }) async {
    return CareerWorkbenchListView(
      applications: [
        CareerApplicationSummaryView(
          application: _application,
          readiness: _readiness,
          linkedAssetCount: 5,
          noteCount: 2,
          learningTaskCount: 1,
          updatedAt: now,
        ),
      ],
      activeApplicationId: _application.applicationId,
      counts: CareerWorkbenchCountsView(
        applications: 1,
        activeApplications: 1,
        notes: 2,
        learningTasks: 1,
        resumeVersions: 1,
      ),
      updatedAt: now,
    );
  }

  @override
  Future<CareerApplicationWorkbenchView> getCareerApplicationWorkbench({
    required String applicationId,
    bool includeArchived = false,
  }) async {
    return CareerApplicationWorkbenchView(
      application: _application,
      resumeProfile: null,
      careerProfile: null,
      jdAnalysis: _jd,
      jobFitReport: _report,
      resumeVersions: [
        ResumeVersionView(
          meta: _meta,
          resumeVersionId: 'resume_version_jd_match',
          baseResumeProfileId: 'resume_profile_jd_match',
          targetJdAnalysisId: 'jd_match_staragent',
          title: 'AI Agent 后端工程师定制简历',
          format: 'markdown',
          artifactId: 'artifact_resume_version',
          changeSummary: const ['补充 Agent 工程化经验'],
          keywordStrategy: const ['Agent', 'RAG'],
          riskNotes: const [],
        ),
      ],
      readiness: _readiness,
      linkedAssets: const [],
      notes: const [],
      learning: CareerLearningSummaryView(
        plans: const [],
        tasks: const [],
        weaknesses: const [],
        reviews: const [],
        openTaskCount: 1,
        doneTaskCount: 0,
        highWeaknessCount: 1,
      ),
      timeline: const [],
      suggestedActions: const [],
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
      [_jd];

  @override
  Future<List<JobFitReportView>> listCareerJobFitReports({
    bool includeArchived = false,
  }) async =>
      [_report];

  @override
  Future<List<ResumeVersionView>> listCareerResumeVersions({
    bool includeArchived = false,
  }) async =>
      [
        ResumeVersionView(
          meta: _meta,
          resumeVersionId: 'resume_version_jd_match',
          baseResumeProfileId: 'resume_profile_jd_match',
          targetJdAnalysisId: 'jd_match_staragent',
          title: 'AI Agent 后端工程师定制简历',
          format: 'markdown',
          artifactId: 'artifact_resume_version',
          changeSummary: const ['补充 Agent 工程化经验'],
          keywordStrategy: const ['Agent', 'RAG'],
          riskNotes: const [],
        ),
      ];

  @override
  Future<List<NoteView>> listNotes({
    bool includeArchived = false,
    String? collectionId,
    String? relatedApplicationId,
  }) async =>
      createdNotes;

  @override
  Future<NoteView> createNote({
    String? noteId,
    required String sourceSessionId,
    String? sourceArtifactId,
    List<String> evidenceRefs = const [],
    required String title,
    required String bodyMarkdown,
    String bodyFormat = "markdown",
    String noteType = "note",
    String origin = "user",
    String? collectionId,
    List<String> tags = const [],
    List<Map<String, dynamic>> sourceRefs = const [],
    String? relatedApplicationId,
    String summary = "",
  }) async {
    final note = NoteView(
      noteId: noteId ?? 'note_${createdNotes.length + 1}',
      status: 'active',
      sourceSessionId: sourceSessionId,
      sourceArtifactId: sourceArtifactId,
      evidenceRefs: evidenceRefs,
      createdAt: now,
      updatedAt: now,
      title: title,
      bodyMarkdown: bodyMarkdown,
      bodyFormat: bodyFormat,
      noteType: noteType,
      origin: origin,
      collectionId: collectionId,
      tags: tags,
      sourceRefs: const [],
      relatedApplicationId: relatedApplicationId,
      summary: summary,
    );
    createdNotes.add(note);
    return note;
  }
}
