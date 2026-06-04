import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../career_workbench/career_workbench_provider.dart';
import 'workspace_models.dart';
import 'workspace_nav.dart';
import 'workspace_top_bar.dart';

class ProductWorkspaceShell extends ConsumerStatefulWidget {
  final WorkspacePage activePage;
  final WorkspaceBadges badges;
  final bool serverReachable;
  final Widget child;
  final ValueChanged<WorkspacePage> onPageChanged;
  final VoidCallback onNewSession;
  final VoidCallback onOpenChat;
  final VoidCallback onOpenSessionHistory;
  final ValueChanged<String> onCommandSubmitted;

  const ProductWorkspaceShell({
    super.key,
    required this.activePage,
    required this.badges,
    required this.serverReachable,
    required this.child,
    required this.onPageChanged,
    required this.onNewSession,
    required this.onOpenChat,
    required this.onOpenSessionHistory,
    required this.onCommandSubmitted,
  });

  @override
  ConsumerState<ProductWorkspaceShell> createState() =>
      _ProductWorkspaceShellState();
}

class _ProductWorkspaceShellState extends ConsumerState<ProductWorkspaceShell> {
  void _openMobileNav(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) {
        final height = MediaQuery.sizeOf(sheetContext).height;
        return Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(20),
            child: SizedBox(
              height: (height * 0.86).clamp(520.0, 760.0),
              child: ProductSidebar(
                activePage: widget.activePage,
                badges: widget.badges,
                compact: true,
                onPageChanged: (page) {
                  Navigator.of(sheetContext).pop();
                  widget.onPageChanged(page);
                },
                onNewSession: () {
                  Navigator.of(sheetContext).pop();
                  widget.onNewSession();
                },
                onOpenChat: () {
                  Navigator.of(sheetContext).pop();
                  widget.onOpenChat();
                },
              ),
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final workbench = ref.watch(careerWorkbenchProvider);
    final action = workbench.activeAction;
    final showActionBanner = action != null &&
        widget.activePage != WorkspacePage.projects &&
        widget.activePage != WorkspacePage.jdMatch;
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final desktop = width >= ProductBreakpoints.shellDesktop;
        return Material(
          color: ProductColors.canvas,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (desktop)
                ProductSidebar(
                  activePage: widget.activePage,
                  badges: widget.badges,
                  onPageChanged: widget.onPageChanged,
                  onNewSession: widget.onNewSession,
                  onOpenChat: widget.onOpenChat,
                ),
              Expanded(
                child: Column(
                  children: [
                    WorkspaceTopBar(
                      activePage: widget.activePage,
                      showMenu: !desktop,
                      serverReachable: widget.serverReachable,
                      onMenuTap: () => _openMobileNav(context),
                      onNewSession: widget.onNewSession,
                      onOpenSessionHistory: widget.onOpenSessionHistory,
                      onOpenWorkbench: () =>
                          widget.onPageChanged(WorkspacePage.projects),
                      onCommandSubmitted: widget.onCommandSubmitted,
                    ),
                    if (showActionBanner) ...[
                      Padding(
                        padding: EdgeInsets.fromLTRB(
                          desktop ? 24 : 14,
                          0,
                          desktop ? 24 : 14,
                          12,
                        ),
                        child: _WorkspaceActionBanner(
                          provider: workbench,
                          action: action,
                          onOpenTarget: () {
                            unawaited(workbench.focusActiveActionTarget());
                            widget.onPageChanged(WorkspacePage.projects);
                          },
                        ),
                      ),
                    ],
                    Expanded(
                      child: Padding(
                        padding: EdgeInsets.fromLTRB(
                          desktop ? 24 : 14,
                          0,
                          desktop ? 24 : 14,
                          desktop ? 24 : 14,
                        ),
                        child: widget.child,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _WorkspaceActionBanner extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerWorkbenchActionRun action;
  final VoidCallback onOpenTarget;

  const _WorkspaceActionBanner({
    required this.provider,
    required this.action,
    required this.onOpenTarget,
  });

  @override
  Widget build(BuildContext context) {
    final color = switch (action.state) {
      CareerWorkbenchActionState.running => ProductColors.primary,
      CareerWorkbenchActionState.completed => ProductColors.primary,
      CareerWorkbenchActionState.failed => ProductColors.danger,
    };
    final icon = switch (action.state) {
      CareerWorkbenchActionState.running => Icons.auto_awesome_rounded,
      CareerWorkbenchActionState.completed => Icons.check_rounded,
      CareerWorkbenchActionState.failed => Icons.error_outline_rounded,
    };
    final title = switch (action.state) {
      CareerWorkbenchActionState.running => '正在生成：${action.request.label}',
      CareerWorkbenchActionState.completed => '已完成：${action.request.label}',
      CareerWorkbenchActionState.failed => '生成失败：${action.request.label}',
    };
    final subtitle = switch (action.state) {
      CareerWorkbenchActionState.running => 'Agent 正在当前页面后台执行，完成后会刷新相关资产。',
      CareerWorkbenchActionState.completed => action.resultHints.isEmpty
          ? '工作台和求职资产已刷新。'
          : action.resultHints.join(' · '),
      CareerWorkbenchActionState.failed =>
        action.error?.trim().isNotEmpty == true
            ? action.error!.trim()
            : '执行未完成，请稍后重试。',
    };

    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.075),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.18)),
      ),
      child: Row(
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(12),
            ),
            child: action.isRunning
                ? Padding(
                    padding: const EdgeInsets.all(8),
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: color,
                    ),
                  )
                : Icon(icon, size: 17, color: color),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.4,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11,
                    height: 1.35,
                    color: ProductColors.textSecondary,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          if (action.state == CareerWorkbenchActionState.completed) ...[
            TextButton(
              onPressed: onOpenTarget,
              child: const Text('查看项目'),
            ),
            IconButton(
              tooltip: '关闭',
              onPressed: provider.clearAction,
              icon: const Icon(Icons.close_rounded),
            ),
          ] else if (action.state != CareerWorkbenchActionState.running)
            IconButton(
              tooltip: '关闭',
              onPressed: provider.clearAction,
              icon: const Icon(Icons.close_rounded),
            ),
        ],
      ),
    );
  }
}
