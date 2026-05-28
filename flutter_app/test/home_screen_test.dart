import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/providers/chat_provider.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/home/home_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('从工作台动作回到聊天后刷新求职工作台数据', (tester) async {
    tester.view.physicalSize = const Size(1180, 1180);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});

    final api = _FakeHomeApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiServiceProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(home: HomeScreen()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('求职项目').first);
    await tester.pumpAndSettle();

    expect(find.text('求职项目'), findsWidgets);
    expect(find.text('岗位工作台'), findsWidgets);
    expect(api.workbenchListCalls, greaterThanOrEqualTo(1));
    final callsAfterOpen = api.workbenchListCalls;

    await tester.tap(find.text('生成定制简历').first);
    await tester.pumpAndSettle();

    expect(api.sentMessages.last, contains('application_home_staragent'));
    expect(api.workbenchListCalls, greaterThan(callsAfterOpen));

    await tester.tap(find.text('求职项目').first);
    await tester.pumpAndSettle();

    expect(find.text('已完成：生成定制简历'), findsOneWidget);
    expect(find.textContaining('已刷新项目状态'), findsOneWidget);
  });

  testWidgets('工作台动作失败时保留失败提示', (tester) async {
    tester.view.physicalSize = const Size(1180, 1180);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});

    final api = _FakeHomeApiService(failChat: true);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiServiceProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(home: HomeScreen()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.text('求职项目').first);
    await tester.pumpAndSettle();

    await tester.tap(find.text('生成定制简历').first);
    await tester.pumpAndSettle();

    await tester.tap(find.text('求职项目').first);
    await tester.pumpAndSettle();

    expect(find.text('执行失败：生成定制简历'), findsOneWidget);
    expect(find.textContaining('模拟聊天失败'), findsOneWidget);
  });

  testWidgets('产品一级导航不再嵌套旧求职工作台', (tester) async {
    tester.view.physicalSize = const Size(1440, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});

    final api = _FakeHomeApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiServiceProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(home: HomeScreen()),
      ),
    );
    await tester.pumpAndSettle();

    Future<void> openProductPage(String label) async {
      await tester.tap(find.text(label).first);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('求职工作台'), findsNothing);
      expect(find.text('工作台模式'), findsNothing);
      expect(find.text('JD 与匹配'), findsNothing);
    }

    await openProductPage('求职项目');
    expect(find.text('岗位工作台'), findsWidgets);

    await openProductPage('简历资料');
    expect(find.text('版本管理'), findsWidgets);

    await openProductPage('JD 匹配');
    expect(find.text('智能分析'), findsWidgets);

    await openProductPage('学习计划');
    expect(find.text('补短板'), findsWidgets);

    await openProductPage('笔记');
    expect(find.text('知识沉淀'), findsWidgets);
  });

  testWidgets('产品壳顶部入口可以打开会话历史', (tester) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    SharedPreferences.setMockInitialValues({});

    final api = _FakeHomeApiService();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          apiServiceProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(home: HomeScreen()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('会话历史'));
    await tester.pumpAndSettle();

    expect(find.text('会话与求职资产'), findsOneWidget);
    expect(find.text('历史会话样例'), findsOneWidget);
  });
}

class _FakeHomeApiService extends ApiService {
  final now = DateTime(2026, 5, 14, 9, 30);
  final sentMessages = <String>[];
  int workbenchListCalls = 0;
  final bool failChat;

  _FakeHomeApiService({this.failChat = false})
      : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_home',
        sourceArtifactId: 'artifact_home_jd',
        evidenceRefs: const ['artifact_home_jd'],
        createdAt: now,
        updatedAt: now,
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_home_staragent',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        location: '上海',
        jobUrl: '',
        stage: 'ready_to_apply',
        priority: 'high',
        resumeProfileId: 'resume_profile_home',
        careerProfileId: 'career_profile_default',
        jdAnalysisId: 'jd_home_staragent',
        jobFitReportId: 'fit_home_staragent',
        resumeVersionIds: const [],
        summary: '可进入定制简历阶段。',
        nextActions: const ['生成定制简历'],
        risks: const [],
        notes: '',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 82,
        level: 'ready',
        recommendation: 'recommended',
        summary: '建议生成定制简历。',
        strengths: const ['后端经验匹配'],
        risks: const [],
        missingMaterials: const [],
        nextActions: const ['生成定制简历'],
      );

  @override
  Future<HealthView?> fetchHealth() async {
    return HealthView(status: 'ok', midTermFlush: null);
  }

  @override
  Future<List<SkillOption>> listSkills() async => const [];

  @override
  Future<List<SessionMeta>> listSessions() async => [
        SessionMeta(
          id: 'sess_history_sample',
          title: '历史会话样例',
          createdAt: now.subtract(const Duration(days: 1)),
          updatedAt: now,
          isPinned: false,
          pinnedAt: null,
          messageCount: 4,
        ),
      ];

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
    if (failChat) {
      throw ApiException(500, '{"detail":"模拟聊天失败"}');
    }
    return ChatResponse(
      sessionId: sessionId ?? 'sess_home',
      answer: '已生成定制简历。',
      toolCalls: const [],
      memoryHits: const [],
    );
  }

  @override
  Future<SessionArtifactsResponse> listSessionArtifacts(
      String sessionId) async {
    return SessionArtifactsResponse(
      sessionId: sessionId,
      activeArtifactIds: const [],
      artifacts: const [],
    );
  }

  @override
  Future<CareerWorkbenchListView> getCareerWorkbench({
    bool includeArchived = false,
  }) async {
    workbenchListCalls += 1;
    return CareerWorkbenchListView(
      applications: [
        CareerApplicationSummaryView(
          application: _application,
          readiness: _readiness,
          linkedAssetCount: 3,
          noteCount: 0,
          learningTaskCount: 0,
          updatedAt: now,
        ),
      ],
      activeApplicationId: _application.applicationId,
      counts: CareerWorkbenchCountsView(
        applications: 1,
        activeApplications: 1,
        notes: 0,
        learningTasks: 0,
        resumeVersions: 0,
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
      jdAnalysis: null,
      jobFitReport: null,
      resumeVersions: const [],
      readiness: _readiness,
      linkedAssets: const [],
      notes: const [],
      learning: CareerLearningSummaryView(
        plans: const [],
        tasks: const [],
        weaknesses: const [],
        reviews: const [],
        openTaskCount: 0,
        doneTaskCount: 0,
        highWeaknessCount: 0,
      ),
      timeline: const [],
      suggestedActions: [
        CareerSuggestedActionView(
          actionType: 'custom_resume',
          label: '生成定制简历',
          promptIntent: '基于当前岗位生成定制简历版本',
          priority: 'high',
          enabled: true,
          reason: '已有匹配报告',
        ),
      ],
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
  Future<List<NoteView>> listNotes({
    bool includeArchived = false,
    String? collectionId,
    String? relatedApplicationId,
  }) async =>
      const [];

  @override
  Future<List<CareerApplicationView>> listCareerApplications({
    bool includeArchived = false,
  }) async =>
      [_application];
}
