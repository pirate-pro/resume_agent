import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/shared/widgets/input_bar.dart';

void main() {
  testWidgets('输入区不常驻展示资料栏，仍可用斜杠激活资料', (tester) async {
    SessionArtifactView? toggledFile;
    bool? toggledActive;
    final now = DateTime(2026, 5, 10, 10, 30);
    final artifacts = [
      _artifact(
        artifactId: 'artifact_resume',
        title: '张明-后端工程师简历.pdf',
        mediaType: 'application/pdf',
        createdAt: now,
      ),
      _artifact(
        artifactId: 'artifact_jd',
        title: '星河智能 JD.txt',
        mediaType: 'text/plain',
        createdAt: now.subtract(const Duration(minutes: 1)),
      ),
      _artifact(
        artifactId: 'artifact_image',
        title: '岗位截图.png',
        mediaType: 'image/png',
        createdAt: now.subtract(const Duration(minutes: 2)),
      ),
    ];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Align(
            alignment: Alignment.bottomCenter,
            child: SizedBox(
              width: 760,
              child: InputBar(
                onSend: (_) async {},
                onUpload: ({
                  required String filename,
                  required Uint8List bytes,
                }) async {},
                onToggleArtifactActive: (file, active) async {
                  toggledFile = file;
                  toggledActive = active;
                },
                onRefreshSkills: () async {},
                onToggleSkill: (_) {},
                onMaxToolRoundsChanged: (_) {},
                onResetRuntimeOptions: () {},
                sessionArtifacts: artifacts,
                activeArtifactIds: const ['artifact_resume', 'artifact_jd'],
                availableSkills: const [],
                selectedSkillNames: const [],
                maxToolRounds: 10,
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('本次任务资料已就绪'), findsNothing);
    expect(find.text('资料已上传，尚未加入本次任务'), findsNothing);
    expect(find.text('已上传 3'), findsNothing);
    expect(find.text('已激活 2'), findsNothing);
    expect(find.text('待激活 1'), findsNothing);
    expect(find.text('张明-后端工程师简历.pdf'), findsNothing);
    expect(find.text('星河智能 JD.txt'), findsNothing);
    expect(find.text('岗位截图.png'), findsNothing);
    expect(find.text('简历 + JD 匹配'), findsNothing);

    await tester.enterText(find.byType(TextField), '/');
    await tester.pumpAndSettle();

    expect(find.text('选择资料或任务'), findsOneWidget);
    expect(find.text('推荐任务'), findsOneWidget);
    expect(find.text('简历 + JD 匹配'), findsOneWidget);
    expect(find.text('岗位截图.png'), findsOneWidget);

    await tester.ensureVisible(find.text('岗位截图.png'));
    await tester.tap(find.text('岗位截图.png'));
    await tester.pumpAndSettle();

    expect(toggledFile?.artifactId, 'artifact_image');
    expect(toggledActive, isTrue);
  });

  testWidgets('斜杠推荐任务会激活相关资料并填入提示词', (tester) async {
    final toggledArtifacts = <String>[];
    final now = DateTime(2026, 5, 10, 10, 30);
    final artifacts = [
      _artifact(
        artifactId: 'artifact_resume',
        title: '张明-后端工程师简历.pdf',
        mediaType: 'application/pdf',
        createdAt: now,
      ),
      _artifact(
        artifactId: 'artifact_jd',
        title: '星河智能 JD.txt',
        mediaType: 'text/plain',
        createdAt: now.subtract(const Duration(minutes: 1)),
      ),
    ];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Align(
            alignment: Alignment.bottomCenter,
            child: SizedBox(
              width: 760,
              child: InputBar(
                onSend: (_) async {},
                onUpload: ({
                  required String filename,
                  required Uint8List bytes,
                }) async {},
                onToggleArtifactActive: (file, active) async {
                  if (active) {
                    toggledArtifacts.add(file.artifactId);
                  }
                },
                onRefreshSkills: () async {},
                onToggleSkill: (_) {},
                onMaxToolRoundsChanged: (_) {},
                onResetRuntimeOptions: () {},
                sessionArtifacts: artifacts,
                activeArtifactIds: const [],
                availableSkills: const [],
                selectedSkillNames: const [],
                maxToolRounds: 10,
              ),
            ),
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '/');
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('简历 + JD 匹配'));
    await tester.tap(find.text('简历 + JD 匹配'));
    await tester.pumpAndSettle();

    expect(toggledArtifacts, containsAll(['artifact_resume', 'artifact_jd']));
    final textField = tester.widget<TextField>(find.byType(TextField));
    expect(textField.controller?.text, contains('多 Agent 协作'));
    expect(textField.controller?.text, contains('匹配报告'));
  });

  testWidgets('发送时展示处理中状态并恢复可输入', (tester) async {
    final sendCompleter = Completer<void>();
    var sendCount = 0;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Align(
            alignment: Alignment.bottomCenter,
            child: SizedBox(
              width: 760,
              child: InputBar(
                onSend: (_) async {
                  sendCount += 1;
                  await sendCompleter.future;
                },
                onUpload: ({
                  required String filename,
                  required Uint8List bytes,
                }) async {},
                onToggleArtifactActive: (_, __) async {},
                onRefreshSkills: () async {},
                onToggleSkill: (_) {},
                onMaxToolRoundsChanged: (_) {},
                onResetRuntimeOptions: () {},
                sessionArtifacts: const [],
                activeArtifactIds: const [],
                availableSkills: const [],
                selectedSkillNames: const [],
                maxToolRounds: 10,
              ),
            ),
          ),
        ),
      ),
    );

    await tester.enterText(find.byType(TextField), '请诊断这份简历');
    await tester.pump();
    await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
    await tester.pump();

    expect(sendCount, 1);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    expect(find.text('请诊断这份简历'), findsNothing);

    sendCompleter.complete();
    await tester.pumpAndSettle();

    expect(find.byType(CircularProgressIndicator), findsNothing);
  });
}

SessionArtifactView _artifact({
  required String artifactId,
  required String title,
  required String mediaType,
  required DateTime createdAt,
}) {
  return SessionArtifactView(
    artifactId: artifactId,
    title: title,
    kind: 'upload',
    mediaType: mediaType,
    sizeBytes: 2048,
    status: 'ready',
    visibility: 'user',
    createdAt: createdAt,
    updatedAt: createdAt,
  );
}
