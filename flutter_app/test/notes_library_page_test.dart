import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/core/services/api_service.dart';
import 'package:resume_agent_app/features/career_workbench/career_workbench_provider.dart';
import 'package:resume_agent_app/features/notes/notes_library_page.dart';

void main() {
  testWidgets('笔记页展示、编辑、新建并发送复盘动作', (tester) async {
    tester.view.physicalSize = const Size(1440, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final api = _FakeNotesApi();
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
            body: NotesLibraryPage(
              currentSessionId: 'sess_current_notes',
              onOpenProjects: () {},
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

    expect(find.text('笔记'), findsOneWidget);
    expect(find.text('知识沉淀'), findsOneWidget);
    expect(find.text('笔记库'), findsOneWidget);
    expect(find.text('投递准备记录'), findsWidgets);
    expect(find.text('AI Agent 面试复盘'), findsWidgets);
    expect(find.byKey(const Key('notes_markdown_preview')), findsOneWidget);
    expect(find.textContaining('面试关注点'), findsWidgets);

    await tester.tap(find.text('复盘整理').first);
    await tester.pump();
    expect(sentPrompt, contains('application_notes'));
    expect(sentAction?.origin, 'notes_library');
    expect(sentAction?.actionType, 'note_create');

    await tester.tap(find.text('编辑').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('notes_body_field')),
      '# 更新后的投递准备\n\n- 补充 RAG 项目证据',
    );
    await tester.enterText(
      find.byKey(const Key('notes_summary_field')),
      '已补充面试关注点。',
    );
    await tester.ensureVisible(find.text('保存').last);
    await tester.tap(find.text('保存').last);
    await tester.pumpAndSettle();

    expect(api.updatedNoteBodies.last, contains('更新后的投递准备'));
    expect(find.text('笔记已保存'), findsOneWidget);

    await tester.tap(find.text('新建笔记').first);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('notes_title_field')),
      '系统设计追问记录',
    );
    await tester.enterText(
      find.byKey(const Key('notes_body_field')),
      '# 系统设计追问记录\n\n- 解释任务状态机和工具幂等。',
    );
    await tester.ensureVisible(find.text('保存').last);
    await tester.tap(find.text('保存').last);
    await tester.pumpAndSettle();

    expect(api.createdNoteTitles.last, '系统设计追问记录');
    expect(api.createdSourceSessionIds.last, 'sess_current_notes');
    expect(find.text('系统设计追问记录'), findsWidgets);
  });
}

class _FakeNotesApi extends ApiService {
  final now = DateTime(2026, 5, 16, 10, 49);
  final createdNoteTitles = <String>[];
  final createdSourceSessionIds = <String>[];
  final updatedNoteBodies = <String>[];

  late final List<NoteView> _notes = [_noteOne, _noteTwo];

  _FakeNotesApi() : super(baseUrl: 'http://localhost');

  CareerRecordMetaView get _meta => CareerRecordMetaView(
        status: 'active',
        sourceSessionId: 'sess_notes',
        sourceArtifactId: 'artifact_notes',
        evidenceRefs: const ['artifact_notes'],
        createdAt: now.subtract(const Duration(days: 5)),
        updatedAt: now,
      );

  CareerApplicationView get _application => CareerApplicationView(
        meta: _meta,
        applicationId: 'application_notes',
        company: '华为',
        position: 'AI Agent 后端工程师',
        location: '深圳',
        jobUrl: '',
        stage: 'interviewing',
        priority: 'high',
        resumeProfileId: 'resume_profile_notes',
        careerProfileId: 'career_profile_notes',
        jdAnalysisId: 'jd_notes',
        jobFitReportId: 'fit_notes',
        resumeVersionIds: const [],
        summary: '面试推进中，需要沉淀复盘和系统设计证据。',
        nextActions: const ['整理面试复盘'],
        risks: const ['系统设计回答还不够结构化'],
        notes: '',
      );

  CareerReadinessView get _readiness => CareerReadinessView(
        score: 78,
        level: 'good',
        recommendation: 'recommended',
        summary: '建议继续沉淀面试复盘。',
        strengths: const ['Agent 项目经验匹配'],
        risks: const ['复盘证据不足'],
        missingMaterials: const [],
        nextActions: const ['整理面试复盘'],
      );

