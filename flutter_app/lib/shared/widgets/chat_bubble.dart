import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../../core/models/api_models.dart';
import '../theme/app_theme.dart';

class ChatBubble extends StatefulWidget {
  final ChatMessage message;
  final bool isStreaming;
  const ChatBubble({super.key, required this.message, this.isStreaming = false});

  @override
  State<ChatBubble> createState() => _ChatBubbleState();
}

class _ChatBubbleState extends State<ChatBubble> {
  bool _hovering = false;

  @override
  Widget build(BuildContext context) {
    final isUser = widget.message.isUser;
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovering = true),
        onExit: (_) => setState(() => _hovering = false),
        child: Container(
          constraints: const BoxConstraints(maxWidth: 780),
          margin: EdgeInsets.only(
            left: isUser ? 60 : 0,
            right: isUser ? 0 : 60,
            top: 6,
            bottom: 6,
          ),
          child: Column(
            crossAxisAlignment:
                isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(bottom: 6, left: 4, right: 4),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _Avatar(isUser: isUser),
                    const SizedBox(width: 8),
                    Text(
                      isUser ? "你" : "Assistant",
                      style: AppTheme.ts(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.textSecondary),
                    ),
                    if (_hovering && !isUser) ...[
                      const SizedBox(width: 8),
                      _CopyButton(text: widget.message.content),
                    ],
                  ],
                ),
              ),
              Container(
                width: double.infinity,
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: isUser
                    ? AppTheme.userBubbleDecoration
                    : AppTheme.assistantBubbleDecoration,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (widget.message.content.isNotEmpty)
                      _MarkdownBody(
                        content: widget.message.content,
                        isUser: isUser,
                      ),
                    if (widget.isStreaming) const _Cursor(),
                    if (widget.message.toolCalls.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      ...widget.message.toolCalls
                          .map((tc) => _ToolCallChip(toolCall: tc)),
                    ],
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

class StreamingBubble extends StatelessWidget {
  final String buffer;
  final List<String> thinkingLines;
  const StreamingBubble({super.key, required this.buffer, this.thinkingLines = const []});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 780),
        margin: const EdgeInsets.only(top: 6, bottom: 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Padding(
              padding: const EdgeInsets.only(bottom: 6, left: 4),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const _Avatar(isUser: false),
                  const SizedBox(width: 8),
                  Text(
                    "Assistant",
                    style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.textSecondary),
                  ),
                  if (buffer.isEmpty) ...[
                    const SizedBox(width: 8),
                    Text("输出中...",
                        style: AppTheme.ts(
                            fontSize: 11, color: AppTheme.textTertiary)),
                  ],
                ],
              ),
            ),
            // Thinking section (collapsible)
            if (thinkingLines.isNotEmpty)
              _ThinkingBlock(lines: thinkingLines),
            // Content
            if (buffer.isNotEmpty)
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: AppTheme.assistantBubbleDecoration,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _MarkdownBody(content: buffer, isUser: false),
                    const _Cursor(),
                  ],
                ),
              )
            else
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: AppTheme.assistantBubbleDecoration,
                child: const _Cursor(),
              ),
          ],
        ),
      ),
    );
  }
}

// ── Thinking block (collapsible) ────────────────────────────────────────

class _ThinkingBlock extends StatefulWidget {
  final List<String> lines;
  const _ThinkingBlock({required this.lines});

  @override
  State<_ThinkingBlock> createState() => _ThinkingBlockState();
}

class _ThinkingBlockState extends State<_ThinkingBlock> {
  bool _expanded = true;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: AppTheme.surfaceActive.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: [
                  Icon(
                    _expanded
                        ? Icons.expand_more_rounded
                        : Icons.chevron_right_rounded,
                    size: 16,
                    color: AppTheme.textTertiary,
                  ),
                  const SizedBox(width: 4),
                  Text("执行过程",
                      style: AppTheme.ts(
                          fontSize: 12,
                          fontWeight: FontWeight.w500,
                          color: AppTheme.textTertiary)),
                  const Spacer(),
                  Text("${widget.lines.length} 条",
                      style: AppTheme.ts(
                          fontSize: 11, color: AppTheme.textTertiary)),
                ],
              ),
            ),
          ),
          if (_expanded)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: widget.lines
                    .map((l) => Padding(
                          padding: const EdgeInsets.only(bottom: 2),
                          child: Text(l,
                              style: AppTheme.ts(
                                  fontSize: 11,
                                  color: AppTheme.textSecondary,
                                  height: 1.4)),
                        ))
                    .toList(),
              ),
            ),
        ],
      ),
    );
  }
}

