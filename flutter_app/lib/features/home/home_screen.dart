import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/career_assets_provider.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../../shared/widgets/session_sidebar.dart';
import '../career/career_assets_panel.dart';
import '../career_workbench/career_workbench_provider.dart';
import '../chat_workspace/agent_chat_workspace.dart';
import '../chat/chat_screen.dart';
import '../dashboard/dashboard_page.dart';
import '../jd_match/jd_match_page.dart';
import '../learning/learning_plan_page.dart';
import '../notes/notes_library_page.dart';
import '../projects/career_projects_page.dart';
import '../resumes/resume_library_page.dart';
import '../workspace/workspace_models.dart';
import '../workspace/workspace_shell.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  WorkspacePage _activePage = WorkspacePage.dashboard;

  void _openCompactDebugPanel(BuildContext context, ChatProvider provider) {
    showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) {
        final height = MediaQuery.of(sheetContext).size.height;
        return Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          child: SizedBox(
            height: math.min(height * 0.78, 680.0),
            child: _DebugPanel(
              provider: provider,
              compact: true,
              onClose: () => Navigator.of(context).pop(),
            ),
          ),
        );
      },
    );
  }

  void _openCompactCareerAssetsPanel(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) {
        final height = MediaQuery.of(sheetContext).size.height;
        return Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          child: SizedBox(
            height: math.min(height * 0.82, 720.0),
            child: CareerAssetsPanel(
              compact: true,
              onOpenWorkbench: () {
                Navigator.of(sheetContext).pop();
                _setWorkspacePage(WorkspacePage.projects);
              },
              onClose: () => Navigator.of(sheetContext).pop(),
            ),
          ),
        );
      },
    );
  }

  void _setWorkspacePage(WorkspacePage page) {
    setState(() {
      _activePage = page;
    });
    final workbench = ref.read(careerWorkbenchProvider);
    if (getWorkspacePageNeedsWorkbench(page)) {
      unawaited(workbench.ensureLoaded());
    }
  }

  void _openProject(String applicationId) {
    _setWorkspacePage(WorkspacePage.projects);
    unawaited(
      ref.read(careerWorkbenchProvider).selectApplication(applicationId),
    );
  }

  void _openChat() {
    _setWorkspacePage(WorkspacePage.chat);
  }

  void _openSessionHistory(BuildContext context) {
    unawaited(ref.read(chatProvider).refreshSessions());
    if (MediaQuery.sizeOf(context).width >= ProductBreakpoints.shellDesktop) {
      _openChat();
      return;
    }
    showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) {
        final height = MediaQuery.sizeOf(sheetContext).height;
        final width = MediaQuery.sizeOf(sheetContext).width;
        return Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          child: Align(
            alignment: Alignment.bottomLeft,
            child: SizedBox(
              width: width < 620 ? double.infinity : 380,
              height: math.min(height * 0.86, 760.0),
              child: Consumer(
                builder: (context, ref, _) {
                  final chat = ref.watch(chatProvider);
                  return SessionSidebar(
                    sessions: chat.sessions,
                    activeSessionId: chat.sessionId,
                    collapsed: false,
                    onToggleCollapse: () => Navigator.of(sheetContext).pop(),
                    onNewSession: () {
                      Navigator.of(sheetContext).pop();
                      ref.read(chatProvider).createNewSession();
                      _openChat();
                    },
                    onSessionTap: (sessionId) {
                      Navigator.of(sheetContext).pop();
                      _openChat();
                      unawaited(
                        ref.read(chatProvider).switchSession(sessionId),
                      );
                    },
                    onSessionDelete: (sessionId) {
                      unawaited(
                        ref.read(chatProvider).deleteSession(sessionId),
                      );
                    },
                    onSessionRename: (sessionId, title) {
                      return ref
                          .read(chatProvider)
                          .renameSession(sessionId, title);
                    },
                    onSessionPinToggle: (sessionId, isPinned) {
                      return ref
                          .read(chatProvider)
                          .setSessionPinned(sessionId, isPinned);
                    },
                  );
                },
              ),
            ),
          ),
        );
      },
    );
  }

  Future<void> _sendWorkbenchPrompt(
    String prompt, {
    CareerWorkbenchActionRequest? action,
  }) async {
    setState(() {
      _activePage = WorkspacePage.chat;
    });
    final workbench = ref.read(careerWorkbenchProvider);
    final chat = ref.read(chatProvider);
    if (action != null) {
      workbench.beginAction(action);
    }
    await chat.sendMessage(prompt);
    final chatError = ref.read(chatProvider).error;
    if (chatError != null && action != null) {
      workbench.failAction(chatError);
      return;
    }
    await workbench.refresh();
    await ref.read(careerAssetsProvider).refresh();
    if (action != null) {
      workbench.completeAction();
    }
  }

  void _handleWorkspaceCommand(String command) {
    _openChat();
    unawaited(ref.read(chatProvider).sendMessage(command));
  }

  WorkspaceBadges _workspaceBadges(CareerWorkbenchProvider workbench) {
    final counts = workbench.workbench?.counts;
    final jdCount = workbench.jobMatchLibraryCount > 0
        ? workbench.jobMatchLibraryCount
        : workbench.applications
            .where((item) =>
                (item.application.jdAnalysisId?.trim().isNotEmpty ?? false) ||
                (item.application.jobFitReportId?.trim().isNotEmpty ?? false))
            .length;
    return WorkspaceBadges(
      applications: counts?.applications ?? workbench.applications.length,
      resumes: counts?.resumeVersions == 0
          ? workbench.resumeLibraryCount
          : (counts?.resumeVersions ?? workbench.resumeLibraryCount),
      jdMatches: jdCount,
      learningTasks: counts?.learningTasks ?? 0,
      notes: counts?.notes ?? 0,
    );
  }

  Widget _buildWorkspaceChild(
    BuildContext context,
    ChatProvider chat,
    CareerWorkbenchProvider workbench,
  ) {
    return switch (_activePage) {
      WorkspacePage.dashboard => DashboardPage(
          onOpenProject: _openProject,
          onOpenProjects: () => _setWorkspacePage(WorkspacePage.projects),
          onOpenResumes: () => _setWorkspacePage(WorkspacePage.resumes),
          onOpenLearning: () => _setWorkspacePage(WorkspacePage.learning),
          onOpenNotes: () => _setWorkspacePage(WorkspacePage.notes),
          onSendPrompt: _sendWorkbenchPrompt,
        ),
      WorkspacePage.chat => ChatScreen(
          showSidebarToggle: true,
          onSidebarToggle: () => _openSessionHistory(context),
          showWorkbenchToggle: true,
          onWorkbenchToggle: () => _setWorkspacePage(WorkspacePage.projects),
          showCareerAssetsToggle: true,
          onCareerAssetsToggle: () => _openCompactCareerAssetsPanel(context),
          showDebugToggle: true,
          onDebugToggle: () => _openCompactDebugPanel(context, chat),
        ),
      WorkspacePage.projects => CareerProjectsPage(
          onOpenProject: _openProject,
          onOpenResumes: () => _setWorkspacePage(WorkspacePage.resumes),
          onOpenJDMatch: () => _setWorkspacePage(WorkspacePage.jdMatch),
          onOpenLearning: () => _setWorkspacePage(WorkspacePage.learning),
          onSendPrompt: _sendWorkbenchPrompt,
        ),
      WorkspacePage.jdMatch => JDMatchPage(
          onOpenProjects: () => _setWorkspacePage(WorkspacePage.projects),
          onOpenResumes: () => _setWorkspacePage(WorkspacePage.resumes),
          onOpenLearning: () => _setWorkspacePage(WorkspacePage.learning),
          onSendPrompt: _sendWorkbenchPrompt,
        ),
      WorkspacePage.resumes => ResumeLibraryPage(
          onOpenProjects: () => _setWorkspacePage(WorkspacePage.projects),
          onOpenJDMatch: () => _setWorkspacePage(WorkspacePage.jdMatch),
          onSendPrompt: _sendWorkbenchPrompt,
        ),
      WorkspacePage.learning => LearningPlanPage(
          onOpenProjects: () => _setWorkspacePage(WorkspacePage.projects),
          onOpenNotes: () => _setWorkspacePage(WorkspacePage.notes),
          onSendPrompt: _sendWorkbenchPrompt,
        ),
      WorkspacePage.notes => NotesLibraryPage(
          currentSessionId: chat.sessionId,
          onOpenProjects: () => _setWorkspacePage(WorkspacePage.projects),
          onOpenLearning: () => _setWorkspacePage(WorkspacePage.learning),
          onSendPrompt: _sendWorkbenchPrompt,
        ),
    };
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatProvider);
    final workbench = ref.watch(careerWorkbenchProvider);
    final badges = _workspaceBadges(workbench);

    if (_activePage == WorkspacePage.chat) {
      return Scaffold(
        body: AgentChatWorkspace(
          badges: badges,
          onPageChanged: _setWorkspacePage,
          onNewSession: () {
            chat.createNewSession();
            _openChat();
          },
          onSendPrompt: _sendWorkbenchPrompt,
        ),
      );
    }

    return Scaffold(
      body: ProductWorkspaceShell(
        activePage: _activePage,
        badges: badges,
        serverReachable: chat.serverReachable,
        onPageChanged: _setWorkspacePage,
        onNewSession: () {
          chat.createNewSession();
          _openChat();
        },
        onOpenChat: _openChat,
        onOpenSessionHistory: () => _openSessionHistory(context),
        onCommandSubmitted: _handleWorkspaceCommand,
        child: _buildWorkspaceChild(context, chat, workbench),
      ),
    );
  }
}

