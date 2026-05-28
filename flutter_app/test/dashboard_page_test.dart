import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_provider.dart';
import 'package:resume_agent_app/features/dashboard/dashboard_page.dart';

void main() {
  testWidgets('总览页展示状态、指标、最近岗位和推荐动作', (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeDashboardApi();
    String? openedProjectId;
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
            body: DashboardPage(
              onOpenProject: (id) => openedProjectId = id,
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

    expect(find.text('当前求职状态'), findsOneWidget);
    expect(find.text('继续推进岗位'), findsOneWidget);
    expect(find.text('已投递岗位'), findsOneWidget);
    expect(find.text('匹配度均值'), findsOneWidget);
    expect(find.text('最近推进中的岗位'), findsOneWidget);
    expect(find.text('星河智能'), findsWidgets);
    expect(find.text('生成定制简历'), findsWidgets);
    expect(find.text('当前判断'), findsOneWidget);
    expect(find.text('关联资产'), findsOneWidget);

    await tester.tap(find.text('继续推进岗位'));
    expect(openedProjectId, 'application_dashboard_staragent');

    await tester.tap(find.text('去执行').first);
    await tester.pump();
    expect(sentPrompt, contains('application_dashboard_staragent'));
    expect(sentAction?.origin, 'dashboard');
  });
}

class _FakeDashboardApi extends ApiService {
  final now = DateTime(2026, 5, 16, 10, 49);

  _FakeDashboardApi() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_dashboard',
        sourceArtifactId: 'artifact_dashboard_jd',
        evidenceRefs: const ['artifact_dashboard_jd'],
        createdAt: now,
        updatedAt: now,
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_dashboard_staragent',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        location: '上海 / 杭州',
        jobUrl: '',
        stage: 'interviewing',
        priority: 'high',
        resumeProfileId: 'resume_profile_dashboard',
        careerProfileId: 'career_profile_default',
        jdAnalysisId: 'jd_dashboard_staragent',
        jobFitReportId: 'fit_dashboard_staragent',
        resumeVersionIds: const ['resume_version_dashboard'],
        summary: '整体匹配良好，建议准备面试。',
        nextActions: const ['生成定制简历', '准备面试题'],
        risks: const ['分布式系统经验需要补充证据'],
        notes: '',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 78,
        level: 'good',
        recommendation: 'cautious',
        summary: '整体进展良好，建议优先准备高匹配岗位的面试。',
        strengths: const ['Python / FastAPI / Agent 开发经验匹配'],
        risks: const ['分布式系统与性能优化表达不足'],
        missingMaterials: const [],
        nextActions: const ['生成定制简历', '准备面试题'],
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
          linkedAssetCount: 4,
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
      jdAnalysis: null,
      jobFitReport: null,
      resumeVersions: const [],
      readiness: _readiness,
      linkedAssets: [
        CareerLinkedAssetView(
          type: 'resume_version',
          id: 'resume_version_dashboard',
          title: 'AI Agent 后端工程师定制简历',
          subtitle: '当前简历版本',
          status: 'active',
          updatedAt: now,
          previewArtifactId: 'artifact_resume_version',
          sourceSessionId: 'sess_dashboard',
          isCurrent: true,
          actions: const ['preview'],
        ),
      ],
      notes: const [],
      learning: CareerLearningSummaryView(
        plans: const [],
        tasks: const [],
        weaknesses: const [],
        reviews: const [],
        openTaskCount: 1,
        doneTaskCount: 2,
        highWeaknessCount: 1,
      ),
      timeline: const [],
      suggestedActions: [
        CareerSuggestedActionView(
          actionType: 'custom_resume',
          label: '生成定制简历',
          promptIntent: '基于当前岗位生成定制简历版本',
          priority: 'high',
          enabled: true,
          reason: '面试前优先提升简历匹配表达',
        ),
      ],
    );
  }
}
