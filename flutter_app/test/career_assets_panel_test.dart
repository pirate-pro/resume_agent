import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
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
    expect(find.textContaining('匹配度较高'), findsOneWidget);
    expect(find.textContaining('复核定制简历'), findsOneWidget);

    await tester.tap(find.text('预览报告'));
    await tester.pump();
    expect(previewedArtifactId, 'artifact_fit_report_001');
  });
}
