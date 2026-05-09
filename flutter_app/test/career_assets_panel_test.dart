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
    expect(find.text('当前诊断'), findsOneWidget);
    expect(find.text('可预览'), findsOneWidget);
    expect(find.text('详情'), findsOneWidget);
    expect(find.text('预览诊断'), findsOneWidget);
    expect(find.text('历史 3'), findsOneWidget);

    await tester.tap(find.text('详情'));
    expect(detailsOpened, isTrue);

    await tester.tap(find.text('预览诊断'));
    await tester.pump();
    expect(previewedArtifactId, 'artifact_diagnosis_001');

    await tester.tap(find.text('历史 3'));
    expect(historyOpened, isTrue);
  });
}