class _DebugPanel extends ConsumerWidget {
  final ChatProvider provider;
  final VoidCallback onClose;
  final bool compact;

  const _DebugPanel({
    required this.provider,
    required this.onClose,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tokenUsage = _TokenUsageSnapshot.fromEvents(provider.streamEvents);
    final tokenSummary = provider.tokenUsageSummary;
    return Container(
      decoration: AppTheme.floatingPanelDecoration(
        radius: compact ? 28 : 30,
        alpha: 0.9,
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 16, 12, 14),
            child: Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: AppTheme.surfaceActive,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: AppTheme.border),
                  ),
                  child: Icon(
                    Icons.developer_board_rounded,
                    size: 18,
                    color: AppTheme.accent,
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  '调试面板',
                  style: AppTheme.ts(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const Spacer(),
                _PanelIconButton(
                  icon: Icons.refresh_rounded,
                  onTap: () {
                    unawaited(provider.refreshHealth());
                    provider.refreshEvents();
                    provider.refreshSessionArtifacts();
                    unawaited(provider.refreshTokenUsageSummary());
                  },
                ),
                const SizedBox(width: 6),
                _PanelIconButton(icon: Icons.close_rounded, onTap: onClose),
              ],
            ),
          ),
          if (provider.sessionId != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 0, 18, 14),
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 14,
                ),
                decoration: BoxDecoration(
                  color: AppTheme.surface.withValues(alpha: 0.82),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '当前会话',
                      style: AppTheme.ts(
                        fontSize: 11,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      provider.sessionId!,
                      style: AppTheme.ts(
                        fontSize: 12,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
              children: [
                _TokenUsageSection(snapshot: tokenUsage),
                const SizedBox(height: 14),
                _TokenUsageBaselineSection(
                  summary: tokenSummary,
                  loading: provider.isLoadingTokenUsageSummary,
                ),
                const SizedBox(height: 14),
                _section(
                  '系统状态',
                  _formatSystemHealth(
                    provider.healthView,
                    provider.serverReachable,
                  ),
                ),
                const SizedBox(height: 14),
                _section(
                  '工具调用',
                  provider.lastToolCalls.isEmpty
                      ? '[]'
                      : _formatToolCalls(provider.lastToolCalls),
                ),
                const SizedBox(height: 14),
                _section(
                  'Memory 命中',
                  provider.lastMemoryHits.isEmpty
                      ? '[]'
                      : _formatMemoryHits(provider.lastMemoryHits),
                ),
                const SizedBox(height: 14),
                _section('执行事件', _formatEvents(provider.streamEvents)),
                const SizedBox(height: 14),
                _section('会话资料', _formatArtifacts(provider.sessionArtifacts)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _section(String title, String content) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: AppTheme.ts(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            color: AppTheme.textTertiary,
          ),
        ),
        const SizedBox(height: 8),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.82),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(color: AppTheme.border),
          ),
          child: SelectableText(
            content,
            style: AppTheme.ts(
              fontSize: 11,
              color: AppTheme.textSecondary,
              height: 1.55,
            ),
          ),
        ),
      ],
    );
  }

  String _formatToolCalls(List<ToolCallView> calls) {
    final buf = StringBuffer();
    for (final c in calls) {
      buf.writeln('${c.name}(${jsonEncode(c.arguments)})');
    }
    return buf.toString().trim();
  }

  String _formatMemoryHits(List<MemoryView> hits) {
    final buf = StringBuffer();
    for (final h in hits) {
      buf.writeln('[${h.tags.join(', ')}] ${h.content}');
    }
    return buf.toString().trim();
  }

  String _formatEvents(List<EventView> events) {
    if (events.isEmpty) return '[]';
    final buf = StringBuffer();
    for (final e in events) {
      final time = DateFormat('HH:mm:ss').format(e.createdAt);
      buf.writeln('[$time] ${e.shortDescription}');
    }
    return buf.toString().trim();
  }

  String _formatArtifacts(List<SessionArtifactView> files) {
    if (files.isEmpty) return '当前会话暂无资料';
    final buf = StringBuffer();
    for (final f in files) {
      final active =
          provider.activeArtifactIds.contains(f.artifactId) ? '✓' : ' ';
      buf.writeln('[$active] ${f.title} (${f.status}) ${f.sizeDisplay}');
    }
    return buf.toString().trim();
  }

  String _formatSystemHealth(HealthView? health, bool reachable) {
    final buf = StringBuffer();
    final status = health?.status ?? (reachable ? 'ok' : 'offline');
    buf.writeln('后端状态: ${reachable ? '在线' : '离线'} ($status)');
    final mid = health?.midTermFlush;
    if (mid == null) {
      buf.writeln('mid_term_flush: -');
      return buf.toString().trim();
    }

    buf.writeln('mid_term_flush.worker_enabled: ${mid.workerEnabled}');
    if (mid.error != null) {
      buf.writeln('mid_term_flush.error: ${mid.error}');
      return buf.toString().trim();
    }

    final queue = mid.queue;
    if (queue == null) {
      buf.writeln('mid_term_flush.queue: -');
      return buf.toString().trim();
    }

    buf.writeln('queue.targets: ${queue.targets}');
    buf.writeln('queue.total: ${queue.total}');
    buf.writeln('queue.due: ${queue.due}');
    buf.writeln('queue.retry: ${queue.retry}');
    buf.writeln('queue.deferred: ${queue.deferred}');
    buf.writeln('queue.succeeded: ${queue.succeeded}');
    return buf.toString().trim();
  }
}

