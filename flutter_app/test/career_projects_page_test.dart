import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_provider.dart';
import 'package:resume_agent_app/features/projects/career_projects_page.dart';

void main() {
  testWidgets('求职项目页展示岗位工作台、执行进度和推荐动作', (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeProjectsApi();
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
            body: CareerProjectsPage(
              onOpenProject: (_) {},
              onOpenResumes: () {},
              onOpenJDMatch: () {},
              onOpenLearning: () {},
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

    expect(find.text('求职项目'), findsOneWidget);
    expect(find.text('岗位工作台'), findsOneWidget);
    expect(find.text('星河智能'), findsWidgets);
    expect(find.text('岗位总览'), findsOneWidget);
    expect(find.text('面试流程时间线'), findsOneWidget);
    expect(find.text('多 Agent 执行进度'), findsOneWidget);
    expect(find.text('当前判断'), findsOneWidget);
    expect(find.text('求职进展'), findsOneWidget);
    expect(find.text('关联资产'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.text('风险与差距'),
      320,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('风险与差距'), findsOneWidget);
    expect(find.text('推荐动作'), findsOneWidget);

    await tester.tap(find.text('去执行').first);
    await tester.pump();

    expect(sentPrompt, contains('application_projects_staragent'));
    expect(sentAction?.origin, 'projects');
    expect(sentAction?.actionType, 'custom_resume');
  });
}

class _FakeProjectsApi extends ApiService {
  final now = DateTime(2026, 5, 16, 10, 49);

  _FakeProjectsApi() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_projects',
        sourceArtifactId: 'artifact_projects_jd',
        evidenceRefs: const ['artifact_projects_jd'],
        createdAt: now.subtract(const Duration(days: 1)),
        updatedAt: now,
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_projects_staragent',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        location: '深圳 / 南山',
        jobUrl: 'https://example.com/jobs/1',
        stage: 'screening',
        priority: 'high',
        resumeProfileId: 'resume_profile_projects',
        careerProfileId: 'career_profile_default',
        jdAnalysisId: 'jd_projects_staragent',
        jobFitReportId: 'fit_projects_staragent',
        resumeVersionIds: const [],
        summary: '简历筛选进行中，建议优先生成定制简历。',
        nextActions: const ['生成定制简历', '准备技术面试'],
        risks: const ['分布式系统经验需要更具体的项目证据'],
        notes: '',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 78,
        level: 'good',
        recommendation: 'cautious',
        summary: '整体匹配良好，但大模型工程化和分布式经验仍需补强。',
        strengths: const ['Agent 平台后端开发经验匹配'],
        risks: const ['分布式训练经验不足'],
        missingMaterials: const ['缺少高并发项目指标'],
        nextActions: const ['生成定制简历', '准备技术面试'],
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
          noteCount: 1,
          learningTaskCount: 2,
          updatedAt: now,
        ),
      ],
      activeApplicationId: _application.applicationId,
      counts: CareerWorkbenchCountsView(
        applications: 1,
        activeApplications: 1,
        notes: 1,
        learningTasks: 2,
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
      resumeProfile: ResumeProfileView(
        meta: _meta,
        resumeProfileId: 'resume_profile_projects',
        basicInfo: const {'name': '张明'},
        education: const [],
        workExperience: const [],
        projectExperience: const [],
        skills: const ['Python', 'FastAPI', 'Agent'],
        certificates: const [],
        awards: const [],
        selfEvaluation: '',
        rawTextArtifactId: 'artifact_resume_raw',
        diagnosisArtifactId: 'artifact_resume_diagnosis',
        diagnosis: const {},
      ),
      careerProfile: null,
      jdAnalysis: JDAnalysisView(
        meta: _meta,
        jdAnalysisId: 'jd_projects_staragent',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        seniority: '3-5 年',
        requiredSkills: const ['Python', 'FastAPI', 'RAG'],
        preferredSkills: const ['多 Agent 系统'],
        responsibilities: const ['负责 Agent 平台后端研发'],
        keywords: const ['Agent', 'LLM', '工具调用'],
        riskSignals: const ['要求工程化落地经验'],
        interviewFocus: const ['系统设计', '工具调用'],
      ),
      jobFitReport: JobFitReportView(
        meta: _meta,
        jobFitReportId: 'fit_projects_staragent',
        jdAnalysisId: 'jd_projects_staragent',
        resumeProfileId: 'resume_profile_projects',
        careerProfileId: 'career_profile_default',
        overallScore: 78,
        scoreBreakdown: const {'技术栈': 85, '工程化': 80},
        matchedEvidence: const [],
        gaps: const [],
        resumeOptimizationDirection: const [],
        interviewPreparationFocus: const [],
        recommendation: 'cautious',
        reportArtifactId: 'artifact_fit_report',
      ),
      resumeVersions: const [],
      readiness: _readiness,
      linkedAssets: [
        CareerLinkedAssetView(
          type: 'job_fit_report',
          id: 'fit_projects_staragent',
          title: '星河智能匹配报告',
          subtitle: '匹配度 78%',
          status: 'active',
          updatedAt: now,
          previewArtifactId: 'artifact_fit_report',
          sourceSessionId: 'sess_projects',
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
        openTaskCount: 2,
        doneTaskCount: 1,
        highWeaknessCount: 1,
      ),
      timeline: [
        CareerTimelineItemView(
          type: 'stage',
          title: '简历投递',
          subtitle: '已投递',
          occurredAt: now.subtract(const Duration(days: 1)),
          sourceType: 'application',
          sourceId: 'application_projects_staragent',
        ),
      ],
      suggestedActions: [
        CareerSuggestedActionView(
          actionType: 'custom_resume',
          label: '生成定制简历',
          promptIntent: '基于当前岗位生成定制简历版本',
          priority: 'high',
          enabled: true,
          reason: '筛选阶段优先提升简历匹配表达',
        ),
      ],
    );
  }
}
