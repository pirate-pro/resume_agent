import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_page.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_provider.dart';

void main() {
  testWidgets('求职工作台展示项目详情、预览资产并发送推荐动作', (tester) async {
    tester.view.physicalSize = const Size(1360, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeCareerWorkbenchApi();
    String? sentPrompt;
    CareerWorkbenchActionRequest? sentAction;
    var backToChatCount = 0;

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          careerWorkbenchProvider.overrideWith(
            (ref) => CareerWorkbenchProvider(api),
          ),
        ],
        child: MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 1280,
              height: 820,
              child: CareerWorkbenchPage(
                onBackToChat: () => backToChatCount += 1,
                onSendPrompt: (prompt, {action}) async {
                  sentPrompt = prompt;
                  sentAction = action;
                },
              ),
            ),
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('求职工作台'), findsWidgets);
    expect(find.text('求职项目'), findsWidgets);
    expect(find.text('星河智能 · AI Agent 后端工程师'), findsWidgets);
    expect(find.text('当前判断'), findsOneWidget);
    expect(find.text('求职进展'), findsOneWidget);
    expect(find.text('准备投递'), findsWidgets);
    expect(find.text('关联资产'), findsOneWidget);
    expect(find.text('生成定制简历'), findsOneWidget);

    await tester.ensureVisible(find.text('预览').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('预览').first);
    await tester.pumpAndSettle();

    expect(api.previewedArtifactIds, contains('artifact_fit_report_001'));
    expect(find.text('岗位匹配报告.md'), findsOneWidget);
    expect(find.textContaining('核心匹配点'), findsOneWidget);

    await tester.tap(find.byIcon(Icons.close_rounded).last);
    await tester.pumpAndSettle();

    await tester.tap(find.text('引用').first);
    await tester.pumpAndSettle();
    expect(find.text('新建笔记'), findsWidgets);
    expect(find.text('笔记类型'), findsOneWidget);
    expect(find.text('资料'), findsWidgets);
    expect(find.textContaining('引用来源'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('career_note_body_field')),
      '# 资产引用笔记\n\n记录匹配报告里的 RAG 风险。',
    );
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.createdNoteTitles.last, contains('星河智能'));
    expect(api.createdNoteTypes.last, 'resource');
    expect(api.createdSourceRefs.last.first['source_type'], 'job_fit_report');

    await tester.tap(find.text('笔记').first);
    await tester.pumpAndSettle();
    expect(
        find.byKey(const Key('career_note_filter_resource')), findsOneWidget);
    await tester.tap(find.byKey(const Key('career_note_filter_resource')));
    await tester.pumpAndSettle();
    expect(find.textContaining('关于 星河智能'), findsWidgets);
    expect(find.textContaining('资料引用'), findsWidgets);
    expect(find.text('投递准备记录'), findsWidgets);
    await tester.tap(find.byKey(const Key('career_note_filter_all')));
    await tester.pumpAndSettle();
    expect(find.text('投递准备记录'), findsWidgets);
    expect(find.text('新建笔记'), findsWidgets);

    await tester.tap(find.text('投递准备记录').first);
    await tester.pumpAndSettle();
    expect(api.openedNoteIds, contains('note_staragent_001'));
    expect(find.textContaining('类型 记录'), findsWidgets);
    expect(find.textContaining('关联项目'), findsWidgets);
    expect(
        find.byKey(const Key('career_note_markdown_preview')), findsOneWidget);
    expect(find.textContaining('面试关注点'), findsOneWidget);
    await tester.tap(find.byKey(const Key('career_note_body_mode_实时')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('career_note_body_field')), findsOneWidget);
    expect(
        find.byKey(const Key('career_note_markdown_preview')), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('career_note_body_field')),
      '# 实时预览标题\n\n- 实时渲染条目',
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('实时渲染条目'), findsWidgets);
    await tester.tap(find.byKey(const Key('career_note_body_mode_编辑')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('career_note_body_field')), findsOneWidget);

    await tester.enterText(
      find.byKey(const Key('career_note_body_field')),
      '# 更新后的投递准备\n\n## 面试关注点\n- 补充 RAG 项目证据',
    );
    await tester.enterText(
      find.byKey(const Key('career_note_summary_field')),
      '已补充面试关注点。',
    );
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(api.updatedNoteBodies.last, contains('更新后的投递准备'));
    expect(find.text('笔记已保存'), findsOneWidget);

    await tester.tap(find.text('学习计划').first);
    await tester.pumpAndSettle();
    expect(find.text('学习路线'), findsOneWidget);
    expect(find.text('学习任务'), findsWidgets);
    expect(find.text('RAG 检索评估'), findsWidgets);
    expect(find.text('从项目推荐'), findsOneWidget);
    expect(find.text('新建任务'), findsOneWidget);

    await tester.tap(find.text('从项目推荐'));
    await tester.pumpAndSettle();
    expect(backToChatCount, 0);
    expect(sentPrompt, contains('请基于当前求职项目生成可加入学习任务的推荐建议'));
    expect(sentPrompt,
        contains('不要写 Note、CareerApplication、WeaknessTracker 或 memory'));
    expect(sentAction?.actionType, 'learning_recommend');
    expect(sentAction?.origin, 'learning');

    await tester.tap(find.text('新建任务'));
    await tester.pumpAndSettle();
    expect(find.text('新建学习任务'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('learning_task_title_field')),
      '补 RAG 评估指标',
    );
    await tester.enterText(
      find.byKey(const Key('learning_task_description_field')),
      '整理 precision、recall 和 hit rate 的项目化表达。',
    );
    await tester.enterText(
      find.byKey(const Key('learning_task_minutes_field')),
      '40',
    );
    await tester.tap(find.text('交给 Agent 创建'));
    await tester.pumpAndSettle();
    expect(backToChatCount, 0);
    expect(sentPrompt, contains('请创建一个用户主动添加的学习任务'));
    expect(sentPrompt, contains('title: 补 RAG 评估指标'));
    expect(sentPrompt, contains('estimated_minutes: 40'));
    expect(sentPrompt, contains('progress_notes 写明“来源：用户主动添加”'));
    expect(sentPrompt, contains('不要因为存在系统推荐的相似任务就跳过创建'));
    expect(sentPrompt, contains('不要写成 session:sess_'));
    expect(sentPrompt,
        contains('不要调用 learning_checkin_create 或 learning_task_update_state'));
    expect(sentAction?.actionType, 'learning_task_manual');

    await tester.tap(find.text('记录进度'));
    await tester.pumpAndSettle();
    expect(find.text('记录今日进度'), findsOneWidget);
    await tester.enterText(
      find.byKey(const Key('learning_checkin_summary_field')),
      '今天完成 RAG 指标整理。',
    );
    await tester.enterText(
      find.byKey(const Key('learning_checkin_minutes_field')),
      '35',
    );
    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('交给 Agent 记录'));
    await tester.pumpAndSettle();
    expect(backToChatCount, 0);
    expect(sentPrompt, contains('learning_task_id: learning_task_rag_eval'));
    expect(sentPrompt, contains('summary: 今天完成 RAG 指标整理。'));
    expect(sentPrompt, contains('minutes_spent: 35'));
    expect(sentPrompt, contains('state_change: done'));
    expect(sentPrompt, contains('调用 learning_checkin_create'));
    expect(sentAction?.actionType, 'learning_checkin');

    await tester.scrollUntilVisible(
      find.text('RAG 检索评估'),
      220,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('RAG 检索评估').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('验收标准'), findsOneWidget);
    await tester.tap(find.byIcon(Icons.close_rounded).last);
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('短板跟踪'),
      360,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    expect(find.text('短板跟踪'), findsOneWidget);
    expect(find.text('RAG 深度不足'), findsWidgets);
    await tester.scrollUntilVisible(
      find.text('复盘安排'),
      360,
      scrollable: find.byType(Scrollable).last,
    );
    await tester.pumpAndSettle();
    expect(find.text('复盘安排'), findsOneWidget);

    await tester.tap(find.text('简历资料').first);
    await tester.pumpAndSettle();
    expect(find.text('简历画像'), findsWidgets);
    expect(find.text('职业画像'), findsWidgets);
    expect(find.text('简历版本'), findsWidgets);
    expect(find.text('张明'), findsWidgets);
    await tester.tap(find.text('诊断').first);
    await tester.pumpAndSettle();
    expect(api.previewedArtifactIds, contains('artifact_resume_diagnosis_001'));
    await tester.tap(find.byIcon(Icons.close_rounded).last);
    await tester.pumpAndSettle();

    await tester.tap(find.text('JD 与匹配').first);
    await tester.pumpAndSettle();
    expect(find.text('JD 分析'), findsWidgets);
    expect(find.text('匹配报告'), findsWidgets);
    expect(find.text('82/100'), findsWidgets);
    await tester.tap(find.text('JD 原文').first);
    await tester.pumpAndSettle();
    expect(api.previewedArtifactIds, contains('artifact_jd_001'));
    await tester.tap(find.byIcon(Icons.close_rounded).last);
    await tester.pumpAndSettle();

    await tester.tap(find.text('笔记').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('新建笔记').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('career_note_title_field')),
      '自由复盘笔记',
    );
    await tester.enterText(
      find.byKey(const Key('career_note_body_field')),
      '# 自由复盘笔记\n\n今天补充一个独立想法。',
    );
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();
    expect(api.createdNoteTitles.last, '自由复盘笔记');
    expect(api.createdNoteTypes.last, 'note');

    await tester.tap(find.text('生成定制简历'));
    await tester.pumpAndSettle();

    expect(backToChatCount, 1);
    expect(sentPrompt, contains('application_staragent_001'));
    expect(sentPrompt, contains('生成定制简历'));
    expect(sentPrompt, contains('不要写 memory'));
    expect(sentAction?.applicationId, 'application_staragent_001');
    expect(sentAction?.label, '生成定制简历');
  });
}

