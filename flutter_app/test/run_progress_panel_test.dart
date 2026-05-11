import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/shared/widgets/run_progress_panel.dart';

void main() {
  testWidgets('多 Agent 进度卡展示业务名称和进度摘要', (tester) async {
    final now = DateTime(2026, 5, 9, 16, 20);
    final events = [
      _event(
        type: 'agent_task_group_created',
        createdAt: now,
        payload: {
          'status': 'running',
          'tasks': [
            {
              'task_id': 'task_resume',
              'target_agent_id': 'resume_agent',
              'status': 'queued',
              'title': '解析简历',
              'detail': '读取已激活的简历 artifact',
              'artifact_refs': ['artifact_resume_source_123456789'],
            },
            {
              'task_id': 'task_job',
              'target_agent_id': 'job_agent',
              'status': 'queued',
              'title': '分析 JD',
              'detail': '生成 JD 分析和匹配报告',
              'artifact_refs': ['artifact_jd_source_987654321'],
            },
          ],
        },
      ),
      _event(
        type: 'agent_task_completed',
        createdAt: now.add(const Duration(seconds: 5)),
        payload: {
          'task_id': 'task_resume',
          'target_agent_id': 'resume_agent',
          'status': 'completed',
          'title': '解析简历',
          'detail': '已创建简历画像',
          'product_refs': ['resume_profile_zhangming_003'],
        },
      ),
      _event(
        type: 'agent_task_started',
        createdAt: now.add(const Duration(seconds: 7)),
        payload: {
          'task_id': 'task_job',
          'target_agent_id': 'job_agent',
          'status': 'running',
          'title': '分析 JD',
          'detail': '正在生成匹配报告',
          'stage': 'tool_call',
          'phase': 'job_fit',
          'step_index': 4,
          'total_steps': 7,
          'current_action': '正在计算岗位匹配信号',
          'next_action': '生成风险和建议',
        },
      ),
      _event(
        type: 'tool_call',
        createdAt: now.add(const Duration(seconds: 8)),
        payload: {
          'tool_call_id': 'call_fit_save',
          'name': 'career_job_fit_report_save',
          'arguments': {'job_fit_report_id': 'fit_demo'},
        },
      ),
      _event(
        type: 'tool_result',
        createdAt: now.add(const Duration(seconds: 9)),
        payload: {
          'tool_call_id': 'call_fit_save',
          'tool_name': 'career_job_fit_report_save',
          'success': true,
          'summary': '匹配报告已写入求职资产',
        },
      ),
    ];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: SizedBox(
              width: 720,
              child: RunProgressPanel(events: events),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('多 Agent 协作执行中'), findsOneWidget);
    expect(find.textContaining('%'), findsOneWidget);
    expect(find.text('执行阶段'), findsOneWidget);
    expect(find.text('读取资料'), findsOneWidget);
    expect(find.text('简历诊断'), findsOneWidget);
    expect(find.text('岗位匹配'), findsOneWidget);
    expect(find.text('报告生成'), findsOneWidget);
    expect(find.text('资产同步'), findsOneWidget);
    expect(find.text('当前处理'), findsOneWidget);
    expect(find.text('实时动态'), findsOneWidget);
    expect(find.text('最近操作'), findsOneWidget);
    expect(find.text('已产出'), findsOneWidget);
    expect(find.text('1 个产品记录 · 2 个文件引用'), findsOneWidget);
    expect(find.text('Agent 流程'), findsOneWidget);
    expect(find.text('2 个协作者'), findsOneWidget);
    expect(find.text('4/7'), findsOneWidget);
    expect(find.text('简历分析 Agent'), findsWidgets);
    expect(find.text('岗位匹配 Agent'), findsWidgets);
    expect(find.textContaining('正在计算岗位匹配信号'), findsWidgets);
    expect(find.textContaining('下一步：生成风险和建议'), findsWidgets);
    expect(find.text('执行动态'), findsOneWidget);
    expect(find.text('保存岗位匹配报告'), findsOneWidget);
    expect(find.text('模型规划、工具执行和结果整理'), findsOneWidget);
    expect(find.text('匹配报告已写入求职资产'), findsOneWidget);
    expect(find.text('1 秒'), findsOneWidget);
    expect(find.textContaining('调用：保存岗位匹配报告'), findsNothing);
    expect(find.textContaining('完成：保存岗位匹配报告'), findsNothing);
    expect(find.textContaining('career_job_fit_report_save'), findsNothing);
    expect(find.textContaining('resume_agent'), findsNothing);
    expect(
        find.textContaining('artifact_resume_source_123456789'), findsNothing);
    expect(find.textContaining('简历画像 003'), findsWidgets);
    expect(find.textContaining('文件 23456789'), findsWidgets);
  });

  testWidgets('没有子 Agent 事件时仍保留执行明细', (tester) async {
    final now = DateTime(2026, 5, 9, 17, 10);
    final events = [
      _event(
        type: 'run_started',
        createdAt: now,
        payload: {},
      ),
      _event(
        type: 'tool_call',
        createdAt: now.add(const Duration(seconds: 1)),
        payload: {
          'tool_call_id': 'call_read_artifact',
          'name': 'session_read_artifact',
          'arguments': {'artifact_id': 'artifact_demo'},
        },
      ),
      _event(
        type: 'run_finished',
        createdAt: now.add(const Duration(seconds: 4)),
        payload: {},
      ),
    ];

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: SizedBox(
              width: 720,
              child: RunProgressPanel(events: events),
            ),
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('执行动态'), findsNothing);
    expect(find.textContaining('3 条执行动态'), findsOneWidget);
    expect(find.text('执行阶段'), findsOneWidget);
    expect(find.text('接收请求'), findsOneWidget);
    expect(find.text('执行工具'), findsOneWidget);
    expect(find.text('输出结果'), findsOneWidget);
    expect(find.text('已完成'), findsWidgets);
    expect(find.text('执行完成'), findsOneWidget);
    await tester.tap(find.text('多 Agent 协作已完成'));
    await tester.pumpAndSettle();
    expect(find.text('执行动态'), findsOneWidget);
    expect(find.text('读取文件内容'), findsOneWidget);
    expect(find.text('3 秒'), findsOneWidget);
    expect(find.textContaining('调用：读取文件内容'), findsNothing);
    expect(find.textContaining('session_read_artifact'), findsNothing);
  });
}

EventView _event({
  required String type,
  required DateTime createdAt,
  required Map<String, dynamic> payload,
}) {
  return EventView(
    eventId: 'evt_${type}_${createdAt.millisecondsSinceEpoch}',
    sessionId: 'sess_test',
    agentId: 'agent_main',
    runId: 'run_test',
    eventVersion: 1,
    type: type,
    payload: payload,
    createdAt: createdAt,
  );
}
