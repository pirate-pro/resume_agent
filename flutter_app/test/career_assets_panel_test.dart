import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/providers/career_assets_provider.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career/career_assets_panel.dart';

void main() {
  testWidgets('求职资产卡片隐藏长 ID 并触发预览动作', (tester) async {
    String? previewedArtifactId;
    var detailsOpened = false;
    var historyOpened = false;
    final record = ResumeProfileView(
      meta: CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_demo',
        sourceArtifactId: 'artifact_resume_source',
        evidenceRefs: const ['artifact_resume_source'],
        createdAt: DateTime(2026, 5, 8, 13, 20),
        updatedAt: DateTime(2026, 5, 8, 14, 28),
      ),
      resumeProfileId: 'resume_profile_zhangming_003',
      basicInfo: const {'name': '张明'},
      education: const [],
      workExperience: const [{}, {}],
      projectExperience: const [{}, {}, {}],
      skills: List<Object>.filled(29, const {}),
      certificates: const [],
      awards: const [],
      selfEvaluation: '',
      rawTextArtifactId: 'artifact_resume_source',
      diagnosisArtifactId: 'artifact_diagnosis_001',
      diagnosis: const {},
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 320,
              child: ResumeProfileCard(
                record: record,
                selected: false,
                highlighted: false,
                onDetails: () => detailsOpened = true,
                onPreviewArtifact: (artifactId) async {
                  previewedArtifactId = artifactId;
                },
                historyCount: 3,
                onHistory: () => historyOpened = true,
              ),
            ),
          ),
        ),
      ),
    );

    expect(find.text('张明'), findsOneWidget);
    expect(find.text('resume_profile_zhangming_003'), findsNothing);
    expect(find.text('当前诊断'), findsNothing);
    expect(find.text('可预览'), findsOneWidget);
    expect(find.text('详情'), findsOneWidget);
    expect(find.text('预览诊断'), findsOneWidget);
    expect(find.text('3 版'), findsOneWidget);
    expect(find.text('当前版本 · 2 版历史已收起'), findsOneWidget);
    expect(find.text('查看'), findsOneWidget);
    expect(find.text('历史 3'), findsOneWidget);

    await tester.tap(find.text('详情'));
    expect(detailsOpened, isTrue);

    await tester.tap(find.text('预览诊断'));
    await tester.pump();
    expect(previewedArtifactId, 'artifact_diagnosis_001');

    historyOpened = false;
    await tester.tap(find.text('查看'));
    expect(historyOpened, isTrue);

    historyOpened = false;
    await tester.tap(find.text('历史 3'));
    expect(historyOpened, isTrue);
  });

  testWidgets('求职项目卡片展示项目阶段并优先预览匹配报告', (tester) async {
    String? previewedArtifactId;
    var updateOpened = false;
    final record = CareerApplicationView(
      meta: CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_demo',
        sourceArtifactId: 'artifact_jd_001',
        evidenceRefs: const ['artifact_jd_001'],
        createdAt: DateTime(2026, 5, 8, 13, 20),
        updatedAt: DateTime(2026, 5, 8, 14, 28),
      ),
      applicationId: 'application_zhangming_staragent_001',
      company: '星河智能',
      position: 'AI Agent 后端工程师',
      location: '上海',
      jobUrl: '',
      stage: 'ready_to_apply',
      priority: 'high',
      resumeProfileId: 'resume_profile_zhangming_003',
      careerProfileId: 'career_profile_default',
      jdAnalysisId: 'jd_zhangming_staragent_001',
      jobFitReportId: 'fit_zhangming_staragent_001',
      resumeVersionIds: const ['resume_version_zhangming_staragent_001'],
      summary: '匹配度较高，可进入投递准备。',
      nextActions: const ['复核定制简历事实准确性'],
      risks: const ['RAG 证据需要补充'],
      notes: '',
    );
    final fitReport = JobFitReportView(
      meta: CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_demo',
        sourceArtifactId: 'artifact_jd_001',
        evidenceRefs: const ['artifact_jd_001'],
        createdAt: DateTime(2026, 5, 8, 13, 20),
        updatedAt: DateTime(2026, 5, 8, 14, 28),
      ),
      jobFitReportId: 'fit_zhangming_staragent_001',
      jdAnalysisId: 'jd_zhangming_staragent_001',
      resumeProfileId: 'resume_profile_zhangming_003',
      careerProfileId: 'career_profile_default',
      overallScore: 82,
      scoreBreakdown: const {},
      matchedEvidence: const [],
      gaps: const [],
      resumeOptimizationDirection: const [],
      interviewPreparationFocus: const [],
      recommendation: 'recommended',
      reportArtifactId: 'artifact_fit_report_001',
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 340,
              child: CareerApplicationCard(
                record: record,
                fitReport: fitReport,
                latestResumeVersion: null,
                selected: false,
                highlighted: false,
                onDetails: () {},
                onPreviewArtifact: (artifactId) async {
                  previewedArtifactId = artifactId;
                },
                onUpdate: () => updateOpened = true,
              ),
            ),
          ),
        ),
      ),
    );

    expect(find.text('求职项目'), findsOneWidget);
    expect(find.text('星河智能 · AI Agent 后端工程师'), findsOneWidget);
    expect(find.text('可投递'), findsOneWidget);
    expect(find.text('高优先级'), findsOneWidget);
    expect(find.text('5 项资料'), findsOneWidget);
    expect(find.text('预览报告'), findsOneWidget);
    expect(find.text('更新进展'), findsOneWidget);
    expect(find.textContaining('匹配度较高'), findsOneWidget);
    expect(find.textContaining('复核定制简历'), findsOneWidget);

    await tester.tap(find.text('预览报告'));
    await tester.pump();
    expect(previewedArtifactId, 'artifact_fit_report_001');

    await tester.tap(find.text('更新进展'));
    expect(updateOpened, isTrue);
  });

  testWidgets('求职项目详情串起关联资产和匹配报告预览', (tester) async {
    final api = _FakeCareerApiService();
    final provider = CareerAssetsProvider(api);
    await provider.refresh();
    provider.setTab(CareerAssetsTab.applications);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 420,
              height: 760,
              child: CareerAssetList(provider: provider),
            ),
          ),
        ),
      ),
    );

    expect(find.text('星河智能 · AI Agent 后端工程师'), findsOneWidget);
    expect(find.text('详情'), findsOneWidget);

    await tester.tap(find.text('详情'));
    await tester.pumpAndSettle();

    expect(find.textContaining('求职项目工作台'), findsOneWidget);
    expect(find.text('关联资料'), findsOneWidget);
    expect(find.text('简历画像'), findsWidgets);
    expect(find.text('职业画像'), findsWidgets);
    expect(find.text('JD 分析'), findsWidgets);
    expect(find.text('匹配报告'), findsWidgets);
    expect(find.text('定制简历'), findsWidgets);
    expect(find.text('下一步行动'), findsOneWidget);
    expect(find.text('风险点'), findsOneWidget);

    await tester.tap(find.text('预览匹配报告'));
    await tester.pumpAndSettle();

    expect(api.previewedArtifactIds, contains('artifact_fit_report_001'));
    expect(find.text('M7 匹配报告.md'), findsOneWidget);
    expect(find.textContaining('整体匹配度'), findsOneWidget);
  });

  testWidgets('求职项目工作台快捷动作发送受控提示词', (tester) async {
    final api = _FakeCareerApiService();
    final provider = CareerAssetsProvider(api);
    final prompts = <String>[];
    await provider.refresh();
    provider.setTab(CareerAssetsTab.applications);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 420,
              height: 760,
              child: CareerAssetList(
                provider: provider,
                onApplicationPromptAction: (prompt) async {
                  prompts.add(prompt);
                },
              ),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('详情'));
    await tester.pumpAndSettle();

    expect(find.text('生成定制简历'), findsOneWidget);
    expect(find.text('投递前检查'), findsOneWidget);
    expect(find.text('面试准备'), findsOneWidget);

    await tester.tap(find.text('生成定制简历'));
    await tester.pumpAndSettle();

    expect(prompts, hasLength(1));
    expect(prompts.single, contains('application_zhangming_staragent_001'));
    expect(prompts.single, contains('resume_profile_zhangming_003'));
    expect(prompts.single, contains('career_resume_version_create'));
    expect(prompts.single, contains('career_application_merge'));
    expect(prompts.single, contains('不要重新解析简历'));
  });
}