class _TokenUsageSection extends StatelessWidget {
  final _TokenUsageSnapshot snapshot;

  const _TokenUsageSection({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final hasData = snapshot.entries.isNotEmpty;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            AppTheme.accent.withValues(alpha: AppTheme.isDark ? 0.16 : 0.10),
            const Color(0xFF2563EB).withValues(
              alpha: AppTheme.isDark ? 0.12 : 0.07,
            ),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(
          color:
              AppTheme.accent.withValues(alpha: AppTheme.isDark ? 0.32 : 0.24),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: AppTheme.surface.withValues(alpha: 0.8),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Icon(
                  Icons.data_usage_rounded,
                  size: 16,
                  color: AppTheme.accent,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Token 消耗',
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      hasData
                          ? '${snapshot.entries.length} 次模型接口调用'
                          : '等待下一次模型调用',
                      style: AppTheme.ts(
                        fontSize: 10,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              _TokenSourceChip(snapshot: snapshot),
            ],
          ),
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _TokenMetric(
                  label: '累计',
                  value: _formatTokenCount(snapshot.totalTokens),
                  strong: true,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _TokenMetric(
                  label: '输入',
                  value: _formatTokenCount(snapshot.promptTokens),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _TokenMetric(
                  label: '输出',
                  value: _formatTokenCount(snapshot.completionTokens),
                ),
              ),
            ],
          ),
          if (hasData) ...[
            const SizedBox(height: 14),
            ...snapshot.entries.take(8).map(_TokenUsageRow.new),
          ] else ...[
            const SizedBox(height: 12),
            Text(
              '运行一次对话后，这里会按时间列出每次模型接口、所属 Agent、输入/输出/总 token。',
              style: AppTheme.ts(
                fontSize: 11,
                color: AppTheme.textSecondary,
                height: 1.45,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _TokenUsageBaselineSection extends StatelessWidget {
  final TokenUsageSummaryView? summary;
  final bool loading;

  const _TokenUsageBaselineSection({
    required this.summary,
    required this.loading,
  });

  @override
  Widget build(BuildContext context) {
    final data = summary;
    final hasData = data != null && data.callCount > 0;
    final maxSessionTokens = data?.sessions
            .fold<int>(0, (max, item) => math.max(max, item.totalTokens)) ??
        0;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.86),
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: AppTheme.border),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.16 : 0.06),
            blurRadius: 18,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: const Color(0xFF2563EB).withValues(alpha: 0.10),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: const Color(0xFF2563EB).withValues(alpha: 0.20),
                  ),
                ),
                child: const Icon(
                  Icons.query_stats_rounded,
                  size: 16,
                  color: Color(0xFF2563EB),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '历史成本基线',
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      hasData
                          ? '${data.sessionCount} 个会话 · ${data.callCount} 次调用'
                          : loading
                              ? '正在读取历史 llm_usage 事件'
                              : '暂无历史 token 记录',
                      style: AppTheme.ts(
                        fontSize: 10,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              if (loading)
                SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: AppTheme.accent,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 14),
          if (!hasData)
            Text(
              '完成一次模型调用后，这里会展示最近会话的总量、Agent 分布和高消耗会话，便于后续做成本优化对比。',
              style: AppTheme.ts(
                fontSize: 11,
                color: AppTheme.textSecondary,
                height: 1.45,
              ),
            )
          else ...[
            Row(
              children: [
                Expanded(
                  child: _TokenMetric(
                    label: '历史总量',
                    value: _formatTokenCount(data.totalTokens),
                    strong: true,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _TokenMetric(
                    label: 'Provider',
                    value: data.providerCount.toString(),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _TokenMetric(
                    label: '估算',
                    value: data.estimatedCount.toString(),
                  ),
                ),
              ],
            ),
            if (data.agentBuckets.isNotEmpty) ...[
              const SizedBox(height: 14),
              Text(
                'Agent 分布',
                style: AppTheme.ts(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.textTertiary,
                ),
              ),
              const SizedBox(height: 8),
              ...data.agentBuckets.take(4).map(_TokenBucketRow.new),
            ],
            if (data.sessions.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                '最近高消耗会话',
                style: AppTheme.ts(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.textTertiary,
                ),
              ),
              const SizedBox(height: 8),
              ...data.sessions.take(4).map(
                    (item) => _TokenSessionCostRow(
                      item: item,
                      maxTokens: maxSessionTokens,
                    ),
                  ),
            ],
          ],
        ],
      ),
    );
  }
}