class _FakeCareerWorkbenchApi extends ApiService {
  final previewedArtifactIds = <String>[];
  final openedNoteIds = <String>[];
  final updatedNoteBodies = <String>[];
  final createdNoteTitles = <String>[];
  final createdNoteTypes = <String>[];
  final createdSourceRefs = <List<Map<String, dynamic>>>[];
  final _now = DateTime(2026, 5, 10, 12, 30);
  String _noteTitle = '投递准备记录';
  String _noteSummary = '记录本轮岗位匹配和投递准备。';
  String _noteBody = '# 投递准备记录\n\n## 面试关注点\n- 复盘 Agent Runtime 项目';
  String _noteType = 'note';
  List<String> _noteTags = const ['投递'];
  final List<NoteView> _createdNotes = [];

  _FakeCareerWorkbenchApi() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_demo',
        sourceArtifactId: 'artifact_jd_001',
        evidenceRefs: const ['artifact_jd_001'],
        createdAt: _now,
        updatedAt: _now,
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_staragent_001',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        location: '上海',
        jobUrl: '',
        stage: 'ready_to_apply',
        priority: 'high',
        resumeProfileId: 'resume_profile_zhangming_003',
        careerProfileId: 'career_profile_default',
        jdAnalysisId: 'jd_staragent_001',
        jobFitReportId: 'fit_staragent_001',
        resumeVersionIds: const ['resume_version_staragent_001'],
        summary: '匹配度较高，可进入投递准备。',
        nextActions: const ['生成定制简历'],
        risks: const ['RAG 证据需要补充'],
        notes: '',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 82,
        level: 'ready',
        recommendation: 'recommended',
        summary: '候选人与目标岗位匹配度较高，建议进入定制简历阶段。',
        strengths: const [
          'Python 与 FastAPI 经验匹配',
          'Agent Runtime 项目经验可复用',
        ],
        risks: const ['RAG 证据需要补充'],
        missingMaterials: const [],
        nextActions: const ['生成定制简历'],
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
          linkedAssetCount: 3,
          noteCount: 1,
          learningTaskCount: 0,
          updatedAt: _now,
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
      updatedAt: _now,
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
          type: 'job_fit_report',
          id: 'fit_staragent_001',
          title: '星河智能 · AI Agent 后端工程师',
          subtitle: '匹配报告',
          status: 'active',
          updatedAt: _now,
          previewArtifactId: 'artifact_fit_report_001',
          sourceSessionId: 'sess_demo',
          isCurrent: true,
          actions: const ['preview'],
        ),
        CareerLinkedAssetView(
          type: 'resume_version',
          id: 'resume_version_staragent_001',
          title: '张明-星河智能定制简历.md',
          subtitle: '简历版本',
          status: 'active',
          updatedAt: _now,
          previewArtifactId: 'artifact_resume_version_001',
          sourceSessionId: 'sess_demo',
          isCurrent: true,
          actions: const ['preview'],
        ),
      ],
      notes: [
        CareerNoteSummaryView(
          noteId: 'note_staragent_001',
          title: _noteTitle,
          summary: _noteSummary,
          noteType: _noteType,
          status: 'active',
          updatedAt: _now,
          sourceArtifactId: null,
          relatedApplicationId: applicationId,
          tags: _noteTags,
        ),
      ],
      learning: CareerLearningSummaryView(
        plans: [
          CareerWorkbenchLearningPlanView(
            status: 'active',
            sourceSessionId: 'sess_demo',
            sourceArtifactId: null,
            learningPlanId: 'learning_plan_staragent_001',
            title: '星河智能投递补强计划',
            description: '围绕 RAG、Agent 架构和工程复盘补齐面试证据。',
            planType: 'job_gap',
            targetApplicationId: applicationId,
            targetRole: 'AI Agent 后端工程师',
            targetCompany: '星河智能',
            priority: 'high',
            goals: const ['补齐 RAG 项目证据', '准备 Agent Runtime 架构说明'],
            focusSkillTags: const ['RAG', 'Agent Runtime'],
            progressSummary: '已拆出第一批学习任务。',
            updatedAt: _now,
          ),
        ],
        tasks: [
          CareerWorkbenchLearningTaskView(
            status: 'active',
            sourceSessionId: 'sess_demo',
            sourceArtifactId: null,
            evidenceRefs: const ['fit_demo_001'],
            learningTaskId: 'learning_task_rag_eval',
            title: 'RAG 检索评估',
            learningPlanId: 'learning_plan_staragent_001',
            description: '整理 RAG 检索指标、chunk 策略和评估方式。',
            taskType: 'write_answer',
            priority: 'high',
            state: 'doing',
            skillTags: const ['RAG'],
            estimatedMinutes: 60,
            dueDate: _now.add(const Duration(days: 1)),
            completedAt: null,
            successCriteria: const ['能讲清召回率和准确率', '能结合项目证据说明'],
            progressNotes: '已准备指标框架。',
            updatedAt: _now,
          ),
          CareerWorkbenchLearningTaskView(
            status: 'active',
            sourceSessionId: 'sess_demo',
            sourceArtifactId: null,
            evidenceRefs: const ['application_demo_001'],
            learningTaskId: 'learning_task_agent_arch',
            title: 'Agent 架构复盘',
            learningPlanId: 'learning_plan_staragent_001',
            description: '整理主 Agent 与子 Agent 的协作边界。',
            taskType: 'review',
            priority: 'medium',
            state: 'todo',
            skillTags: const ['Agent Runtime'],
            estimatedMinutes: 45,
            dueDate: null,
            completedAt: null,
            successCriteria: const ['能说明任务委派和进度事件'],
            progressNotes: '',
            updatedAt: _now,
          ),
        ],
        weaknesses: [
          CareerWorkbenchWeaknessView(
            status: 'active',
            sourceSessionId: 'sess_demo',
            sourceArtifactId: null,
            weaknessId: 'weakness_rag_depth',
            title: 'RAG 深度不足',
            description: '匹配报告显示 RAG 实战证据需要补充。',
            weaknessType: 'skill',
            severity: 'high',
            state: 'tracking',
            skillTags: const ['RAG'],
            relatedTaskIds: const ['learning_task_rag_eval'],
            updatedAt: _now,
          ),
        ],
        reviews: [
          CareerWorkbenchReviewView(
            status: 'active',
            sourceSessionId: 'sess_demo',
            sourceArtifactId: null,
            reviewScheduleId: 'review_rag_eval',
            title: 'RAG 答案复盘',
            reviewType: 'task',
            state: 'scheduled',
            reviewAt: _now.add(const Duration(days: 2)),
            nextReviewAt: null,
            summary: '复盘 RAG 问答是否足够贴近岗位要求。',
            updatedAt: _now,
          ),
        ],
        openTaskCount: 2,
        doneTaskCount: 0,
        highWeaknessCount: 1,
      ),
      timeline: [
        CareerTimelineItemView(
          type: 'job_fit_report',
          title: '匹配报告更新',
          subtitle: 'fit_staragent_001',
          occurredAt: _now,
          sourceType: 'job_fit_report',
          sourceId: 'fit_staragent_001',
        ),
      ],
      suggestedActions: [
        CareerSuggestedActionView(
          actionType: 'custom_resume',
          label: '生成定制简历',
          promptIntent: '基于当前岗位生成定制简历版本',
          priority: 'high',
          enabled: true,
          reason: '已有匹配报告，可以定制简历',
        ),
      ],
    );
  }

  @override
  Future<List<ResumeProfileView>> listCareerResumeProfiles({
    bool includeArchived = false,
  }) async {
    return [
      ResumeProfileView(
        meta: _meta,
        resumeProfileId: 'resume_profile_zhangming_003',
        basicInfo: const {'name': '张明'},
        education: const ['上海理工大学 · 软件工程本科'],
        workExperience: const ['4 年后端研发经验'],
        projectExperience: const ['Agent Runtime 平台'],
        skills: const ['Python', 'FastAPI', 'PostgreSQL'],
        certificates: const [],
        awards: const [],
        selfEvaluation: '具备 Agent Runtime 与后端工程经验。',
        rawTextArtifactId: 'artifact_resume_raw_001',
        diagnosisArtifactId: 'artifact_resume_diagnosis_001',
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
        meta: _meta,
        careerProfileId: 'career_profile_default',
        careerGoal: 'AI Agent 后端工程师',
        targetRoles: const ['后端工程师', 'AI 应用工程师'],
        preferredIndustries: const ['AI'],
        preferredCities: const ['上海'],
        strengths: const ['工程化经验', 'Agent 系统经验'],
        weaknesses: const ['RAG 证据需补充'],
        skills: const ['Python', 'FastAPI'],
        interests: const [],
        educationSummary: '软件工程本科',
        experienceSummary: '4 年后端研发经验',
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
        meta: _meta,
        jdAnalysisId: 'jd_staragent_001',
        company: '星河智能',
        position: 'AI Agent 后端工程师',
        seniority: '中级',
        requiredSkills: const ['Python', 'FastAPI'],
        preferredSkills: const ['RAG', 'Agent Runtime'],
        responsibilities: const ['建设 Agent 平台后端服务'],
        keywords: const ['AI Agent', '后端'],
        riskSignals: const ['RAG 深度要求较高'],
        interviewFocus: const ['Agent Runtime 架构'],
      ),
    ];
  }

  @override
  Future<List<JobFitReportView>> listCareerJobFitReports({
    bool includeArchived = false,
  }) async {
    return [
      JobFitReportView(
        meta: _meta,
        jobFitReportId: 'fit_staragent_001',
        jdAnalysisId: 'jd_staragent_001',
        resumeProfileId: 'resume_profile_zhangming_003',
        careerProfileId: 'career_profile_default',
        overallScore: 82,
        scoreBreakdown: const {'技术匹配': 85, 'RAG 经验': 65},
        matchedEvidence: const ['Python 与 FastAPI 项目经验匹配'],
        gaps: const ['RAG 实战证据需补充'],
        resumeOptimizationDirection: const ['补充 RAG 链路细节'],
        interviewPreparationFocus: const ['准备 Agent Runtime 设计说明'],
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
        meta: _meta,
        resumeVersionId: 'resume_version_staragent_001',
        baseResumeProfileId: 'resume_profile_zhangming_003',
        targetJdAnalysisId: 'jd_staragent_001',
        title: '张明-星河智能定制简历.md',
        format: 'markdown',
        artifactId: 'artifact_resume_version_001',
        changeSummary: const ['突出 Agent Runtime 项目'],
        keywordStrategy: const ['Python', 'FastAPI', 'Agent'],
        riskNotes: const ['补充 RAG 证据'],
      ),
    ];
  }

  @override
  Future<NoteView> getNote({
    required String noteId,
    bool includeArchived = false,
  }) async {
    openedNoteIds.add(noteId);
    return _noteView();
  }

  @override
  Future<List<NoteView>> listNotes({
    bool includeArchived = false,
    String? collectionId,
    String? relatedApplicationId,
  }) async {
    return [_noteView(), ..._createdNotes];
  }

  @override
  Future<NoteView> createNote({
    String? noteId,
    required String sourceSessionId,
    String? sourceArtifactId,
    List<String> evidenceRefs = const [],
    required String title,
    required String bodyMarkdown,
    String bodyFormat = 'markdown',
    String noteType = 'note',
    String origin = 'user',
    String? collectionId,
    List<String> tags = const [],
    List<Map<String, dynamic>> sourceRefs = const [],
    String? relatedApplicationId,
    String summary = '',
  }) async {
    createdNoteTitles.add(title);
    createdNoteTypes.add(noteType);
    createdSourceRefs.add(sourceRefs);
    final note = NoteView(
      noteId: noteId ?? 'note_created_${createdNoteTitles.length}',
      status: 'active',
      sourceSessionId: sourceSessionId,
      sourceArtifactId: sourceArtifactId,
      evidenceRefs: evidenceRefs,
      createdAt: _now,
      updatedAt: _now,
      title: title,
      bodyMarkdown: bodyMarkdown,
      bodyFormat: bodyFormat,
      noteType: noteType,
      origin: origin,
      collectionId: collectionId,
      tags: tags,
      sourceRefs:
          sourceRefs.map((item) => NoteSourceRefView.fromJson(item)).toList(),
      relatedApplicationId: relatedApplicationId,
      summary: summary,
    );
    _createdNotes.insert(0, note);
    return note;
  }

  @override
  Future<NoteView> updateNote({
    required String noteId,
    String? title,
    String? bodyMarkdown,
    String? bodyFormat,
    String? noteType,
    String? summary,
    List<String>? tags,
    String? collectionId,
    String? relatedApplicationId,
  }) async {
    if (title != null) {
      _noteTitle = title;
    }
    if (summary != null) {
      _noteSummary = summary;
    }
    if (bodyMarkdown != null) {
      _noteBody = bodyMarkdown;
      updatedNoteBodies.add(bodyMarkdown);
    }
    if (noteType != null) {
      _noteType = noteType;
    }
    if (tags != null) {
      _noteTags = tags;
    }
    return _noteView();
  }

  NoteView _noteView() {
    return NoteView(
      noteId: 'note_staragent_001',
      status: 'active',
      sourceSessionId: 'sess_demo',
      sourceArtifactId: null,
      evidenceRefs: const ['application_staragent_001'],
      createdAt: _now,
      updatedAt: _now,
      title: _noteTitle,
      bodyMarkdown: _noteBody,
      bodyFormat: 'markdown',
      noteType: _noteType,
      collectionId: null,
      tags: _noteTags,
      sourceRefs: const [],
      relatedApplicationId: 'application_staragent_001',
      summary: _noteSummary,
    );
  }

  @override
  Future<SessionArtifactContentView> readSessionArtifactContent({
    required String sessionId,
    required String artifactId,
    int offset = 0,
    int maxChars = 12000,
  }) async {
    previewedArtifactIds.add(artifactId);
    const content = '# 岗位匹配报告\n\n## 核心匹配点\n- Python 与 FastAPI 经验匹配';
    return SessionArtifactContentView(
      sessionId: sessionId,
      artifactId: artifactId,
      title: '岗位匹配报告.md',
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