  NoteView get _noteOne => NoteView(
        noteId: 'note_prepare',
        status: 'active',
        sourceSessionId: 'sess_notes',
        sourceArtifactId: null,
        evidenceRefs: const ['application_notes'],
        createdAt: now.subtract(const Duration(days: 2)),
        updatedAt: now,
        title: '投递准备记录',
        bodyMarkdown: '# 投递准备记录\n\n## 面试关注点\n- 补充 RAG 项目证据',
        bodyFormat: 'markdown',
        noteType: 'note',
        origin: 'user',
        collectionId: null,
        tags: const ['面试', '投递'],
        sourceRefs: const [],
        relatedApplicationId: 'application_notes',
        summary: '记录投递前需要补齐的材料。',
      );

  NoteView get _noteTwo => NoteView(
        noteId: 'note_review',
        status: 'active',
        sourceSessionId: 'sess_notes',
        sourceArtifactId: 'artifact_review',
        evidenceRefs: const ['artifact_review'],
        createdAt: now.subtract(const Duration(days: 4)),
        updatedAt: now.subtract(const Duration(hours: 3)),
        title: 'AI Agent 面试复盘',
        bodyMarkdown: '# AI Agent 面试复盘\n\n- 需要解释状态机和工具幂等。',
        bodyFormat: 'markdown',
        noteType: 'learning',
        origin: 'agent',
        collectionId: null,
        tags: const ['系统设计'],
        sourceRefs: [
          NoteSourceRefView(
            sourceType: 'job_fit_report',
            sourceId: 'fit_notes',
            sourceSessionId: 'sess_notes',
            title: '岗位匹配报告',
            quote: '短板集中在工程化案例表达。',
          ),
        ],
        relatedApplicationId: 'application_notes',
        summary: '面试复盘里保留系统设计追问。',
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
          noteCount: _notes.length,
          learningTaskCount: 1,
          updatedAt: now,
        ),
      ],
      activeApplicationId: _application.applicationId,
      counts: CareerWorkbenchCountsView(
        applications: 1,
        activeApplications: 1,
        notes: _notes.length,
        learningTasks: 1,
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
      notes: _notes
          .map(
            (note) => CareerNoteSummaryView(
              noteId: note.noteId,
              title: note.title,
              summary: note.summary,
              status: note.status,
              updatedAt: note.updatedAt,
              noteType: note.noteType,
              origin: note.origin,
              sourceArtifactId: note.sourceArtifactId,
              relatedApplicationId: note.relatedApplicationId,
              tags: note.tags,
            ),
          )
          .toList(),
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
  Future<List<NoteView>> listNotes({
    bool includeArchived = false,
    String? collectionId,
    String? relatedApplicationId,
  }) async {
    return [..._notes]..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
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
    createdSourceSessionIds.add(sourceSessionId);
    final note = NoteView(
      noteId: noteId ?? 'note_created_${createdNoteTitles.length}',
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
      sourceRefs:
          sourceRefs.map((item) => NoteSourceRefView.fromJson(item)).toList(),
      relatedApplicationId: relatedApplicationId,
      summary: summary,
    );
    _notes.insert(0, note);
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
    final index = _notes.indexWhere((note) => note.noteId == noteId);
    final existing = _notes[index];
    final updated = NoteView(
      noteId: existing.noteId,
      status: existing.status,
      sourceSessionId: existing.sourceSessionId,
      sourceArtifactId: existing.sourceArtifactId,
      evidenceRefs: existing.evidenceRefs,
      createdAt: existing.createdAt,
      updatedAt: now.add(const Duration(minutes: 1)),
      title: title ?? existing.title,
      bodyMarkdown: bodyMarkdown ?? existing.bodyMarkdown,
      bodyFormat: bodyFormat ?? existing.bodyFormat,
      noteType: noteType ?? existing.noteType,
      origin: existing.origin,
      collectionId: collectionId ?? existing.collectionId,
      tags: tags ?? existing.tags,
      sourceRefs: existing.sourceRefs,
      relatedApplicationId:
          relatedApplicationId ?? existing.relatedApplicationId,
      summary: summary ?? existing.summary,
    );
    _notes[index] = updated;
    if (bodyMarkdown != null) updatedNoteBodies.add(bodyMarkdown);
    return updated;
  }
}
