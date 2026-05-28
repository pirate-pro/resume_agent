import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_provider.dart';
import 'package:resume_agent_app/features/resumes/resume_library_page.dart';

void main() {
  testWidgets('简历资料页展示版本、预览、洞察并发送生成版本动作', (tester) async {
    tester.view.physicalSize = const Size(1440, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeResumeLibraryApi();
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
            body: ResumeLibraryPage(
              onOpenProjects: () {},
              onOpenJDMatch: () {},
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

    expect(find.text('简历资料'), findsOneWidget);
    expect(find.text('版本管理'), findsOneWidget);
    expect(find.text('版本列表'), findsOneWidget);
    expect(find.text('前端开发工程师定制简历'), findsWidgets);
    expect(find.text('张明'), findsOneWidget);
    expect(find.text('AI 洞察'), findsOneWidget);
    expect(find.text('推荐动作'), findsOneWidget);
    expect(find.text('关联岗位'), findsOneWidget);

    await tester.tap(find.text('生成新版本').first);
    await tester.pump();

    expect(sentPrompt, contains('application_resume_library'));
    expect(sentAction?.origin, 'resume_library');
    expect(sentAction?.actionType, 'custom_resume');

    await tester.scrollUntilVisible(
      find.text('版本历史'),
      320,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('版本历史'), findsOneWidget);
  });
}

class _FakeResumeLibraryApi extends ApiService {
  final now = DateTime(2026, 5, 16, 10, 49);

  _FakeResumeLibraryApi() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_resume_library',
        sourceArtifactId: 'artifact_resume_library',
        evidenceRefs: const ['artifact_resume_library'],
        createdAt: now.subtract(const Duration(days: 3)),
        updatedAt: now,
      );

  ResumeProfileView get _resumeProfile => ResumeProfileView(
        meta: _meta,
        resumeProfileId: 'resume_profile_resume_library',
        basicInfo: const {'name': '张明'},
        education: const [],
        workExperience: const [
          {'company': '字节跳动', 'role': '前端开发工程师'},
        ],
        projectExperience: const [
          {'title': '创作客服数据分析平台', 'summary': '负责数据分析和前端工程化。'},
        ],
        skills: const ['React', 'TypeScript', '性能优化'],
        certificates: const [],
        awards: const [],
        selfEvaluation: '3 年前端开发经验，擅长 React 与工程化。',
        rawTextArtifactId: 'artifact_resume_raw',
        diagnosisArtifactId: 'artifact_resume_diagnosis',
        diagnosis: const {
          'score': 85,
          'risks': ['量化结果还可以更突出'],
        },
      );

  CareerProfileView get _careerProfile => CareerProfileView(
        meta: _meta,
        careerProfileId: 'career_profile_resume_library',
        careerGoal: '前端开发工程师',
        targetRoles: const ['前端开发工程师'],
        preferredIndustries: const ['互联网'],
        preferredCities: const ['北京', '杭州'],
        strengths: const ['项目经验丰富', '技术栈匹配度较高'],
        weaknesses: const ['业务价值表达不足'],
        skills: const ['React', 'TypeScript', '工程化'],
        interests: const [],
        educationSummary: '本科',
        experienceSummary: '具备 React、TypeScript 和复杂业务系统开发经验。',
        resumeIssues: const ['需要补充业务指标'],
        interviewWeaknesses: const [],
      );

  ResumeVersionView get _resumeVersion => ResumeVersionView(
        meta: _meta,
        resumeVersionId: 'resume_version_resume_library_v3',
        baseResumeProfileId: 'resume_profile_resume_library',
        targetJdAnalysisId: 'jd_resume_library',
        title: '前端开发工程师定制简历',
        format: 'markdown',
        artifactId: 'artifact_resume_version',
        changeSummary: const ['强化项目指标和业务价值表达'],
        keywordStrategy: const ['React', 'TypeScript', '微前端'],
        riskNotes: const ['部分项目缺少量化结果'],
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_resume_library',
        company: '字节跳动',
        position: '前端开发工程师',
        location: '北京',
        jobUrl: '',
        stage: 'screening',
        priority: 'high',
        resumeProfileId: 'resume_profile_resume_library',
        careerProfileId: 'career_profile_resume_library',
        jdAnalysisId: 'jd_resume_library',
        jobFitReportId: 'fit_resume_library',
        resumeVersionIds: const ['resume_version_resume_library_v3'],
        summary: '当前岗位匹配度较高，建议优化项目指标。',
        nextActions: const ['优化项目描述'],
        risks: const ['缺少业务量化指标'],
        notes: '',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 85,
        level: 'good',
        recommendation: 'recommended',
        summary: '匹配度较高，建议继续优化简历。',
        strengths: const ['React 经验匹配'],
        risks: const ['业务价值表达不足'],
        missingMaterials: const [],
        nextActions: const ['优化项目描述'],
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
          learningTaskCount: 0,
          updatedAt: now,
        ),
      ],
      activeApplicationId: _application.applicationId,
      counts: CareerWorkbenchCountsView(
        applications: 1,
        activeApplications: 1,
        notes: 1,
        learningTasks: 0,
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
      resumeProfile: _resumeProfile,
      careerProfile: _careerProfile,
      jdAnalysis: null,
      jobFitReport: null,
      resumeVersions: [_resumeVersion],
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
      suggestedActions: const [],
    );
  }

  @override
  Future<List<ResumeProfileView>> listCareerResumeProfiles({
    bool includeArchived = false,
  }) async =>
      [_resumeProfile];

  @override
  Future<List<CareerProfileView>> listCareerProfiles({
    bool includeArchived = false,
  }) async =>
      [_careerProfile];

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
      [_resumeVersion];
}
