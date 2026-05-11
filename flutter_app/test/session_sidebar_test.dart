import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/shared/widgets/session_sidebar.dart';

void main() {
  testWidgets('会话列表按置顶和最近分组且不显示猜测标签', (tester) async {
    final now = DateTime(2026, 5, 10, 12, 0);
    final sessions = [
      _session(
        id: 'sess_pinned',
        title: '多Agent协作求职岗位匹配',
        updatedAt: now,
        isPinned: true,
        messageCount: 8,
      ),
      _session(
        id: 'sess_resume',
        title: '简历诊断与报告生成',
        updatedAt: now.subtract(const Duration(hours: 2)),
        messageCount: 6,
      ),
      _session(
        id: 'sess_intro',
        title: '智能体自我介绍',
        updatedAt: now.subtract(const Duration(days: 1)),
        messageCount: 2,
      ),
    ];
    String? tappedSessionId;

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SizedBox(
            width: 320,
            height: 640,
            child: SessionSidebar(
              sessions: sessions,
              activeSessionId: 'sess_resume',
              onSessionTap: (id) => tappedSessionId = id,
              onSessionDelete: (_) {},
              onSessionRename: (_, __) async => true,
              onSessionPinToggle: (_, __) async => true,
              onNewSession: () {},
              onToggleCollapse: () {},
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('置顶'), findsOneWidget);
    expect(find.text('最近'), findsOneWidget);
    expect(find.text('协作任务'), findsNothing);
    expect(find.text('简历诊断'), findsNothing);
    expect(find.text('资料问答'), findsNothing);
    expect(find.text('8 条'), findsOneWidget);
    expect(find.text('3 个会话 · 1 个置顶'), findsOneWidget);

    await tester.tap(find.text('简历诊断与报告生成'));
    expect(tappedSessionId, 'sess_resume');
  });
}

SessionMeta _session({
  required String id,
  required String title,
  required DateTime updatedAt,
  bool isPinned = false,
  int messageCount = 0,
}) {
  return SessionMeta(
    id: id,
    title: title,
    createdAt: updatedAt.subtract(const Duration(days: 1)),
    updatedAt: updatedAt,
    isPinned: isPinned,
    messageCount: messageCount,
  );
}
