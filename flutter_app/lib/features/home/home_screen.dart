import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/widgets/session_sidebar.dart';
import '../chat/chat_screen.dart';

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  bool _sidebarCollapsed = false;
  bool _debugPanelOpen = true;

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(chatProvider);

    return Scaffold(
      body: Row(
        children: [
          // ── Sidebar ─────────────────────────────────────────────────
          SessionSidebar(
            sessions: provider.sessions,
            activeSessionId: provider.sessionId,
            collapsed: _sidebarCollapsed,
            onToggleCollapse: () =>
                setState(() => _sidebarCollapsed = !_sidebarCollapsed),
            onNewSession: provider.createNewSession,
            onSessionTap: provider.switchSession,
            onSessionDelete: provider.deleteSession,
          ),
          // ── Main chat area ──────────────────────────────────────────
          const Expanded(child: ChatScreen()),
          // ── Debug panel ─────────────────────────────────────────────
          if (_debugPanelOpen)
            _DebugPanel(
              provider: provider,
              onClose: () => setState(() => _debugPanelOpen = false),
            ),
          if (!_debugPanelOpen)
            Container(
              width: 40,
              color: AppTheme.surface,
              child: Column(
                children: [
                  const SizedBox(height: 12),
                  IconButton(
                    iconSize: 18,
                    icon: const Icon(Icons.developer_board_rounded,
                        color: AppTheme.textSecondary),
                    onPressed: () => setState(() => _debugPanelOpen = true),
                    tooltip: "打开调试面板",
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

// ── Debug panel ─────────────────────────────────────────────────────────

class _DebugPanel extends ConsumerWidget {
  final ChatProvider provider;
  final VoidCallback onClose;

  const _DebugPanel({required this.provider, required this.onClose});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Container(
      width: 300,
      decoration: const BoxDecoration(
        color: AppTheme.surface,
        border: Border(left: BorderSide(color: AppTheme.border, width: 0.5)),
      ),
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
            decoration: const BoxDecoration(
              border: Border(bottom: BorderSide(color: AppTheme.border, width: 0.5)),
            ),
            child: Row(
              children: [
                const Icon(Icons.developer_board_rounded,
                    size: 16, color: AppTheme.accent),
                const SizedBox(width: 8),
                Text("调试面板",
                    style: AppTheme.ts(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.textPrimary)),
                const Spacer(),
                IconButton(
                  iconSize: 16,
                  icon: const Icon(Icons.refresh_rounded,
                      color: AppTheme.textSecondary),
                  onPressed: () {
                    provider.refreshEvents();
                    provider.refreshSessionFiles();
                  },
                  tooltip: "刷新",
                ),
                IconButton(
                  iconSize: 16,
                  icon: const Icon(Icons.close_rounded,
                      color: AppTheme.textSecondary),
                  onPressed: onClose,
                ),
              ],
            ),
          ),
          // Session info
          if (provider.sessionId != null)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: AppTheme.border, width: 0.5)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text("当前会话",
                      style: AppTheme.ts(
                          fontSize: 11, color: AppTheme.textTertiary)),
                  const SizedBox(height: 4),
                  Text(provider.sessionId!,
                      style: AppTheme.ts(
                          fontSize: 12,
                          color: AppTheme.textSecondary)),
                ],
              ),
            ),
          // Scrollable content
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: [
                _section("工具调用", provider.lastToolCalls.isEmpty
                    ? "[]"
                    : _formatToolCalls(provider.lastToolCalls)),
                const SizedBox(height: 12),
                _section("Memory 命中", provider.lastMemoryHits.isEmpty
                    ? "[]"
                    : _formatMemoryHits(provider.lastMemoryHits)),
                const SizedBox(height: 12),
                _section("执行事件", _formatEvents(provider.streamEvents)),
                const SizedBox(height: 12),
                _section("会话文件", _formatFiles(provider.sessionFiles)),
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
        Text(title,
            style: AppTheme.ts(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: AppTheme.textTertiary)),
        const SizedBox(height: 6),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: const Color(0xFF111111),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: AppTheme.border),
          ),
          child: SelectableText(content,
              style: AppTheme.ts(
                  fontSize: 11, color: AppTheme.textSecondary, height: 1.5)),
        ),
      ],
    );
  }

  String _formatToolCalls(List<ToolCallView> calls) {
    final buf = StringBuffer();
    for (final c in calls) {
      buf.writeln("${c.name}(${jsonEncode(c.arguments)})");
    }
    return buf.toString().trim();
  }

  String _formatMemoryHits(List<MemoryView> hits) {
    final buf = StringBuffer();
    for (final h in hits) {
      buf.writeln("[${h.tags.join(', ')}] ${h.content}");
    }
    return buf.toString().trim();
  }

  String _formatEvents(List<EventView> events) {
    if (events.isEmpty) return "[]";
    final buf = StringBuffer();
    for (final e in events) {
      final time = DateFormat("HH:mm:ss").format(e.createdAt);
      buf.writeln("[$time] ${e.shortDescription}");
    }
    return buf.toString().trim();
  }

  String _formatFiles(List<SessionFileView> files) {
    if (files.isEmpty) return "当前会话暂无文件";
    final buf = StringBuffer();
    for (final f in files) {
      final active = provider.activeFileIds.contains(f.fileId) ? "✓" : " ";
      buf.writeln("[$active] ${f.filename} (${f.status}) ${f.sizeDisplay}");
    }
    return buf.toString().trim();
  }
}
