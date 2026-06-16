import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/features/workspace/workspace_models.dart';
import 'package:resume_agent_app/features/workspace/workspace_shell.dart';

void main() {
  testWidgets('产品工作台 shell 展示导航、顶部搜索并支持切换页面', (tester) async {
    tester.view.physicalSize = const Size(1280, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    var activePage = WorkspacePage.dashboard;
    var openedHistory = false;

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          home: StatefulBuilder(
            builder: (context, setState) {
              return ProductWorkspaceShell(
                activePage: activePage,
                badges: const WorkspaceBadges(
                  applications: 3,
                  resumes: 2,
                  jdMatches: 1,
                  learningTasks: 4,
                  notes: 5,
                ),
                serverReachable: true,
                onPageChanged: (page) => setState(() => activePage = page),
                onNewSession: () {},
                onOpenChat: () =>
                    setState(() => activePage = WorkspacePage.chat),
                onOpenSessionHistory: () => openedHistory = true,
                onCommandSubmitted: (_) {},
                child: const Center(child: Text('workspace content')),
              );
            },
          ),
        ),
      ),
    );

    expect(find.text('求职 Agent'), findsOneWidget);
    expect(find.text('你的智能求职伙伴'), findsOneWidget);
    expect(find.text('总览'), findsWidgets);
    expect(find.text('Agent 助手'), findsWidgets);
    expect(find.text('求职项目'), findsOneWidget);
    expect(find.text('workspace content'), findsOneWidget);
    expect(find.text('搜索项目、岗位、笔记，或输入命令（如：分析 JD 匹配度）'), findsOneWidget);

    await tester.tap(find.text('会话历史'));
    await tester.pump();

    expect(openedHistory, isTrue);

    await tester.tap(find.text('JD 匹配'));
    await tester.pumpAndSettle();

    expect(activePage, WorkspacePage.jdMatch);
    expect(find.text('分析岗位要求、匹配度和差距'), findsOneWidget);
  });
}