class _FakeCareerApiService extends ApiService {
  final List<String> previewedArtifactIds = [];
  final _now = DateTime(2026, 5, 11, 10, 30);

  _FakeCareerApiService() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView _meta({
    String sourceArtifactId = 'artifact_jd_001',
  }) {
    return CareerRecordMetaView(
      status: 'active',
      sourceSessionId: 'sess_demo',
      sourceArtifactId: sourceArtifactId,
      evidenceRefs: [sourceArtifactId],
      createdAt: _now,
      updatedAt: _now,
    );
  }

  @override
  Future<List<ResumeProfileView>> listCareerResumeProfiles({
    bool includeArchived = false,
  }) async {
    return [
      ResumeProfileView(
        meta: _meta(sourceArtifactId: 'artifact_resume_source'),
        resumeProfileId: 'resume_profile_zhangming_003',
        basicInfo: const {'name': '张明'},
        education: const [],
        workExperience: const [{}, {}],
        projectExperience: const [{}, {}, {}],
        skills: List<Object>.filled(29, const {}),
        certificates: const [],
        awards: const [],
        selfEvaluation: '',
        rawTextArtifactId: 'artifact_resume_source',
        diagnosisArtifactId: 'artifact_diagnosis_001',
        diagnosis: const {},
      ),
    ];
  }

