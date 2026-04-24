import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/widgets/chat_bubble.dart';
import '../../shared/widgets/input_bar.dart';

const double _messageRailMaxWidth = 1160;

class ChatScreen extends ConsumerStatefulWidget {
  final bool showSidebarToggle;
  final VoidCallback? onSidebarToggle;
  final bool showDebugToggle;
  final bool isDebugPanelOpen;
  final VoidCallback? onDebugToggle;

  const ChatScreen({
    super.key,
    this.showSidebarToggle = false,
    this.onSidebarToggle,
    this.showDebugToggle = false,
    this.isDebugPanelOpen = false,
    this.onDebugToggle,
  });

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _scrollCtrl = ScrollController();

  @override
  void dispose() {
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollCtrl.hasClients) {
        _scrollCtrl.animateTo(
          _scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(chatProvider);
    final msgs = provider.messages;
    final hasMessages = msgs.isNotEmpty || provider.isStreaming;

    ref.listen(chatProvider, (prev, next) {
      if (prev?.messages.length != next.messages.length ||
          prev?.streamBuffer != next.streamBuffer ||
          prev?.streamEvents.length != next.streamEvents.length) {
        _scrollToBottom();
      }
    });

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 6, 8, 8),
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1180),
              child: Row(
                children: [
                  if (widget.showSidebarToggle) ...[
                    _HeaderButton(
                      icon: Icons.menu_rounded,
                      onTap: widget.onSidebarToggle,
                    ),
                    const SizedBox(width: 10),
                  ],
                  Expanded(
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 14,
                      ),
                      decoration: AppTheme.floatingPanelDecoration(
                        radius: 24,
                        alpha: 0.72,
                      ),
                      child: Row(
                        children: [
                          Text(
                            "Single Agent Runtime",
                            style: AppTheme.ts(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const Spacer(),
                          _HealthBadge(reachable: provider.serverReachable),
                          if (widget.showDebugToggle) ...[
                            const SizedBox(width: 10),
                            _HeaderButton(
                              icon: widget.isDebugPanelOpen
                                  ? Icons.tune_rounded
                                  : Icons.developer_board_rounded,
                              active: widget.isDebugPanelOpen,
                              onTap: widget.onDebugToggle,
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
        // ── Messages area ──────────────────────────────────────────────
        Expanded(
          child: hasMessages
              ? _MessageList(
                  messages: msgs,
                  scrollCtrl: _scrollCtrl,
                  isStreaming: provider.isStreaming,
                  streamBuffer: provider.streamBuffer,
                  streamAnswerFormat: provider.streamAnswerFormat,
                  streamRenderHint: provider.streamRenderHint,
                  streamArtifacts: provider.streamArtifacts,
                  streamEvents: provider.streamEvents,
                  error: provider.error,
                  onClearError: provider.clearError,
                )
              : const _WelcomeScreen(),
        ),
        // ── Input ──────────────────────────────────────────────────────
        InputBar(
          enabled: !provider.isStreaming,
          isUploading: provider.isUploadingFile,
          isLoadingSkills: provider.isLoadingSkills,
          sessionFiles: provider.sessionFiles,
          activeFileIds: provider.activeFileIds,
          highlightedFileId: provider.recentActivatedFileId,
          availableSkills: provider.availableSkills,
          selectedSkillNames: provider.selectedSkillNames,
          maxToolRounds: provider.maxToolRounds,
          skillsError: provider.skillsError,
          onSend: (text) => provider.sendMessage(text),
          onUpload: ({required filename, required bytes}) =>
              provider.uploadSessionFile(filename: filename, bytes: bytes),
          onToggleFileActive: (file, active) =>
              provider.toggleFileActive(file.fileId, active),
          onRefreshSkills: provider.refreshSkills,
          onToggleSkill: provider.toggleSkill,
          onMaxToolRoundsChanged: provider.setMaxToolRounds,
          onResetRuntimeOptions: provider.resetRuntimeOptions,
        ),
      ],
    );
  }
}

// ── Health badge ─────────────────────────────────────────────────────────

class _HealthBadge extends StatelessWidget {
  final bool reachable;
  const _HealthBadge({required this.reachable});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: reachable
            ? AppTheme.accent.withValues(alpha: 0.15)
            : AppTheme.danger.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.circle,
              size: 7, color: reachable ? AppTheme.accent : AppTheme.danger),
          const SizedBox(width: 6),
          Text(reachable ? "在线" : "离线",
              style: AppTheme.ts(
                  fontSize: 11,
                  color: reachable ? AppTheme.accent : AppTheme.danger)),
        ],
      ),
    );
  }
}