class _TokenBucketRow extends StatelessWidget {
  final TokenUsageBucketView bucket;

  const _TokenBucketRow(this.bucket);

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 7),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.78)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              _formatAgentName(bucket.key),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: AppTheme.textPrimary,
              ),
            ),
          ),
          Text(
            '${_formatTokenCount(bucket.totalTokens)} · ${bucket.callCount} 次',
            style: AppTheme.ts(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: AppTheme.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _TokenSessionCostRow extends StatelessWidget {
  final TokenUsageSessionView item;
  final int maxTokens;

  const _TokenSessionCostRow({
    required this.item,
    required this.maxTokens,
  });

  @override
  Widget build(BuildContext context) {
    final ratio =
        maxTokens <= 0 ? 0.0 : (item.totalTokens / maxTokens).clamp(0.0, 1.0);
    final time = item.lastUsageAt ?? item.updatedAt;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.66),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.78)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  item.title.isEmpty ? item.sessionId : item.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ),
              Text(
                _formatTokenCount(item.totalTokens),
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.accent,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: ratio,
              minHeight: 5,
              backgroundColor: AppTheme.border.withValues(alpha: 0.55),
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            '${item.callCount} 次调用 · ${DateFormat('MM-dd HH:mm').format(time)}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(fontSize: 10, color: AppTheme.textTertiary),
          ),
        ],
      ),
    );
  }
}

