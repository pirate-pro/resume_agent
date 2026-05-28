import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../career_ui/career_ui_helpers.dart';
import '../career_workbench/career_workbench_provider.dart';
import '../chat/chat_screen.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_nav.dart';

const double _chatSidebarWidth = 284;
const double _contextRailWidth = 344;
const double _desktopBreakpoint = 1180;
const double _tabletBreakpoint = 760;

class AgentChatWorkspace extends ConsumerStatefulWidget {
  final WorkspaceBadges badges;
  final ValueChanged<WorkspacePage> onPageChanged;
  final VoidCallback onNewSession;
  final CareerPromptSender? onSendPrompt;

  const AgentChatWorkspace({
    super.key,
    required this.badges,
    required this.onPageChanged,
    required this.onNewSession,
    this.onSendPrompt,
  });

  @override
  ConsumerState<AgentChatWorkspace> createState() => _AgentChatWorkspaceState();
}

class _AgentChatWorkspaceState extends ConsumerState<AgentChatWorkspace> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() {
      ref.read(chatProvider).refreshSessions();
      ref.read(careerWorkbenchProvider).ensureLoaded();
    });
  }

  void _openSessionDrawer(BuildContext context) {
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
            borderRadius: BorderRadius.circular(22),
            child: SizedBox(
              height: math.min(height * 0.9, 780),
              child: _SidebarHost(
                badges: widget.badges,
                onPageChanged: (page) {
                  Navigator.of(sheetContext).pop();
                  widget.onPageChanged(page);
                },
                onNewSession: () {
                  Navigator.of(sheetContext).pop();
                  widget.onNewSession();
                },
              ),
            ),
          ),
        );
      },
    );
  }

  void _openContextSheet(BuildContext context) {
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
            borderRadius: BorderRadius.circular(22),
            child: SizedBox(
              height: math.min(height * 0.82, 720),
              child: _ContextRail(onSendPrompt: widget.onSendPrompt),
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final desktop = width >= _desktopBreakpoint;
        final tablet = width >= _tabletBreakpoint && !desktop;
        return Material(
          color: ProductColors.canvas,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (desktop)
                SizedBox(
                  width: _chatSidebarWidth,
                  child: _SidebarHost(
                    badges: widget.badges,
                    onPageChanged: widget.onPageChanged,
                    onNewSession: widget.onNewSession,
                  ),
                ),
              Expanded(
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: ChatScreen(
                        showSidebarToggle: !desktop,
                        onSidebarToggle: () => _openSessionDrawer(context),
                        showWorkbenchToggle: tablet,
                        onWorkbenchToggle: () =>
                            widget.onPageChanged(WorkspacePage.projects),
                        showCareerAssetsToggle: false,
                        showDebugToggle: false,
                      ),
                    ),
                    if (!desktop)
                      Positioned(
                        right: 14,
                        top: tablet ? 74 : 88,
                        child: _FloatingContextButton(
                          onTap: () => _openContextSheet(context),
                        ),
                      ),
                  ],
                ),
              ),
              if (desktop)
                SizedBox(
                  width: _contextRailWidth,
                  child: _ContextRail(onSendPrompt: widget.onSendPrompt),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _SidebarHost extends ConsumerWidget {
  final WorkspaceBadges badges;
  final ValueChanged<WorkspacePage> onPageChanged;
  final VoidCallback onNewSession;

  const _SidebarHost({
    required this.badges,
    required this.onPageChanged,
    required this.onNewSession,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(chatProvider);
    final workbench = ref.watch(careerWorkbenchProvider);
    return _AgentChatSidebar(
      sessions: chat.sessions,
      activeSessionId: chat.sessionId,
      badges: badges,
      serverReachable: chat.serverReachable,
      applications: workbench.applications,
      onPageChanged: onPageChanged,
      onNewSession: onNewSession,
      onSessionTap: (sessionId) =>
          unawaited(ref.read(chatProvider).switchSession(sessionId)),
      onSessionDelete: (sessionId) =>
          unawaited(ref.read(chatProvider).deleteSession(sessionId)),
      onSessionRename: (sessionId, title) =>
          ref.read(chatProvider).renameSession(sessionId, title),
      onSessionPinToggle: (sessionId, isPinned) =>
          ref.read(chatProvider).setSessionPinned(sessionId, isPinned),
    );
  }
}

class _AgentChatSidebar extends StatelessWidget {
  final List<SessionMeta> sessions;
  final String? activeSessionId;
  final WorkspaceBadges badges;
  final bool serverReachable;
  final List<CareerApplicationSummaryView> applications;
  final ValueChanged<WorkspacePage> onPageChanged;
  final VoidCallback onNewSession;
  final ValueChanged<String> onSessionTap;
  final ValueChanged<String> onSessionDelete;
  final Future<bool> Function(String, String) onSessionRename;
  final Future<bool> Function(String, bool) onSessionPinToggle;

  const _AgentChatSidebar({
    required this.sessions,
    required this.activeSessionId,
    required this.badges,
    required this.serverReachable,
    required this.applications,
    required this.onPageChanged,
    required this.onNewSession,
    required this.onSessionTap,
    required this.onSessionDelete,
    required this.onSessionRename,
    required this.onSessionPinToggle,
  });

  @override
  Widget build(BuildContext context) {
    final pages = [
      WorkspacePage.dashboard,
      WorkspacePage.projects,
      WorkspacePage.resumes,
      WorkspacePage.jdMatch,
      WorkspacePage.learning,
      WorkspacePage.notes,
    ];
    final recentSessions = sessions.take(6).toList();
    return Container(
      decoration: const BoxDecoration(
        color: ProductColors.surface,
        border: Border(right: BorderSide(color: ProductColors.border)),
      ),
      child: SafeArea(
        right: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 18, 16, 10),
              child: _BrandHeader(serverReachable: serverReachable),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
              child: _NewSessionButton(onTap: onNewSession),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 16),
                children: [
                  for (final page in pages) ...[
                    ProductNavItem(
                      page: page,
                      selected: false,
                      count: workspacePageBadge(page, badges),
                      onTap: () => onPageChanged(page),
                    ),
                    const SizedBox(height: 7),
                  ],
                  const SizedBox(height: 16),
                  _SidebarSectionHeader(
                    title: '快捷入口',
                    trailing: '${applications.length} 个项目',
                  ),
                  const SizedBox(height: 10),
                  _QuickGrid(onPageChanged: onPageChanged),
                  const SizedBox(height: 18),
                  _SidebarSectionHeader(
                    title: '最近会话',
                    trailing: sessions.isEmpty ? '暂无' : '更多 >',
                  ),
                  const SizedBox(height: 8),
                  if (recentSessions.isEmpty)
                    const _SidebarEmptyHint(message: '还没有历史会话')
                  else
                    for (final session in recentSessions) ...[
                      _RecentSessionTile(
                        session: session,
                        active: session.id == activeSessionId,
                        onTap: () => onSessionTap(session.id),
                        onDelete: () => onSessionDelete(session.id),
                        onRename: (title) => onSessionRename(session.id, title),
                        onPinToggle: (isPinned) =>
                            onSessionPinToggle(session.id, isPinned),
                      ),
                      const SizedBox(height: 6),
                    ],
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
              child: _AssistantStatus(serverReachable: serverReachable),
            ),
          ],
        ),
      ),
    );
  }
}

