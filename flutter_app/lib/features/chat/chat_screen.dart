import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../../core/providers/theme_provider.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/widgets/chat_bubble.dart';
import '../../shared/widgets/input_bar.dart';

const double _messageRailMaxWidth = 1160;
const double _messageListTopPadding = 106;
const double _messageListBottomPadding = 280;
const double _headerDockFadeHeight = 92;
const double _composerDockFadeHeight = 132;
const double _jumpToBottomButtonBottom = 108;
const double _jumpToBottomThreshold = 140;

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
  bool _showJumpToBottom = false;

  @override
  void initState() {
    super.initState();
    _scrollCtrl.addListener(_handleScroll);
  }

  @override
  void dispose() {
    _scrollCtrl.removeListener(_handleScroll);
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _handleScroll() {
    if (!_scrollCtrl.hasClients) {
      return;
    }
    final distanceToBottom =
        _scrollCtrl.position.maxScrollExtent - _scrollCtrl.position.pixels;
    final nextShow = distanceToBottom > _jumpToBottomThreshold;
    if (nextShow != _showJumpToBottom && mounted) {
      setState(() {
        _showJumpToBottom = nextShow;
      });
    }
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
    final hasMessages = ref.watch(
      chatProvider.select((provider) {
        return provider.isStreaming || provider.messages.isNotEmpty;
      }),
    );

    ref.listen<(int, int)>(
      chatProvider.select((provider) {
        return (provider.messages.length, provider.streamBuffer.length);
      }),
      (previous, next) {
        if (previous != next) {
          _scrollToBottom();
        }
      },
    );

    return Stack(
      children: [
        Positioned.fill(
          child: hasMessages
              ? _ChatMessageLayer(scrollCtrl: _scrollCtrl)
              : const _WelcomeScreen(),
        ),
        Positioned(
          left: 0,
          right: 0,
          top: 0,
          child: _ChatHeaderLayer(
            showSidebarToggle: widget.showSidebarToggle,
            onSidebarToggle: widget.onSidebarToggle,
            showDebugToggle: widget.showDebugToggle,
            isDebugPanelOpen: widget.isDebugPanelOpen,
            onDebugToggle: widget.onDebugToggle,
          ),
        ),
        if (hasMessages)
          Positioned(
            left: 0,
            right: 0,
            bottom: _jumpToBottomButtonBottom,
            child: IgnorePointer(
              ignoring: !_showJumpToBottom,
              child: AnimatedOpacity(
                duration: const Duration(milliseconds: 180),
                opacity: _showJumpToBottom ? 1 : 0,
                child: Center(
                  child: ConstrainedBox(
                    constraints:
                        const BoxConstraints(maxWidth: _messageRailMaxWidth),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        Padding(
                          padding: const EdgeInsets.only(right: 28),
                          child: _JumpToBottomButton(
                            onTap: _scrollToBottom,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: const _ChatComposerLayer(),
        ),
      ],
    );
  }
}

class _ChatHeaderLayer extends ConsumerWidget {
  final bool showSidebarToggle;
  final VoidCallback? onSidebarToggle;
  final bool showDebugToggle;
  final bool isDebugPanelOpen;
  final VoidCallback? onDebugToggle;

  const _ChatHeaderLayer({
    required this.showSidebarToggle,
    required this.onSidebarToggle,
    required this.showDebugToggle,
    required this.isDebugPanelOpen,
    required this.onDebugToggle,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final reachable = ref.watch(
      chatProvider.select((provider) => provider.serverReachable),
    );
    final themeMode = ref.watch(themeModeProvider);
    final isDarkMode = themeMode == ThemeMode.dark;

    return _HeaderDock(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 0),
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1180),
            child: Row(
              children: [
                if (showSidebarToggle) ...[
                  _HeaderButton(
                    icon: Icons.menu_rounded,
                    onTap: onSidebarToggle,
                  ),
                  const SizedBox(width: 10),
                ],
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 10,
                    ),
                    decoration: AppTheme.floatingPanelDecoration(
                      radius: 22,
                      alpha: AppTheme.isDark ? 0.66 : 0.56,
                    ),
                    child: Row(
                      children: [
                        Text(
                          "Single Agent Runtime",
                          style: AppTheme.ts(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w700,
                            color: AppTheme.textPrimary,
                          ),
                        ),
                        const Spacer(),
                        _HealthBadge(reachable: reachable),
                        if (showDebugToggle) ...[
                          const SizedBox(width: 8),
                          _HeaderButton(
                            icon: isDebugPanelOpen
                                ? Icons.tune_rounded
                                : Icons.developer_board_rounded,
                            active: isDebugPanelOpen,
                            onTap: onDebugToggle,
                          ),
                        ],
                        const SizedBox(width: 8),
                        _HeaderButton(
                          icon: isDarkMode
                              ? Icons.light_mode_rounded
                              : Icons.dark_mode_rounded,
                          tooltip: isDarkMode ? '切换浅色主题' : '切换深色主题',
                          onTap: () =>
                              ref.read(themeModeProvider.notifier).toggle(),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ChatMessageLayer extends ConsumerWidget {
  final ScrollController scrollCtrl;

  const _ChatMessageLayer({required this.scrollCtrl});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = ref.watch(chatProvider);
    return _MessageList(
      messages: provider.messages,
      scrollCtrl: scrollCtrl,
      isStreaming: provider.isStreaming,
      streamBuffer: provider.streamBuffer,
      streamAnswerFormat: provider.streamAnswerFormat,
      streamRenderHint: provider.streamRenderHint,
      streamLayoutHint: provider.streamLayoutHint,
      streamArtifacts: provider.streamArtifacts,
      streamEvents: provider.streamEvents,
      error: provider.error,
      onClearError: provider.clearError,
    );
  }
}

class _ChatComposerLayer extends ConsumerWidget {
  const _ChatComposerLayer();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final viewModel = ref.watch(
      chatProvider.select(_ComposerViewModel.fromProvider),
    );
    final provider = ref.read(chatProvider);

    return _ComposerDock(
      child: InputBar(
        enabled: viewModel.enabled,
        isUploading: viewModel.isUploading,
        isLoadingSkills: viewModel.isLoadingSkills,
        sessionFiles: viewModel.sessionFiles,
        activeFileIds: viewModel.activeFileIds,
        highlightedFileId: viewModel.highlightedFileId,
        availableSkills: viewModel.availableSkills,
        selectedSkillNames: viewModel.selectedSkillNames,
        maxToolRounds: viewModel.maxToolRounds,
        skillsError: viewModel.skillsError,
        onSend: (text) => provider.sendMessage(text),
        onUpload: ({required filename, required bytes}) => provider
            .uploadSessionFile(filename: filename, bytes: bytes),
        onToggleFileActive: (file, active) =>
            provider.toggleFileActive(file.fileId, active),
        onRefreshSkills: provider.refreshSkills,
        onToggleSkill: provider.toggleSkill,
        onMaxToolRoundsChanged: provider.setMaxToolRounds,
        onResetRuntimeOptions: provider.resetRuntimeOptions,
      ),
    );
  }
}

class _JumpToBottomButton extends StatelessWidget {
  final VoidCallback onTap;

  const _JumpToBottomButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.94),
            shape: BoxShape.circle,
            border:
                Border.all(color: AppTheme.borderLight.withValues(alpha: 0.8)),
            boxShadow: [
              BoxShadow(
                color: Colors.black
                    .withValues(alpha: AppTheme.isDark ? 0.14 : 0.08),
                blurRadius: 18,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Icon(
            Icons.keyboard_double_arrow_down_rounded,
            size: 20,
            color: AppTheme.textSecondary,
          ),
        ),
      ),
    );
  }
}

class _HeaderDock extends StatelessWidget {
  final Widget child;

  const _HeaderDock({required this.child});

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        child,
        IgnorePointer(
          child: SizedBox(
            height: _headerDockFadeHeight,
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.9 : 0.8),
                    AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.74 : 0.6),
                    AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.42 : 0.28),
                    AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.14 : 0.08),
                    AppTheme.bg.withValues(alpha: 0),
                  ],
                  stops: const [0, 0.18, 0.42, 0.74, 1],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _ComposerViewModel {
  final bool enabled;
  final bool isUploading;
  final bool isLoadingSkills;
  final List<SessionFileView> sessionFiles;
  final List<String> activeFileIds;
  final String? highlightedFileId;
  final List<SkillOption> availableSkills;
  final List<String> selectedSkillNames;
  final int maxToolRounds;
  final String? skillsError;

  const _ComposerViewModel({
    required this.enabled,
    required this.isUploading,
    required this.isLoadingSkills,
    required this.sessionFiles,
    required this.activeFileIds,
    required this.highlightedFileId,
    required this.availableSkills,
    required this.selectedSkillNames,
    required this.maxToolRounds,
    required this.skillsError,
  });

  factory _ComposerViewModel.fromProvider(ChatProvider provider) {
    return _ComposerViewModel(
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
    );
  }

  @override
  bool operator ==(Object other) {
    return other is _ComposerViewModel &&
        other.enabled == enabled &&
        other.isUploading == isUploading &&
        other.isLoadingSkills == isLoadingSkills &&
        other.highlightedFileId == highlightedFileId &&
        other.maxToolRounds == maxToolRounds &&
        other.skillsError == skillsError &&
        _stringListEquals(other.activeFileIds, activeFileIds) &&
        _sessionFileListEquals(other.sessionFiles, sessionFiles) &&
        _skillOptionListEquals(other.availableSkills, availableSkills) &&
        _stringListEquals(other.selectedSkillNames, selectedSkillNames);
  }

  @override
  int get hashCode => Object.hash(
        enabled,
        isUploading,
        isLoadingSkills,
        highlightedFileId,
        maxToolRounds,
        skillsError,
        activeFileIds.length,
        sessionFiles.length,
        availableSkills.length,
        selectedSkillNames.length,
      );
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
          const SizedBox(width: 5),
          Text(reachable ? "在线" : "离线",
              style: AppTheme.ts(
                  fontSize: 10.5,
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
  final String? tooltip;

  const _HeaderButton({
    required this.icon,
    required this.onTap,
    this.active = false,
    this.tooltip,
  });

  @override
  Widget build(BuildContext context) {
    final button = Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            color: active
                ? AppTheme.accent.withValues(alpha: 0.16)
                : AppTheme.surface.withValues(alpha: 0.72),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: active
                  ? AppTheme.accent.withValues(alpha: 0.3)
                  : AppTheme.border,
            ),
          ),
          child: Icon(
            icon,
            size: 18,
            color: active ? AppTheme.accent : AppTheme.textSecondary,
          ),
        ),
      ),
    );
    if (tooltip == null || tooltip!.isEmpty) {
      return button;
    }
    return Tooltip(message: tooltip!, child: button);
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
                gradient: LinearGradient(
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
  final String streamLayoutHint;
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
    required this.streamLayoutHint,
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
  Widget build(BuildContext context) {
    final extraItems =
        (widget.isStreaming ? 1 : 0) + (widget.error != null ? 1 : 0);
    final itemCount = widget.messages.length + extraItems;

    return ListView.builder(
      controller: widget.scrollCtrl,
      padding: const EdgeInsets.fromLTRB(
        18,
        _messageListTopPadding,
        18,
        _messageListBottomPadding,
      ),
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
              layoutHint: widget.streamLayoutHint,
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

bool _stringListEquals(List<String> left, List<String> right) {
  if (identical(left, right)) {
    return true;
  }
  if (left.length != right.length) {
    return false;
  }
  for (var index = 0; index < left.length; index++) {
    if (left[index] != right[index]) {
      return false;
    }
  }
  return true;
}

bool _skillOptionListEquals(List<SkillOption> left, List<SkillOption> right) {
  if (identical(left, right)) {
    return true;
  }
  if (left.length != right.length) {
    return false;
  }
  for (var index = 0; index < left.length; index++) {
    if (left[index].name != right[index].name ||
        left[index].description != right[index].description) {
      return false;
    }
  }
  return true;
}

bool _sessionFileListEquals(
  List<SessionFileView> left,
  List<SessionFileView> right,
) {
  if (identical(left, right)) {
    return true;
  }
  if (left.length != right.length) {
    return false;
  }
  for (var index = 0; index < left.length; index++) {
    final leftItem = left[index];
    final rightItem = right[index];
    if (leftItem.fileId != rightItem.fileId ||
        leftItem.filename != rightItem.filename ||
        leftItem.mediaType != rightItem.mediaType ||
        leftItem.sizeBytes != rightItem.sizeBytes ||
        leftItem.status != rightItem.status ||
        leftItem.error != rightItem.error ||
        leftItem.parsedCharCount != rightItem.parsedCharCount ||
        leftItem.parsedTokenEstimate != rightItem.parsedTokenEstimate ||
        leftItem.uploadedAt != rightItem.uploadedAt) {
      return false;
    }
  }
  return true;
}

class _ComposerDock extends StatelessWidget {
  final Widget child;

  const _ComposerDock({required this.child});

  @override
  Widget build(BuildContext context) {
    return Stack(
      clipBehavior: Clip.none,
      children: [
        IgnorePointer(
          child: SizedBox(
            height: _composerDockFadeHeight,
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    AppTheme.bg.withValues(alpha: 0),
                    AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.2 : 0.12),
                    AppTheme.bg
                        .withValues(alpha: AppTheme.isDark ? 0.78 : 0.64),
                    AppTheme.bg
                        .withValues(alpha: AppTheme.isDark ? 0.96 : 0.92),
                  ],
                  stops: const [0, 0.32, 0.72, 1],
                ),
              ),
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Container(
                  width: 280,
                  height: 1,
                  margin: const EdgeInsets.only(bottom: 74),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [
                        AppTheme.border.withValues(alpha: 0),
                        AppTheme.borderLight.withValues(alpha: 0.55),
                        AppTheme.border.withValues(alpha: 0),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
        child,
      ],
    );
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
          Icon(Icons.error_outline_rounded, size: 16, color: AppTheme.danger),
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
              icon: Icon(Icons.close_rounded, color: AppTheme.danger),
              onPressed: onDismiss,
            ),
          ),
        ],
      ),
    );
  }
}
