import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_provider.dart';
import 'package:resume_agent_app/features/learning/learning_plan_page.dart';

void main() {
  testWidgets('学习计划页展示路线、任务、短板并发送推荐动作', (tester) async {
    tester.view.physicalSize = const Size(900, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeLearningPlanApi();
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
            body: LearningPlanPage(
              onOpenProjects: () {},
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

    expect(find.text('学习计划'), findsOneWidget);
    expect(find.text('补短板'), findsOneWidget);
    expect(find.text('当前学习状态'), findsOneWidget);
    expect(find.text('关联求职项目'), findsOneWidget);

    await tester.tap(find.text('生成建议').first);
    await tester.pump();

    expect(sentPrompt, contains('application_learning_plan'));
    expect(sentAction?.origin, 'learning_plan');
    expect(sentAction?.actionType, 'learning_recommend');

    await tester.scrollUntilVisible(
      find.text('多 Agent 后端工程化补强路线'),
      320,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('学习路线'), findsWidgets);
    expect(find.text('多 Agent 后端工程化补强路线'), findsWidgets);

    await tester.scrollUntilVisible(
      find.text('补齐任务编排状态机实践'),
      320,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('补齐任务编排状态机实践'), findsWidgets);

    await tester.scrollUntilVisible(
      find.text('短板与证据缺口'),
      320,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('生产级任务编排经验不足'), findsWidgets);

    await tester.scrollUntilVisible(
      find.text('复盘安排'),
      320,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('系统设计复盘'), findsOneWidget);
  });
}

class _FakeLearningPlanApi extends ApiService {
  final now = DateTime(2026, 5, 16, 10, 49);

  _FakeLearningPlanApi() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_learning_plan',
        sourceArtifactId: 'artifact_learning_plan',
        evidenceRefs: const ['artifact_learning_plan'],
        createdAt: now.subtract(const Duration(days: 4)),
        updatedAt: now,
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_learning_plan',
        company: '华为',
        position: 'AI Agent 后端工程师',
        location: '深圳',
        jobUrl: '',
        stage: 'interviewing',
        priority: 'high',
        resumeProfileId: 'resume_profile_learning',
        careerProfileId: 'career_profile_learning',
        jdAnalysisId: 'jd_learning',
        jobFitReportId: 'fit_learning',
        resumeVersionIds: const ['resume_version_learning'],
        summary: '匹配度较高，但需要补齐多 Agent 工程化和状态追踪案例。',
        nextActions: const ['补齐工程化项目证据', '准备系统设计问题'],
        risks: const ['任务编排经验表达不足'],
        notes: '',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 78,
        level: 'good',
        recommendation: 'recommended',
        summary: '岗位匹配度较高，建议围绕工程化短板推进学习计划。',
        strengths: const ['FastAPI 和 Agent 项目经验匹配'],
        risks: const ['生产级任务编排经验不足'],
        missingMaterials: const [],
        nextActions: const ['补齐任务编排状态机实践'],
      );

  CareerWorkbenchLearningPlanView get _plan => CareerWorkbenchLearningPlanView(
        status: 'active',
        sourceSessionId: 'sess_learning_plan',
        sourceArtifactId: 'artifact_learning_plan',
        learningPlanId: 'learning_plan_agent_backend',
        title: '多 Agent 后端工程化补强路线',
        description: '围绕状态机、工具调用、可观测性和并发稳定性补齐项目证据。',
        planType: 'job_gap',
        targetApplicationId: _application.applicationId,
        targetRole: 'AI Agent 后端工程师',
        targetCompany: '华为',
        priority: 'high',
        goals: const [
          '完成任务编排状态机总结',
          '补齐工具调用幂等和审计案例',
        ],
        focusSkillTags: const ['Agent', '任务编排', '可观测性'],
        progressSummary: '已完成 RAG 基础复盘，下一步补齐工程化实践。',
        updatedAt: now,
      );

  CareerWorkbenchLearningTaskView get _doingTask =>
      CareerWorkbenchLearningTaskView(
        status: 'active',
        sourceSessionId: 'sess_learning_plan',
        sourceArtifactId: 'artifact_learning_plan',
        evidenceRefs: const ['fit_learning'],
        learningTaskId: 'learning_task_orchestration',
        title: '补齐任务编排状态机实践',
        learningPlanId: 'learning_plan_agent_backend',
        description: '整理 main-agent、orchestrator、tool gateway 的边界案例。',
        taskType: 'project',
        priority: 'high',
        state: 'doing',
        skillTags: const ['状态机', 'Agent', '工具幂等'],
        estimatedMinutes: 90,
        dueDate: now.add(const Duration(days: 1)),
        completedAt: null,
        successCriteria: const ['形成一页系统设计说明', '补充到简历项目经历'],
        progressNotes: '来源：岗位匹配短板',
        updatedAt: now,
      );

  CareerWorkbenchLearningTaskView get _todoTask =>
      CareerWorkbenchLearningTaskView(
        status: 'active',
        sourceSessionId: 'sess_learning_plan',
        sourceArtifactId: null,
        evidenceRefs: const ['note_interview_review'],
        learningTaskId: 'learning_task_interview_review',
        title: '准备系统设计追问答案',
        learningPlanId: 'learning_plan_agent_backend',
        description: '针对系统可观测性、失败恢复和成本控制准备回答。',
        taskType: 'interview',
        priority: 'medium',
        state: 'todo',
        skillTags: const ['系统设计', '可观测性'],
        estimatedMinutes: 45,
        dueDate: now.add(const Duration(days: 2)),
        completedAt: null,
        successCriteria: const ['准备 3 个追问答案'],
        progressNotes: '来源：面试复盘建议',
        updatedAt: now.subtract(const Duration(hours: 2)),
      );

  CareerWorkbenchWeaknessView get _weakness => CareerWorkbenchWeaknessView(
        status: 'active',
        sourceSessionId: 'sess_learning_plan',
        sourceArtifactId: 'artifact_learning_plan',
        weaknessId: 'weakness_orchestration',
        title: '生产级任务编排经验不足',
        description: '简历中缺少对状态流转、工具调用账本和失败恢复的项目证据。',
        weaknessType: 'project_evidence',
        severity: 'high',
        state: 'open',
        skillTags: const ['任务编排', '工程化'],
        relatedTaskIds: const ['learning_task_orchestration'],
        updatedAt: now,
      );

  CareerWorkbenchReviewView get _review => CareerWorkbenchReviewView(
        status: 'active',
        sourceSessionId: 'sess_learning_plan',
        sourceArtifactId: null,
        reviewScheduleId: 'review_system_design',
        title: '系统设计复盘',
        reviewType: 'weekly',
        state: 'scheduled',
        reviewAt: now.add(const Duration(days: 3)),
        nextReviewAt: now.add(const Duration(days: 3)),
        summary: '复盘任务编排和 RAG 写入场景的架构边界。',
        updatedAt: now,
      );

  CareerNoteSummaryView get _note => CareerNoteSummaryView(
        noteId: 'note_interview_review',
        title: 'AI Agent 面试复盘',
        summary: '系统设计追问需要补充失败恢复和幂等案例。',
        status: 'active',
        updatedAt: now,
        noteType: 'review',
        origin: 'agent',
        sourceArtifactId: null,
        relatedApplicationId: _application.applicationId,
        tags: const ['面试复盘', '系统设计'],
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
      linkedAssets: const [],
      notes: [_note],
      learning: CareerLearningSummaryView(
        plans: [_plan],
        tasks: [_doingTask, _todoTask],
        weaknesses: [_weakness],
        reviews: [_review],
        openTaskCount: 2,
        doneTaskCount: 0,
        highWeaknessCount: 1,
      ),
      timeline: const [],
      suggestedActions: const [],
    );
  }
}