class _Avatar extends StatelessWidget {
  final bool isUser;
  const _Avatar({required this.isUser});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 26,
      height: 26,
      decoration: BoxDecoration(
        color: isUser ? const Color(0xFF6366F1) : AppTheme.accent,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Center(
        child: Icon(
          isUser ? Icons.person_rounded : Icons.auto_awesome_rounded,
          size: 15,
          color: Colors.white,
        ),
      ),
    );
  }
}

class _CopyButton extends StatelessWidget {
  final String text;
  const _CopyButton({required this.text});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 24,
      height: 24,
      child: IconButton(
        padding: EdgeInsets.zero,
        iconSize: 14,
        icon: const Icon(Icons.copy_rounded, color: AppTheme.textTertiary),
        onPressed: () {
          Clipboard.setData(ClipboardData(text: text));
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text("已复制"), duration: Duration(seconds: 1)),
          );
        },
      ),
    );
  }
}

class _MarkdownBody extends StatelessWidget {
  final String content;
  final bool isUser;
  const _MarkdownBody({required this.content, required this.isUser});

  @override
  Widget build(BuildContext context) {
    return MarkdownBody(
      data: content,
      selectable: true,
      styleSheet: MarkdownStyleSheet(
        p: AppTheme.ts(fontSize: 15, color: AppTheme.textPrimary, height: 1.65),
        code: TextStyle(
          fontFamily: 'monospace',
          fontSize: 13,
          color: AppTheme.accent,
          backgroundColor: AppTheme.surfaceActive,
        ),
        codeblockDecoration: BoxDecoration(
          color: const Color(0xFF111111),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppTheme.border),
        ),
        codeblockPadding: const EdgeInsets.all(14),
        h1: AppTheme.ts(
            fontSize: 22, fontWeight: FontWeight.w700, color: AppTheme.textPrimary),
        h2: AppTheme.ts(
            fontSize: 18, fontWeight: FontWeight.w600, color: AppTheme.textPrimary),
        h3: AppTheme.ts(
            fontSize: 16, fontWeight: FontWeight.w600, color: AppTheme.textPrimary),
        blockquoteDecoration: BoxDecoration(
          border: Border(
            left: BorderSide(
                color: AppTheme.accent.withValues(alpha: 0.5), width: 3),
          ),
        ),
        blockquotePadding:
            const EdgeInsets.only(left: 14, top: 4, bottom: 4),
        listBullet:
            AppTheme.ts(fontSize: 15, color: AppTheme.textSecondary),
        a: AppTheme.ts(fontSize: 15, color: AppTheme.accent),
      ),
    );
  }
}

class _ToolCallChip extends StatelessWidget {
  final ToolCallView toolCall;
  const _ToolCallChip({required this.toolCall});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 4),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: AppTheme.surfaceActive,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.build_rounded, size: 13, color: AppTheme.accent),
          const SizedBox(width: 6),
          Text(
            toolCall.name,
            style: TextStyle(
              fontFamily: 'monospace',
              fontSize: 12,
              color: AppTheme.accent,
              fontWeight: FontWeight.w500,
            ),
          ),
        ],
      ),
    );
  }
}

class _Cursor extends StatefulWidget {
  const _Cursor();
  @override
  State<_Cursor> createState() => _CursorState();
}

class _CursorState extends State<_Cursor>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, __) => Container(
        width: 7,
        height: 17,
        margin: const EdgeInsets.only(left: 2),
        decoration: BoxDecoration(
          color: AppTheme.accent.withValues(alpha: _ctrl.value),
          borderRadius: BorderRadius.circular(1),
        ),
      ),
    );
  }
}

class AnimatedBuilder extends AnimatedWidget {
  final Widget Function(BuildContext, Widget?) builder;
  const AnimatedBuilder({
    super.key,
    required Animation<double> animation,
    required this.builder,
  }) : super(listenable: animation);

  @override
  Widget build(BuildContext context) => builder(context, null);
}