class _TokenSourceChip extends StatelessWidget {
  final _TokenUsageSnapshot snapshot;

  const _TokenSourceChip({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final label = snapshot.entries.isEmpty
        ? '待记录'
        : snapshot.estimatedCount == 0
            ? 'provider'
            : snapshot.providerCount == 0
                ? 'estimated'
                : 'mixed';
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.border),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 10,
          fontWeight: FontWeight.w700,
          color: AppTheme.accent,
        ),
      ),
    );
  }
}

class _TokenMetric extends StatelessWidget {
  final String label;
  final String value;
  final bool strong;

  const _TokenMetric({
    required this.label,
    required this.value,
    this.strong = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: strong ? 15 : 13,
              fontWeight: FontWeight.w800,
              color: strong ? AppTheme.accent : AppTheme.textPrimary,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            label,
            style: AppTheme.ts(fontSize: 10, color: AppTheme.textTertiary),
          ),
        ],
      ),
    );
  }
}

class _TokenUsageRow extends StatelessWidget {
  final _TokenUsageEntry entry;

  const _TokenUsageRow(this.entry);

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.82),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.85)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: entry.estimated
                  ? const Color(0xFFF59E0B).withValues(alpha: 0.12)
                  : AppTheme.accent.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(11),
              border: Border.all(
                color: entry.estimated
                    ? const Color(0xFFF59E0B).withValues(alpha: 0.28)
                    : AppTheme.accent.withValues(alpha: 0.26),
              ),
            ),
            child: Icon(
              entry.estimated
                  ? Icons.functions_rounded
                  : Icons.check_circle_outline_rounded,
              size: 15,
              color:
                  entry.estimated ? const Color(0xFFD97706) : AppTheme.accent,
            ),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        '${entry.agentLabel} · ${entry.phaseLabel}',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    Text(
                      _formatTokenCount(entry.totalTokens),
                      style: AppTheme.ts(
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                Text(
                  '${entry.timeLabel} · ${entry.apiLabel}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style:
                      AppTheme.ts(fontSize: 10, color: AppTheme.textTertiary),
                ),
                const SizedBox(height: 4),
                Text(
                  '输入 ${_formatTokenCount(entry.promptTokens)} / 输出 ${_formatTokenCount(entry.completionTokens)}',
                  style:
                      AppTheme.ts(fontSize: 10, color: AppTheme.textSecondary),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _TokenUsageSnapshot {
  final List<_TokenUsageEntry> entries;
  final int promptTokens;
  final int completionTokens;
  final int totalTokens;
  final int providerCount;
  final int estimatedCount;

  const _TokenUsageSnapshot({
    required this.entries,
    required this.promptTokens,
    required this.completionTokens,
    required this.totalTokens,
    required this.providerCount,
    required this.estimatedCount,
  });

  factory _TokenUsageSnapshot.fromEvents(List<EventView> events) {
    final entries = events
        .where((event) => event.type == 'llm_usage')
        .map(_TokenUsageEntry.fromEvent)
        .toList()
      ..sort((left, right) => right.createdAt.compareTo(left.createdAt));
    var prompt = 0;
    var completion = 0;
    var total = 0;
    var provider = 0;
    var estimated = 0;
    for (final entry in entries) {
      prompt += entry.promptTokens;
      completion += entry.completionTokens;
      total += entry.totalTokens;
      if (entry.estimated) {
        estimated += 1;
      } else {
        provider += 1;
      }
    }
    return _TokenUsageSnapshot(
      entries: entries,
      promptTokens: prompt,
      completionTokens: completion,
      totalTokens: total,
      providerCount: provider,
      estimatedCount: estimated,
    );
  }
}

class _TokenUsageEntry {
  final DateTime createdAt;
  final String agentId;
  final String api;
  final String operation;
  final String mode;
  final String phase;
  final int? roundIndex;
  final String model;
  final int promptTokens;
  final int completionTokens;
  final int totalTokens;
  final bool estimated;

  const _TokenUsageEntry({
    required this.createdAt,
    required this.agentId,
    required this.api,
    required this.operation,
    required this.mode,
    required this.phase,
    required this.roundIndex,
    required this.model,
    required this.promptTokens,
    required this.completionTokens,
    required this.totalTokens,
    required this.estimated,
  });

  factory _TokenUsageEntry.fromEvent(EventView event) {
    final payload = event.payload;
    final prompt = _readTokenInt(payload['prompt_tokens']);
    final completion = _readTokenInt(payload['completion_tokens']);
    final total =
        _readOptionalTokenInt(payload['total_tokens']) ?? prompt + completion;
    return _TokenUsageEntry(
      createdAt: event.createdAt,
      agentId: event.agentId,
      api: payload['api']?.toString() ?? 'POST /v1/chat/completions',
      operation: payload['operation']?.toString() ?? '',
      mode: payload['mode']?.toString() ?? '',
      phase: payload['phase']?.toString() ?? '',
      roundIndex: _readOptionalTokenInt(payload['round_index']),
      model: payload['model']?.toString() ?? 'unknown',
      promptTokens: prompt,
      completionTokens: completion,
      totalTokens: total,
      estimated: payload['estimated'] == true,
    );
  }

  String get timeLabel => DateFormat('HH:mm:ss').format(createdAt);

  String get agentLabel {
    if (agentId == 'agent_main') return '主控';
    if (agentId == 'resume_agent') return '简历';
    if (agentId == 'job_agent') return '岗位';
    return agentId.isEmpty ? 'agent' : agentId;
  }

  String get phaseLabel {
    if (phase == 'tool_loop') {
      return roundIndex == null ? '工具轮' : '第 $roundIndex 轮';
    }
    if (phase == 'final_answer_recovery') return '补答';
    return phase.isEmpty ? '模型调用' : phase;
  }

  String get apiLabel {
    final modeLabel = mode == 'stream' ? '流式' : '同步';
    final modelLabel = model == 'unknown' ? '' : ' · $model';
    return '$api · $modeLabel$modelLabel';
  }
}

int _readTokenInt(dynamic value) {
  if (value is int) return value < 0 ? 0 : value;
  return 0;
}

int? _readOptionalTokenInt(dynamic value) {
  if (value is int) return value < 0 ? 0 : value;
  return null;
}

String _formatTokenCount(int value) {
  if (value >= 1000000) {
    return '${(value / 1000000).toStringAsFixed(1)}M';
  }
  if (value >= 1000) {
    return '${(value / 1000).toStringAsFixed(1)}K';
  }
  return value.toString();
}

String _formatAgentName(String value) {
  switch (value) {
    case 'agent_main':
      return '主控 Agent';
    case 'resume_agent':
      return '简历 Agent';
    case 'job_agent':
      return '岗位 Agent';
    case 'retrieval_agent':
      return '检索 Agent';
    case 'note_agent':
      return '笔记 Agent';
    case 'learning_agent':
      return '学习 Agent';
    default:
      return value.isEmpty ? '未知 Agent' : value;
  }
}

class _PanelIconButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;

  const _PanelIconButton({required this.icon, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Container(
          width: 34,
          height: 34,
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.82),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: AppTheme.border),
          ),
          child: Icon(icon, size: 17, color: AppTheme.textSecondary),
        ),
      ),
    );
  }
}