  @override
  Future<List<CareerProfileView>> listCareerProfiles({
    bool includeArchived = false,
  }) async {
    return [
      CareerProfileView(
        meta: _meta(sourceArtifactId: 'artifact_resume_source'),
        careerProfileId: 'career_profile_default',
        careerGoal: 'AI Agent 后端工程师',
        targetRoles: const ['后端工程师', 'AI 应用工程师'],
        preferredIndustries: const [],
        preferredCities: const ['上海'],
        strengths: const ['工程质量意识强'],
        weaknesses: const ['RAG 经验需要补充'],
        skills: const ['Python', 'FastAPI', 'PostgreSQL'],
        interests: const [],
        educationSummary: '',
        experienceSummary: '',
        resumeIssues: const [],
        interviewWeaknesses: const [],
      ),
    ];
  }

  @override
  Future<List<JDAnalysisView>> listCareerJobs({
    bool includeArchived = false,
  }) async {
    return [
      JDAnalysisView(
        meta: _meta(sourceArtifactId: 'artifact_jd_001'),
        jdAnalysisId: 'jd_zhangming_staragent_001',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        seniority: '3 年以上',
        requiredSkills: const ['Python', 'FastAPI', 'RAG'],
        preferredSkills: const ['LangGraph'],
        responsibilities: const ['建设 Agent 平台'],
        keywords: const ['Agent', 'RAG'],
        riskSignals: const ['RAG 深度要求高'],
        interviewFocus: const ['系统设计'],
      ),
    ];
  }

  @override
  Future<List<JobFitReportView>> listCareerJobFitReports({
    bool includeArchived = false,
  }) async {
    return [
      JobFitReportView(
        meta: _meta(sourceArtifactId: 'artifact_jd_001'),
        jobFitReportId: 'fit_zhangming_staragent_001',
        jdAnalysisId: 'jd_zhangming_staragent_001',
        resumeProfileId: 'resume_profile_zhangming_003',
        careerProfileId: 'career_profile_default',
        overallScore: 82,
        scoreBreakdown: const {'技术栈匹配': 85},
        matchedEvidence: const [],
        gaps: const [],
        resumeOptimizationDirection: const [],
        interviewPreparationFocus: const [],
        recommendation: 'recommended',
        reportArtifactId: 'artifact_fit_report_001',
      ),
    ];
  }

  @override
  Future<List<ResumeVersionView>> listCareerResumeVersions({
    bool includeArchived = false,
  }) async {
    return [
      ResumeVersionView(
        meta: _meta(sourceArtifactId: 'artifact_resume_version_001'),
        resumeVersionId: 'resume_version_zhangming_staragent_001',
        baseResumeProfileId: 'resume_profile_zhangming_003',
        targetJdAnalysisId: 'jd_zhangming_staragent_001',
        title: '星河智能定制简历',
        format: 'markdown',
        artifactId: 'artifact_resume_version_001',
        changeSummary: const ['强化 Agent 平台经验'],
        keywordStrategy: const ['Python', 'FastAPI'],
        riskNotes: const [],
      ),
    ];
  }

  @override
  Future<List<CareerApplicationView>> listCareerApplications({
    bool includeArchived = false,
  }) async {
    return [
      CareerApplicationView(
        meta: _meta(sourceArtifactId: 'artifact_jd_001'),
        applicationId: 'application_zhangming_staragent_001',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        location: '上海',
        jobUrl: '',
        stage: 'ready_to_apply',
        priority: 'high',
        resumeProfileId: 'resume_profile_zhangming_003',
        careerProfileId: 'career_profile_default',
        jdAnalysisId: 'jd_zhangming_staragent_001',
        jobFitReportId: 'fit_zhangming_staragent_001',
        resumeVersionIds: const ['resume_version_zhangming_staragent_001'],
        summary: '匹配度较高，可进入投递准备。',
        nextActions: const ['复核定制简历事实准确性'],
        risks: const ['RAG 证据需要补充'],
        notes: '本轮由完整求职链路生成。',
      ),
    ];
  }

  @override
  Future<SessionArtifactContentView> readSessionArtifactContent({
    required String sessionId,
    required String artifactId,
    int offset = 0,
    int maxChars = 12000,
  }) async {
    previewedArtifactIds.add(artifactId);
    const content =
        '# 岗位匹配报告\n\n整体匹配度：82/100\n\n## 核心匹配点\n- Python 与 FastAPI 经验匹配';
    return SessionArtifactContentView(
      sessionId: sessionId,
      artifactId: artifactId,
      title: 'M7 匹配报告.md',
      mediaType: 'text/markdown',
      status: 'active',
      totalChars: content.length,
      offset: 0,
      returnedChars: content.length,
      truncated: false,
      content: content,
    );
  }

  @override
  String sessionArtifactDownloadUrl({
    required String sessionId,
    required String artifactId,
  }) {
    return 'http://localhost/download/$sessionId/$artifactId';
  }
}
