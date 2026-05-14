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
import '../../shared/widgets/session_sidebar.dart';
import '../career/career_assets_panel.dart';
import '../career_workbench/career_workbench_page.dart';
import '../career_workbench/career_workbench_provider.dart';
import '../chat/chat_screen.dart';

enum _RightPanelMode { career, debug }

enum _PrimaryViewMode { chat, careerWorkbench }

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  bool _sidebarCollapsed = false;
  bool _rightPanelOpen = true;
  _RightPanelMode _rightPanelMode = _RightPanelMode.career;
  _PrimaryViewMode _primaryViewMode = _PrimaryViewMode.chat;

  void _openCompactSidebar(BuildContext context, ChatProvider provider) {
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
            child: SessionSidebar(
              sessions: provider.sessions,
              activeSessionId: provider.sessionId,
              collapsed: false,
              onToggleCollapse: () => Navigator.of(context).pop(),
              onNewSession: () {
                Navigator.of(context).pop();
                provider.createNewSession();
              },
              onSessionTap: (id) {
                Navigator.of(context).pop();
                provider.switchSession(id);
              },
              onSessionDelete: provider.deleteSession,
              onSessionRename: provider.renameSession,
              onSessionPinToggle: provider.setSessionPinned,
            ),
          ),
        );
      },
    );
  }

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
                _openCareerWorkbench();
              },
              onClose: () => Navigator.of(sheetContext).pop(),
            ),
          ),
        );
      },
    );
  }

  void _openCareerWorkbench() {
    setState(() {
      _primaryViewMode = _PrimaryViewMode.careerWorkbench;
      _rightPanelOpen = false;
    });
    unawaited(ref.read(careerWorkbenchProvider).refresh());
  }

  void _backToChat() {
    setState(() {
      _primaryViewMode = _PrimaryViewMode.chat;
    });
  }

  Future<void> _sendWorkbenchPrompt(String prompt) async {
    setState(() {
      _primaryViewMode = _PrimaryViewMode.chat;
    });
    await ref.read(chatProvider).sendMessage(prompt);
    unawaited(ref.read(careerWorkbenchProvider).refresh());
    unawaited(ref.read(careerAssetsProvider).refresh());
  }

  void _toggleDesktopPanel(_RightPanelMode mode) {
    setState(() {
      _primaryViewMode = _PrimaryViewMode.chat;
      if (_rightPanelMode == mode) {
        _rightPanelOpen = !_rightPanelOpen;
        return;
      }
      _rightPanelMode = mode;
      _rightPanelOpen = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(chatProvider);

    return Scaffold(
      body: Container(
        decoration: AppTheme.appShellDecoration,
        child: Stack(
          children: [
            const _AmbientBackground(),
            SafeArea(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final width = constraints.maxWidth;
                  final isCompact = width < 1260;
                  final useCompactSidebar = width < 980;
                  final edgePadding = width < 900 ? 12.0 : 18.0;
                  final gap = width < 900 ? 12.0 : 18.0;
                  final sidebarWidth =
                      (width * 0.19).clamp(272.0, 308.0).toDouble();
                  final panelWidth =
                      (width * 0.22).clamp(296.0, 336.0).toDouble();
                  final showDesktopRightPanel =
                      _primaryViewMode == _PrimaryViewMode.chat &&
                          _rightPanelOpen &&
                          !isCompact;
                  final showDesktopCareer = showDesktopRightPanel &&
                      _rightPanelMode == _RightPanelMode.career;
                  final showDesktopDebug = showDesktopRightPanel &&
                      _rightPanelMode == _RightPanelMode.debug;

                  return Padding(
                    padding: EdgeInsets.all(edgePadding),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (!useCompactSidebar) ...[
                          AnimatedContainer(
                            duration: const Duration(milliseconds: 220),
                            width: _sidebarCollapsed ? 78 : sidebarWidth,
                            child: SessionSidebar(
                              sessions: provider.sessions,
                              activeSessionId: provider.sessionId,
                              collapsed: _sidebarCollapsed,
                              onToggleCollapse: () => setState(
                                () => _sidebarCollapsed = !_sidebarCollapsed,
                              ),
                              onNewSession: provider.createNewSession,
                              onSessionTap: provider.switchSession,
                              onSessionDelete: provider.deleteSession,
                              onSessionRename: provider.renameSession,
                              onSessionPinToggle: provider.setSessionPinned,
                            ),
                          ),
                          SizedBox(width: gap),
                        ],
                        Expanded(
                          child: _primaryViewMode ==
                                  _PrimaryViewMode.careerWorkbench
                              ? CareerWorkbenchPage(
                                  onBackToChat: _backToChat,
                                  onSendPrompt: _sendWorkbenchPrompt,
                                )
                              : ChatScreen(
                                  showSidebarToggle: useCompactSidebar,
                                  onSidebarToggle: useCompactSidebar
                                      ? () => _openCompactSidebar(
                                            context,
                                            provider,
                                          )
                                      : null,
                                  showWorkbenchToggle: true,
                                  onWorkbenchToggle: _openCareerWorkbench,
                                  showCareerAssetsToggle: true,
                                  isCareerAssetsPanelOpen: showDesktopCareer,
                                  onCareerAssetsToggle: isCompact
                                      ? () => _openCompactCareerAssetsPanel(
                                            context,
                                          )
                                      : () => _toggleDesktopPanel(
                                            _RightPanelMode.career,
                                          ),
                                  showDebugToggle: true,
                                  isDebugPanelOpen: showDesktopDebug,
                                  onDebugToggle: isCompact
                                      ? () => _openCompactDebugPanel(
                                            context,
                                            provider,
                                          )
                                      : () => _toggleDesktopPanel(
                                            _RightPanelMode.debug,
                                          ),
                                ),
                        ),
                        if (showDesktopRightPanel) ...[
                          SizedBox(width: gap),
                          SizedBox(
                            width: panelWidth,
                            child: showDesktopCareer
                                ? CareerAssetsPanel(
                                    onOpenWorkbench: _openCareerWorkbench,
                                    onClose: () =>
                                        setState(() => _rightPanelOpen = false),
                                  )
                                : _DebugPanel(
                                    provider: provider,
                                    onClose: () => setState(
                                      () => _rightPanelOpen = false,
                                    ),
                                  ),
                          ),
                        ],
                      ],
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AmbientBackground extends StatelessWidget {
  const _AmbientBackground();

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: Stack(
        children: [
          Positioned(
            top: -180,
            left: -120,
            child: _GlowBlob(
              size: 420,
              color: AppTheme.accent.withValues(alpha: 0.12),
            ),
          ),
          Positioned(
            bottom: -220,
            right: -140,
            child: _GlowBlob(
              size: 480,
              color: const Color(0xFF2563EB).withValues(alpha: 0.08),
            ),
          ),
          Positioned(
            top: 160,
            right: 240,
            child: _GlowBlob(
              size: 220,
              color: Colors.white.withValues(alpha: 0.02),
            ),
          ),
        ],
      ),
    );
  }
}

class _GlowBlob extends StatelessWidget {
  final double size;
  final Color color;

  const _GlowBlob({required this.size, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        gradient: RadialGradient(
          colors: [
            color,
            color.withValues(alpha: color.a * 0.45),
            Colors.transparent,
          ],
        ),
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
