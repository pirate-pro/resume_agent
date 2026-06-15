import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/shared/widgets/workflow_interrupt_panel.dart';

void main() {
  test("workflow interrupt parses durable resume identity", () {
    final interrupt = WorkflowInterruptView.fromJson({
      "workflow_instance_id": "wf_test",
      "workflow_version": 3,
      "type": "source_selection",
      "question": "选择来源",
    });

    expect(interrupt.isValid, isTrue);
    expect(interrupt.workflowInstanceId, "wf_test");
    expect(interrupt.workflowVersion, 3);
  });

  testWidgets("source selection submits selected refs and supplement",
      (tester) async {
    Map<String, dynamic>? submitted;
    await tester.pumpWidget(
      _host(
        WorkflowInterruptPanel(
          interrupt: WorkflowInterruptView.fromJson({
            "workflow_instance_id": "wf_note",
            "workflow_version": 2,
            "type": "source_selection",
            "question": "选择用于生成笔记的来源",
            "candidates": [
              {
                "title": "岗位匹配报告",
                "snippet": "匹配度 82 分",
                "source_ref": {
                  "source_type": "job_fit_report",
                  "source_id": "fit_001",
                },
              },
            ],
          }),
          isSubmitting: false,
          onSubmit: (payload) async => submitted = payload,
        ),
      ),
    );

    await tester.enterText(
      find.byKey(const Key("workflow-user-supplement")),
      "重点关注 RAG 评估",
    );
    await tester.tap(find.byKey(const Key("workflow-continue")));
    await tester.pump();

    expect(submitted?["user_supplement"], "重点关注 RAG 评估");
    expect(
      (submitted?["selected_source_refs"] as List).single,
      {
        "source_type": "job_fit_report",
        "source_id": "fit_001",
      },
    );
  });

  testWidgets("note review submits edited draft", (tester) async {
    Map<String, dynamic>? submitted;
    await tester.pumpWidget(
      _host(
        WorkflowInterruptPanel(
          interrupt: WorkflowInterruptView.fromJson({
            "workflow_instance_id": "wf_note",
            "workflow_version": 4,
            "type": "note_review",
            "question": "确认笔记草稿",
            "draft": {
              "title": "原标题",
              "body_markdown": "原正文",
              "summary": "原摘要",
              "tags": ["面试"],
            },
          }),
          isSubmitting: false,
          onSubmit: (payload) async => submitted = payload,
        ),
      ),
    );

    await tester.enterText(
      find.byKey(const Key("workflow-note-title")),
      "修改后的标题",
    );
    await tester.ensureVisible(find.byKey(const Key("workflow-approve")));
    await tester.tap(find.byKey(const Key("workflow-approve")));
    await tester.pump();

    expect(submitted?["action"], "edit");
    expect(
      (submitted?["edited_draft"] as Map)["title"],
      "修改后的标题",
    );
  });

  testWidgets("interview scope submits application update contract",
      (tester) async {
    Map<String, dynamic>? submitted;
    await tester.pumpWidget(
      _host(
        WorkflowInterruptPanel(
          interrupt: WorkflowInterruptView.fromJson({
            "workflow_instance_id": "wf_review",
            "workflow_version": 1,
            "type": "interview_review_scope",
            "question": "确认复盘范围",
            "application_candidates": [
              {
                "application_id": "application_001",
                "title": "星河智能 AI 应用开发",
              },
            ],
          }),
          isSubmitting: false,
          onSubmit: (payload) async => submitted = payload,
        ),
      ),
    );

    await tester.ensureVisible(find.byKey(const Key("workflow-continue")));
    await tester.tap(find.byKey(const Key("workflow-continue")));
    await tester.pump();

    expect(submitted?["selected_application_id"], "application_001");
    expect(submitted?["save_note"], isTrue);
    expect(submitted?["update_application"], isTrue);
    expect(
      submitted?["update_fields"],
      ["stage", "risks", "next_actions", "notes"],
    );
  });

  testWidgets("interview confirmation can cancel without writes",
      (tester) async {
    Map<String, dynamic>? submitted;
    await tester.pumpWidget(
      _host(
        WorkflowInterruptPanel(
          interrupt: WorkflowInterruptView.fromJson({
            "workflow_instance_id": "wf_review",
            "workflow_version": 2,
            "type": "interview_review_confirmation",
            "question": "确认复盘写入",
            "note_draft": {
              "title": "一面复盘",
              "body_markdown": "正文",
            },
            "application_update_preview": {
              "notes": "更新项目备注",
            },
          }),
          isSubmitting: false,
          onSubmit: (payload) async => submitted = payload,
        ),
      ),
    );

    await tester.ensureVisible(find.byKey(const Key("workflow-cancel")));
    await tester.tap(find.byKey(const Key("workflow-cancel")));
    await tester.pump();

    expect(submitted, {"action": "cancel"});
  });

  testWidgets("write failure exposes retry action", (tester) async {
    Map<String, dynamic>? submitted;
    await tester.pumpWidget(
      _host(
        WorkflowInterruptPanel(
          interrupt: WorkflowInterruptView.fromJson({
            "workflow_instance_id": "wf_retry",
            "workflow_version": 6,
            "type": "workflow_write_retry",
            "question": "笔记保存失败。你可以重试写入，或取消本次保存。",
            "error": "temporary note write failure",
            "retry_count": 2,
          }),
          isSubmitting: false,
          onSubmit: (payload) async => submitted = payload,
        ),
      ),
    );

    expect(find.textContaining("已尝试 2 次"), findsOneWidget);
    await tester.tap(find.byKey(const Key("workflow-retry")));
    await tester.pump();

    expect(submitted, {"action": "retry"});
  });
}

Widget _host(Widget child) {
  return MaterialApp(
    home: Scaffold(
      body: Align(
        alignment: Alignment.bottomCenter,
        child: SizedBox(width: 390, child: child),
      ),
    ),
  );
}