class _BrandHeader extends StatelessWidget {
  final bool serverReachable;

  const _BrandHeader({required this.serverReachable});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            gradient: const LinearGradient(
              colors: [ProductColors.primary, Color(0xFF059669)],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            borderRadius: BorderRadius.circular(16),
            boxShadow: [
              BoxShadow(
                color: ProductColors.primary.withValues(alpha: 0.22),
                blurRadius: 18,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: const Icon(
            Icons.auto_awesome_rounded,
            size: 22,
            color: Colors.white,
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '求职 Agent',
                style: AppTheme.ts(
                  fontSize: 16,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 3),
              Row(
                children: [
                  Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: serverReachable
                          ? ProductColors.primary
                          : ProductColors.danger,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      serverReachable ? '你的智能求职伙伴' : '服务连接异常',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.2,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _NewSessionButton extends StatelessWidget {
  final VoidCallback onTap;

  const _NewSessionButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 44,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: ProductColors.primary,
          foregroundColor: Colors.white,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.add_rounded, size: 18),
            const SizedBox(width: 7),
            Text(
              '新建会话',
              style: AppTheme.ts(
                fontSize: 13,
                fontWeight: FontWeight.w900,
                color: Colors.white,
              ),
            ),
            const Spacer(),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.16),
                borderRadius: BorderRadius.circular(7),
              ),
              child: Text(
                '⌘ K',
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w900,
                  color: Colors.white,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _QuickGrid extends StatelessWidget {
  final ValueChanged<WorkspacePage> onPageChanged;

  const _QuickGrid({required this.onPageChanged});

  @override
  Widget build(BuildContext context) {
    return GridView.count(
      crossAxisCount: 2,
      mainAxisSpacing: 8,
      crossAxisSpacing: 8,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      childAspectRatio: 2.1,
      children: [
        _QuickTile(
          icon: Icons.description_outlined,
          title: '生成简历',
          subtitle: 'AI 优化',
          onTap: () => onPageChanged(WorkspacePage.resumes),
        ),
        _QuickTile(
          icon: Icons.link_rounded,
          title: 'JD 分析',
          subtitle: '拆解岗位',
          onTap: () => onPageChanged(WorkspacePage.jdMatch),
        ),
        _QuickTile(
          icon: Icons.chat_bubble_outline_rounded,
          title: '面试准备',
          subtitle: '题库方案',
          onTap: () => onPageChanged(WorkspacePage.learning),
        ),
        _QuickTile(
          icon: Icons.auto_awesome_rounded,
          title: 'Agent 助手',
          subtitle: '专家求职顾问',
          onTap: () => onPageChanged(WorkspacePage.chat),
        ),
      ],
    );
  }
}

class _QuickTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  const _QuickTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: ProductColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: ProductColors.border),
          ),
          child: Row(
            children: [
              Icon(icon, size: 16, color: ProductColors.primary),
              const SizedBox(width: 7),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 9.6,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _RecentSessionTile extends StatelessWidget {
  final SessionMeta session;
  final bool active;
  final VoidCallback onTap;
  final VoidCallback onDelete;
  final Future<bool> Function(String) onRename;
  final Future<bool> Function(bool) onPinToggle;

  const _RecentSessionTile({
    required this.session,
    required this.active,
    required this.onTap,
    required this.onDelete,
    required this.onRename,
    required this.onPinToggle,
  });

  @override
  Widget build(BuildContext context) {
    final color = active ? ProductColors.primary : ProductColors.textSecondary;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          height: 38,
          padding: const EdgeInsets.only(left: 10, right: 4),
          decoration: BoxDecoration(
            color: active ? ProductColors.primarySoft : Colors.transparent,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: active
                  ? ProductColors.primary.withValues(alpha: 0.14)
                  : Colors.transparent,
            ),
          ),
          child: Row(
            children: [
              Icon(
                session.isPinned
                    ? Icons.push_pin_outlined
                    : Icons.chat_bubble_outline_rounded,
                size: 14,
                color: color,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  session.title.trim().isEmpty ? '新会话' : session.title.trim(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: active ? FontWeight.w900 : FontWeight.w700,
                    color: color,
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Text(
                _sessionTime(session.updatedAt),
                style: AppTheme.ts(
                  fontSize: 10.2,
                  color:
                      active ? ProductColors.primary : ProductColors.textMuted,
                ),
              ),
              _SessionMenu(
                session: session,
                onDelete: onDelete,
                onRename: onRename,
                onPinToggle: onPinToggle,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SessionMenu extends StatelessWidget {
  final SessionMeta session;
  final VoidCallback onDelete;
  final Future<bool> Function(String) onRename;
  final Future<bool> Function(bool) onPinToggle;

  const _SessionMenu({
    required this.session,
    required this.onDelete,
    required this.onRename,
    required this.onPinToggle,
  });

  @override
  Widget build(BuildContext context) {
    return PopupMenuButton<String>(
      tooltip: '会话操作',
      padding: EdgeInsets.zero,
      icon: const Icon(
        Icons.more_horiz_rounded,
        size: 16,
        color: ProductColors.textMuted,
      ),
      onSelected: (value) {
        if (value == 'delete') {
          onDelete();
        } else if (value == 'pin') {
          unawaited(onPinToggle(!session.isPinned));
        } else if (value == 'rename') {
          _showRenameDialog(context);
        }
      },
      itemBuilder: (context) => [
        const PopupMenuItem(value: 'rename', child: Text('重命名')),
        PopupMenuItem(
          value: 'pin',
          child: Text(session.isPinned ? '取消置顶' : '置顶'),
        ),
        const PopupMenuItem(value: 'delete', child: Text('删除')),
      ],
    );
  }

  void _showRenameDialog(BuildContext context) {
    final controller = TextEditingController(text: session.title);
    showDialog<void>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('重命名会话'),
          content: TextField(
            controller: controller,
            autofocus: true,
            decoration: const InputDecoration(hintText: '会话标题'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('取消'),
            ),
            TextButton(
              onPressed: () {
                unawaited(onRename(controller.text));
                Navigator.of(dialogContext).pop();
              },
              child: const Text('保存'),
            ),
          ],
        );
      },
    ).whenComplete(controller.dispose);
  }
}

class _ContextRail extends ConsumerWidget {
  final CareerPromptSender? onSendPrompt;

  const _ContextRail({required this.onSendPrompt});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(chatProvider);
    final workbench = ref.watch(careerWorkbenchProvider);
    final contextData = _ContextData.from(workbench);
    return Container(
      decoration: const BoxDecoration(
        color: ProductColors.canvas,
        border: Border(left: BorderSide(color: ProductColors.border)),
      ),
      child: SafeArea(
        left: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 18, 18, 18),
          children: [
            _ContextHeader(
              title: '当前任务上下文',
              subtitle: chat.isStreaming ? 'Agent 正在执行' : '对话上下文',
            ),
            const SizedBox(height: 12),
            _CurrentTaskCard(contextData: contextData),
            const SizedBox(height: 14),
            _RecommendedActionsCard(
              contextData: contextData,
              onSendPrompt: onSendPrompt,
            ),
            const SizedBox(height: 14),
            _RelatedAssetsCard(
              artifacts: chat.sessionArtifacts,
              linkedAssets: contextData.detail?.linkedAssets ?? const [],
            ),
          ],
        ),
      ),
    );
  }
}

class _ContextData {
  final CareerWorkbenchActionRun? action;
  final CareerApplicationSummaryView? summary;
  final CareerApplicationWorkbenchView? detail;

  const _ContextData({
    required this.action,
    required this.summary,
    required this.detail,
  });

  CareerApplicationView? get application =>
      detail?.application ?? summary?.application;

  CareerReadinessView? get readiness => detail?.readiness ?? summary?.readiness;

  static _ContextData from(CareerWorkbenchProvider provider) {
    final action = provider.activeAction;
    final actionApplicationId = action?.request.applicationId.trim() ?? '';
    CareerApplicationSummaryView? summary = provider.selectedApplicationSummary;
    if (summary == null && actionApplicationId.isNotEmpty) {
      for (final item in provider.applications) {
        if (item.application.applicationId == actionApplicationId) {
          summary = item;
          break;
        }
      }
    }
    summary ??=
        provider.applications.isEmpty ? null : provider.applications.first;
    return _ContextData(
      action: action,
      summary: summary,
      detail: provider.selectedApplicationDetail,
    );
  }
}

class _CurrentTaskCard extends StatelessWidget {
  final _ContextData contextData;

  const _CurrentTaskCard({required this.contextData});

  @override
  Widget build(BuildContext context) {
    final app = contextData.application;
    final action = contextData.action;
    if (app == null && action == null) {
      return const _ContextCard(
        title: '没有绑定任务',
        icon: Icons.assignment_outlined,
        child: _SidebarEmptyHint(
          message: '从求职项目、JD 匹配或学习计划发起动作后，这里会显示任务上下文。',
        ),
      );
    }
    return _ContextCard(
      title: action?.request.label ?? '关联求职项目',
      icon: Icons.assignment_outlined,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (app != null) ...[
            _ContextField(label: '项目', value: app.displayTitle),
            _ContextField(label: '阶段', value: careerStageLabel(app.stage)),
            _ContextField(
                label: '优先级', value: careerPriorityLabel(app.priority)),
            if (app.summary.trim().isNotEmpty)
              _ContextParagraph(text: app.summary.trim()),
          ],
          if (action != null) ...[
            const SizedBox(height: 8),
            _StatusPill(
              label: _actionStateLabel(action.state),
              tone: action.state == CareerWorkbenchActionState.failed
                  ? ProductTone.danger
                  : action.state == CareerWorkbenchActionState.completed
                      ? ProductTone.primary
                      : ProductTone.info,
            ),
            const SizedBox(height: 8),
            _ContextField(
              label: '来源',
              value: action.request.origin,
            ),
            _ContextField(
              label: '开始',
              value: careerFormatDateTime(action.startedAt),
            ),
          ],
          if (contextData.readiness?.score != null) ...[
            const SizedBox(height: 8),
            _ScoreBar(score: contextData.readiness!.score!),
          ],
        ],
      ),
    );
  }
}

class _RecommendedActionsCard extends StatelessWidget {
  final _ContextData contextData;
  final CareerPromptSender? onSendPrompt;

  const _RecommendedActionsCard({
    required this.contextData,
    required this.onSendPrompt,
  });

  @override
  Widget build(BuildContext context) {
    final app = contextData.application;
    final detailActions = contextData.detail?.suggestedActions
            .where((item) => item.enabled)
            .toList() ??
        const <CareerSuggestedActionView>[];
    final textActions = [
      ...?app?.nextActions,
      ...?contextData.readiness?.nextActions,
    ].where((item) => item.trim().isNotEmpty).take(4).toList();
    return _ContextCard(
      title: '推荐操作',
      icon: Icons.auto_awesome_outlined,
      trailing: detailActions.isEmpty && textActions.isEmpty ? null : '继续推进',
      child: Column(
        children: [
          if (detailActions.isNotEmpty)
            for (final action in detailActions.take(4)) ...[
              _ActionRow(
                icon: careerActionIcon(action.actionType),
                title: action.label,
                subtitle: action.reason,
                onTap: app == null
                    ? null
                    : () => sendCareerPromptAction(
                          sender: onSendPrompt,
                          application: app,
                          label: action.label,
                          actionType: action.actionType,
                          origin: 'chat_context_rail',
                          detail: action.promptIntent,
                        ),
              ),
              const SizedBox(height: 8),
            ]
          else if (textActions.isNotEmpty)
            for (final action in textActions) ...[
              _ActionRow(
                icon: Icons.arrow_forward_rounded,
                title: action,
                subtitle: '基于当前项目继续执行',
                onTap: app == null
                    ? null
                    : () => sendCareerPromptAction(
                          sender: onSendPrompt,
                          application: app,
                          label: action,
                          actionType: 'chat_context_action',
                          origin: 'chat_context_rail',
                        ),
              ),
              const SizedBox(height: 8),
            ]
          else
            const _SidebarEmptyHint(message: '当前暂无推荐操作'),
        ],
      ),
    );
  }
}

class _RelatedAssetsCard extends StatelessWidget {
  final List<SessionArtifactView> artifacts;
  final List<CareerLinkedAssetView> linkedAssets;

  const _RelatedAssetsCard({
    required this.artifacts,
    required this.linkedAssets,
  });

  @override
  Widget build(BuildContext context) {
    final recentArtifacts = artifacts.take(4).toList();
    final recentLinked = linkedAssets.take(4).toList();
    return _ContextCard(
      title: '关联资产',
      icon: Icons.folder_copy_outlined,
      trailing: '${artifacts.length + linkedAssets.length} 项',
      child: Column(
        children: [
          if (recentArtifacts.isEmpty && recentLinked.isEmpty)
            const _SidebarEmptyHint(message: '当前会话还没有关联文件或求职资产')
          else ...[
            for (final artifact in recentArtifacts) ...[
              _AssetRow(
                icon: _artifactIcon(artifact),
                title: artifact.title.trim().isEmpty
                    ? artifact.artifactId
                    : artifact.title.trim(),
                subtitle: '${artifact.kind} · ${artifact.sizeDisplay}',
              ),
              const SizedBox(height: 8),
            ],
            for (final asset in recentLinked) ...[
              _AssetRow(
                icon: Icons.work_outline_rounded,
                title: asset.title.trim().isEmpty ? asset.id : asset.title,
                subtitle: asset.subtitle.trim().isEmpty
                    ? asset.type
                    : asset.subtitle.trim(),
              ),
              const SizedBox(height: 8),
            ],
          ],
        ],
      ),
    );
  }
}

class _ContextCard extends StatelessWidget {
  final String title;
  final IconData icon;
  final String? trailing;
  final Widget child;

  const _ContextCard({
    required this.title,
    required this.icon,
    required this.child,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: ProductSurface.card(radius: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 17, color: ProductColors.primary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
              if (trailing != null)
                Text(
                  trailing!,
                  style: AppTheme.ts(
                    fontSize: 10.8,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.primary,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }
}

class _ContextHeader extends StatelessWidget {
  final String title;
  final String subtitle;

  const _ContextHeader({
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: ProductColors.primarySoft,
            borderRadius: BorderRadius.circular(12),
          ),
          child: const Icon(
            Icons.view_sidebar_outlined,
            size: 17,
            color: ProductColors.primary,
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 15,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                style: AppTheme.ts(
                  fontSize: 11,
                  color: ProductColors.textMuted,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ContextField extends StatelessWidget {
  final String label;
  final String value;

  const _ContextField({
    required this.label,
    required this.value,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 52,
            child: Text(
              label,
              style: AppTheme.ts(
                fontSize: 10.8,
                color: ProductColors.textMuted,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value.trim().isEmpty ? '-' : value.trim(),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 11.4,
                fontWeight: FontWeight.w800,
                color: ProductColors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ContextParagraph extends StatelessWidget {
  final String text;

  const _ContextParagraph({required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 4),
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.border),
      ),
      child: Text(
        text,
        maxLines: 4,
        overflow: TextOverflow.ellipsis,
        style: AppTheme.ts(
          fontSize: 11.2,
          height: 1.42,
          color: ProductColors.textSecondary,
        ),
      ),
    );
  }
}

class _ActionRow extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback? onTap;

  const _ActionRow({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(10, 9, 8, 9),
          decoration: BoxDecoration(
            color: ProductColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: ProductColors.border),
          ),
          child: Row(
            children: [
              Icon(icon, size: 16, color: ProductColors.primary),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title.trim().isEmpty ? '继续推进' : title.trim(),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.8,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                    if (subtitle.trim().isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitle.trim(),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 10.2,
                          color: ProductColors.textMuted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const Icon(
                Icons.chevron_right_rounded,
                size: 17,
                color: ProductColors.textMuted,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _AssetRow extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;

  const _AssetRow({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 32,
          height: 32,
          decoration: BoxDecoration(
            color: ProductColors.primarySoft,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Icon(icon, size: 16, color: ProductColors.primary),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 11.6,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.textSecondary,
                ),
              ),
              const SizedBox(height: 2),
              Text(
                subtitle,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 10.2,
                  color: ProductColors.textMuted,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ScoreBar extends StatelessWidget {
  final int score;

  const _ScoreBar({required this.score});

  @override
  Widget build(BuildContext context) {
    final value = score.clamp(0, 100) / 100;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(
              '匹配状态',
              style: AppTheme.ts(
                fontSize: 10.8,
                color: ProductColors.textMuted,
              ),
            ),
            const Spacer(),
            Text(
              '$score%',
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w900,
                color: ProductColors.primary,
              ),
            ),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(999),
          child: LinearProgressIndicator(
            value: value,
            minHeight: 7,
            color: ProductColors.primary,
            backgroundColor: ProductColors.primarySoft,
          ),
        ),
      ],
    );
  }
}

class _FloatingContextButton extends StatelessWidget {
  final VoidCallback onTap;

  const _FloatingContextButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
          decoration: BoxDecoration(
            color: ProductColors.surface.withValues(alpha: 0.92),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: ProductColors.border),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.06),
                blurRadius: 18,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(
                Icons.view_sidebar_outlined,
                size: 15,
                color: ProductColors.primary,
              ),
              const SizedBox(width: 5),
              Text(
                '上下文',
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.primary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SidebarSectionHeader extends StatelessWidget {
  final String title;
  final String? trailing;

  const _SidebarSectionHeader({
    required this.title,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            title,
            style: AppTheme.ts(
              fontSize: 12,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
        ),
        if (trailing != null)
          Text(
            trailing!,
            style: AppTheme.ts(
              fontSize: 10.5,
              fontWeight: FontWeight.w800,
              color: ProductColors.textMuted,
            ),
          ),
      ],
    );
  }
}

class _SidebarEmptyHint extends StatelessWidget {
  final String message;

  const _SidebarEmptyHint({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.border),
      ),
      child: Text(
        message,
        style: AppTheme.ts(
          fontSize: 11,
          height: 1.4,
          color: ProductColors.textMuted,
        ),
      ),
    );
  }
}

class _AssistantStatus extends StatelessWidget {
  final bool serverReachable;

  const _AssistantStatus({required this.serverReachable});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: ProductColors.primary,
              borderRadius: BorderRadius.circular(14),
            ),
            child: const Center(
              child: Text(
                'AI',
                style: TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w900,
                  fontSize: 12,
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'AI 助理',
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  serverReachable ? '在线' : '离线',
                  style: AppTheme.ts(
                    fontSize: 11,
                    color: serverReachable
                        ? ProductColors.primary
                        : ProductColors.danger,
                  ),
                ),
              ],
            ),
          ),
          const Icon(
            Icons.keyboard_arrow_down_rounded,
            size: 18,
            color: ProductColors.textMuted,
          ),
        ],
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  final String label;
  final ProductTone tone;

  const _StatusPill({
    required this.label,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: style.soft,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: style.color.withValues(alpha: 0.14)),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 10.8,
          fontWeight: FontWeight.w900,
          color: style.color,
        ),
      ),
    );
  }
}

String _sessionTime(DateTime value) {
  final now = DateTime.now();
  if (value.year == now.year &&
      value.month == now.month &&
      value.day == now.day) {
    return DateFormat('HH:mm').format(value);
  }
  final yesterday = now.subtract(const Duration(days: 1));
  if (value.year == yesterday.year &&
      value.month == yesterday.month &&
      value.day == yesterday.day) {
    return '昨天';
  }
  return DateFormat('MM-dd').format(value);
}

String _actionStateLabel(CareerWorkbenchActionState state) {
  return switch (state) {
    CareerWorkbenchActionState.running => '执行中',
    CareerWorkbenchActionState.completed => '已完成',
    CareerWorkbenchActionState.failed => '执行失败',
  };
}

IconData _artifactIcon(SessionArtifactView artifact) {
  final media = artifact.mediaType.toLowerCase();
  if (media.contains('pdf')) return Icons.picture_as_pdf_outlined;
  if (media.contains('image')) return Icons.image_outlined;
  if (media.contains('markdown')) return Icons.article_outlined;
  return Icons.description_outlined;
}