class _HeaderButton extends StatelessWidget {
  final IconData icon;
  final bool active;
  final VoidCallback? onTap;

  const _HeaderButton({
    required this.icon,
    required this.onTap,
    this.active = false,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Container(
          width: 46,
          height: 46,
          decoration: BoxDecoration(
            color: active
                ? AppTheme.accent.withValues(alpha: 0.16)
                : AppTheme.surface.withValues(alpha: 0.78),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: active
                  ? AppTheme.accent.withValues(alpha: 0.3)
                  : AppTheme.border,
            ),
          ),
          child: Icon(
            icon,
            size: 20,
            color: active ? AppTheme.accent : AppTheme.textSecondary,
          ),
        ),
      ),
    );
  }
}

// ── Welcome screen ──────────────────────────────────────────────────────

class _WelcomeScreen extends ConsumerWidget {
  const _WelcomeScreen();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Center(
      child: Container(
        constraints: const BoxConstraints(maxWidth: 560),
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  colors: [AppTheme.accent, Color(0xFF059669)],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
                borderRadius: BorderRadius.circular(18),
                boxShadow: [
                  BoxShadow(
                    color: AppTheme.accent.withValues(alpha: 0.3),
                    blurRadius: 24,
                    offset: const Offset(0, 8),
                  ),
                ],
              ),
              child: const Center(
                child: Icon(Icons.auto_awesome_rounded,
                    size: 30, color: Colors.white),
              ),
            ),
            const SizedBox(height: 24),
            Text("Agent Runtime",
                style: AppTheme.ts(
                    fontSize: 26,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textPrimary,
                    letterSpacing: -0.5)),
            const SizedBox(height: 8),
            Text("智能对话 · 工具调用 · 记忆系统",
                style:
                    AppTheme.ts(fontSize: 14, color: AppTheme.textSecondary)),
            const SizedBox(height: 40),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              alignment: WrapAlignment.center,
              children: [
                _QuickPrompt(
                    icon: Icons.psychology_rounded,
                    text: "告诉我你的能力",
                    onSend: (t) => ref.read(chatProvider).sendMessage(t)),
                _QuickPrompt(
                    icon: Icons.code_rounded,
                    text: "帮我写一个函数",
                    onSend: (t) => ref.read(chatProvider).sendMessage(t)),
                _QuickPrompt(
                    icon: Icons.lightbulb_rounded,
                    text: "解释一个概念",
                    onSend: (t) => ref.read(chatProvider).sendMessage(t)),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _QuickPrompt extends StatelessWidget {
  final IconData icon;
  final String text;
  final Function(String) onSend;

  const _QuickPrompt({
    required this.icon,
    required this.text,
    required this.onSend,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => onSend(text),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: AppTheme.cardDecoration,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: AppTheme.accent),
              const SizedBox(width: 8),
              Text(text,
                  style:
                      AppTheme.ts(fontSize: 13, color: AppTheme.textSecondary)),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Message list ────────────────────────────────────────────────────────

class _MessageList extends StatefulWidget {
  final List<ChatMessage> messages;
  final ScrollController scrollCtrl;
  final bool isStreaming;
  final String streamBuffer;
  final String streamAnswerFormat;
  final String streamRenderHint;
  final List<AnswerArtifactView> streamArtifacts;
  final List<EventView> streamEvents;
  final String? error;
  final VoidCallback onClearError;

  const _MessageList({
    required this.messages,
    required this.scrollCtrl,
    required this.isStreaming,
    required this.streamBuffer,
    required this.streamAnswerFormat,
    required this.streamRenderHint,
    required this.streamArtifacts,
    required this.streamEvents,
    required this.error,
    required this.onClearError,
  });

  @override
  State<_MessageList> createState() => _MessageListState();
}

class _MessageListState extends State<_MessageList> {
  @override
  void didUpdateWidget(covariant _MessageList oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.messages.length != oldWidget.messages.length ||
        widget.streamBuffer != oldWidget.streamBuffer) {
      _scroll();
    }
  }

  void _scroll() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (widget.scrollCtrl.hasClients) {
        widget.scrollCtrl.animateTo(
          widget.scrollCtrl.position.maxScrollExtent,
          duration: const Duration(milliseconds: 150),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final extraItems =
        (widget.isStreaming ? 1 : 0) + (widget.error != null ? 1 : 0);
    final itemCount = widget.messages.length + extraItems;

    return ListView.builder(
      controller: widget.scrollCtrl,
      padding: const EdgeInsets.fromLTRB(18, 12, 18, 28),
      itemCount: itemCount,
      itemBuilder: (_, i) {
        Widget child;
        // Error at top
        if (widget.error != null && i == 0) {
          child = _ErrorBanner(
            message: widget.error!,
            onDismiss: widget.onClearError,
          );
        } else {
          final msgIdx = widget.error != null ? i - 1 : i;

          // Streaming bubble at the end
          if (widget.isStreaming && msgIdx == widget.messages.length) {
            child = StreamingBubble(
              buffer: widget.streamBuffer,
              answerFormat: widget.streamAnswerFormat,
              renderHint: widget.streamRenderHint,
              artifacts: widget.streamArtifacts,
              thinkingLines: _buildThinkingLines(widget.streamEvents),
            );
          } else if (msgIdx < widget.messages.length) {
            // Regular messages
            child = ChatBubble(message: widget.messages[msgIdx]);
          } else {
            child = const SizedBox.shrink();
          }
        }

        return Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: _messageRailMaxWidth),
            child: child,
          ),
        );
      },
    );
  }

  List<String> _buildThinkingLines(List<EventView> events) {
    final lines = <String>[];
    for (final e in events) {
      final time = DateFormat("HH:mm:ss").format(e.createdAt);
      switch (e.type) {
        case "run_started":
          lines.add("[$time] 开始执行任务");
          break;
        case "assistant_thinking":
          final content = (e.payload["content"] ?? "").toString();
          final short = content.length > 120
              ? "${content.substring(0, 120)}..."
              : content;
          lines.add("[$time] 模型思考: $short");
          break;
        case "tool_call":
          final name = e.payload["name"] ?? "unknown";
          lines.add("[$time] 调用工具 $name");
          break;
        case "tool_result":
          final name = e.payload["tool_name"] ?? "unknown";
          final ok = e.payload["success"] == true ? "成功" : "失败";
          lines.add("[$time] 工具$ok $name");
          break;
        case "run_finished":
          lines.add("[$time] 执行完成，正在整理答案");
          break;
      }
    }
    return lines;
  }
}

// ── Error banner ────────────────────────────────────────────────────────

class _ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback onDismiss;
  const _ErrorBanner({required this.message, required this.onDismiss});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.danger.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.danger.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded,
              size: 16, color: AppTheme.danger),
          const SizedBox(width: 10),
          Expanded(
            child: Text(message,
                style: AppTheme.ts(fontSize: 13, color: AppTheme.danger)),
          ),
          SizedBox(
            width: 24,
            height: 24,
            child: IconButton(
              padding: EdgeInsets.zero,
              iconSize: 14,
              icon: const Icon(Icons.close_rounded, color: AppTheme.danger),
              onPressed: onDismiss,
            ),
          ),
        ],
      ),
    );
  }
}
