import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:gpt_markdown/gpt_markdown.dart';

import '../../core/models/api_models.dart';
import '../theme/app_theme.dart';

const double _bubbleMaxWidth = 780;

class ChatBubble extends StatefulWidget {
  final ChatMessage message;
  final bool isStreaming;
  const ChatBubble(
      {super.key, required this.message, this.isStreaming = false});

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
          constraints: const BoxConstraints(maxWidth: _bubbleMaxWidth),
          margin: EdgeInsets.only(
            left: isUser ? 60 : 0,
            right: isUser ? 0 : 60,
            top: 6,
            bottom: 6,
          ),
          child: IntrinsicWidth(
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
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: _bubbleMaxWidth),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 12),
                    decoration: isUser
                        ? AppTheme.userBubbleDecoration
                        : AppTheme.assistantBubbleDecoration,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        if (widget.message.content.isNotEmpty)
                          _MessageBody(
                            content: widget.message.content,
                            isUser: isUser,
                            isStreaming: false,
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
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class StreamingBubble extends StatelessWidget {
  final String buffer;
  final List<String> thinkingLines;
  const StreamingBubble(
      {super.key, required this.buffer, this.thinkingLines = const []});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: _bubbleMaxWidth),
        margin: const EdgeInsets.only(top: 6, bottom: 6),
        child: IntrinsicWidth(
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
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: _bubbleMaxWidth),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 12),
                    decoration: AppTheme.assistantBubbleDecoration,
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _MessageBody(
                          content: buffer,
                          isUser: false,
                          isStreaming: true,
                        ),
                        const _Cursor(),
                      ],
                    ),
                  ),
                )
              else
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  decoration: AppTheme.assistantBubbleDecoration,
                  child: const _StreamingSkeleton(),
                ),
            ],
          ),
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

class _MessageBody extends StatelessWidget {
  final String content;
  final bool isUser;
  final bool isStreaming;

  const _MessageBody({
    required this.content,
    required this.isUser,
    required this.isStreaming,
  });

  @override
  Widget build(BuildContext context) {
    if (isUser) {
      return _PlainTextBody(content: content);
    }
    if (isStreaming) {
      return _StreamingMarkdownBody(content: content);
    }
    return _AssistantMarkdownBody(content: content);
  }
}

class _PlainTextBody extends StatelessWidget {
  final String content;

  const _PlainTextBody({required this.content});

  @override
  Widget build(BuildContext context) {
    return SelectableText(
      content,
      style: AppTheme.ts(
        fontSize: 15,
        color: AppTheme.textPrimary,
        height: 1.65,
      ),
    );
  }
}

class _AssistantMarkdownBody extends StatelessWidget {
  final String content;

  const _AssistantMarkdownBody({required this.content});

  @override
  Widget build(BuildContext context) {
    return SelectionArea(
      child: GptMarkdown(
        content,
        style: AppTheme.ts(
          fontSize: 15,
          color: AppTheme.textPrimary,
          height: 1.65,
        ),
        useDollarSignsForLatex: true,
        onLinkTap: (url, title) => _copyLink(context, url),
        codeBuilder: (context, name, code, closed) {
          return _CodeBlockCard(
            language: name,
            code: code,
            closed: closed,
          );
        },
        latexBuilder: (context, tex, textStyle, inline) {
          return _LatexBlock(
            tex: tex,
            inline: inline,
            textStyle: textStyle,
          );
        },
      ),
    );
  }

  void _copyLink(BuildContext context, String url) {
    Clipboard.setData(ClipboardData(text: url));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(url.isEmpty ? "链接为空" : "链接已复制"),
        duration: const Duration(seconds: 1),
      ),
    );
  }
}

class _StreamingMarkdownBody extends StatelessWidget {
  final String content;

  const _StreamingMarkdownBody({required this.content});

  @override
  Widget build(BuildContext context) {
    final segments = _StreamingSegmentParser.parse(content);
    if (segments.isEmpty) {
      return const SizedBox.shrink();
    }
    final children = <Widget>[];
    for (final segment in segments) {
      children.add(
        segment.isCode
            ? _CodeBlockCard(
                language: segment.language,
                code: segment.content,
                closed: segment.closed,
              )
            : _StreamingTextBlock(content: segment.content),
      );
      children.add(const SizedBox(height: 10));
    }
    if (children.isNotEmpty) {
      children.removeLast();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }
}

class _StreamingTextBlock extends StatelessWidget {
  final String content;

  const _StreamingTextBlock({required this.content});

  @override
  Widget build(BuildContext context) {
    final lines = content.split('\n');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final line in lines) _buildLine(line),
      ],
    );
  }

  Widget _buildLine(String line) {
    final trimmed = line.trimRight();
    if (trimmed.isEmpty) {
      return const SizedBox(height: 10);
    }
    if (trimmed.startsWith('### ')) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Text(
          trimmed.substring(4),
          style: AppTheme.ts(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: AppTheme.textPrimary,
            height: 1.45,
          ),
        ),
      );
    }
    if (trimmed.startsWith('## ')) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Text(
          trimmed.substring(3),
          style: AppTheme.ts(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppTheme.textPrimary,
            height: 1.45,
          ),
        ),
      );
    }
    if (trimmed.startsWith('# ')) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Text(
          trimmed.substring(2),
          style: AppTheme.ts(
            fontSize: 22,
            fontWeight: FontWeight.w800,
            color: AppTheme.textPrimary,
            height: 1.4,
          ),
        ),
      );
    }
    if (trimmed.startsWith('>')) {
      return Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.only(left: 12),
        decoration: BoxDecoration(
          border: Border(
            left: BorderSide(
              color: AppTheme.accent.withValues(alpha: 0.45),
              width: 3,
            ),
          ),
        ),
        child: SelectableText(
          trimmed.replaceFirst(RegExp(r'^>\s?'), ''),
          style: AppTheme.ts(
            fontSize: 15,
            color: AppTheme.textSecondary,
            height: 1.65,
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: SelectableText(
        trimmed,
        style: AppTheme.ts(
          fontSize: 15,
          color: AppTheme.textPrimary,
          height: 1.65,
        ),
      ),
    );
  }
}

class _StreamingSkeleton extends StatefulWidget {
  const _StreamingSkeleton();

  @override
  State<_StreamingSkeleton> createState() => _StreamingSkeletonState();
}

class _StreamingSkeletonState extends State<_StreamingSkeleton>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        final alpha = 0.22 + (_controller.value * 0.18);
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _SkeletonLine(widthFactor: 0.92, alpha: alpha),
            const SizedBox(height: 8),
            _SkeletonLine(widthFactor: 0.78, alpha: alpha * 0.9),
            const SizedBox(height: 8),
            _SkeletonLine(widthFactor: 0.56, alpha: alpha * 0.8),
          ],
        );
      },
    );
  }
}

class _SkeletonLine extends StatelessWidget {
  final double widthFactor;
  final double alpha;

  const _SkeletonLine({required this.widthFactor, required this.alpha});

  @override
  Widget build(BuildContext context) {
    return FractionallySizedBox(
      widthFactor: widthFactor,
      child: Container(
        height: 12,
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: alpha),
          borderRadius: BorderRadius.circular(999),
        ),
      ),
    );
  }
}

class _LatexBlock extends StatelessWidget {
  final String tex;
  final bool inline;
  final TextStyle textStyle;

  const _LatexBlock({
    required this.tex,
    required this.inline,
    required this.textStyle,
  });

  @override
  Widget build(BuildContext context) {
    final widget = Math.tex(
      tex,
      mathStyle: inline ? MathStyle.text : MathStyle.display,
      textStyle: textStyle.copyWith(color: AppTheme.textPrimary),
      onErrorFallback: (error) {
        return SelectableText(
          tex,
          style: textStyle.copyWith(
            color: AppTheme.textSecondary,
            fontFamily: 'monospace',
          ),
        );
      },
    );
    if (inline) {
      return widget;
    }
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: widget,
      ),
    );
  }
}

class _CodeBlockCard extends StatelessWidget {
  final String language;
  final String code;
  final bool closed;

  const _CodeBlockCard({
    required this.language,
    required this.code,
    required this.closed,
  });

  @override
  Widget build(BuildContext context) {
    final codeText = code.trimRight();
    final lines = (codeText.isEmpty ? const [''] : codeText.split('\n'));
    final lineNumbers = List<String>.generate(
      lines.length,
      (index) => '${index + 1}',
    ).join('\n');
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFF0F141B),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.04),
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(14),
              ),
              border: Border(bottom: BorderSide(color: AppTheme.border)),
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: AppTheme.surfaceActive,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    language.trim().isEmpty ? 'code' : language.trim(),
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.textSecondary,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (!closed) ...[
                  const SizedBox(width: 8),
                  Text(
                    '生成中',
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.accent,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                const Spacer(),
                _CodeCopyButton(text: codeText),
              ],
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(12, 12, 14, 14),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SelectableText(
                  lineNumbers,
                  style: AppTheme.ts(
                    fontSize: 13,
                    color: AppTheme.textTertiary,
                    height: 1.6,
                  ).copyWith(fontFamily: 'monospace'),
                ),
                Container(
                  width: 1,
                  height:
                      (lines.length * 22).toDouble().clamp(24, 1200).toDouble(),
                  margin: const EdgeInsets.symmetric(horizontal: 12),
                  color: AppTheme.border,
                ),
                SelectableText(
                  codeText,
                  style: AppTheme.ts(
                    fontSize: 13,
                    color: const Color(0xFFE6EDF3),
                    height: 1.6,
                  ).copyWith(fontFamily: 'monospace'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CodeCopyButton extends StatelessWidget {
  final String text;

  const _CodeCopyButton({required this.text});

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: () {
        Clipboard.setData(ClipboardData(text: text));
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('代码已复制'),
            duration: Duration(seconds: 1),
          ),
        );
      },
      style: TextButton.styleFrom(
        foregroundColor: AppTheme.textSecondary,
        textStyle: AppTheme.ts(fontSize: 12, fontWeight: FontWeight.w600),
      ),
      icon: const Icon(Icons.content_copy_rounded, size: 14),
      label: const Text('复制'),
    );
  }
}

class _StreamingSegment {
  final String content;
  final String language;
  final bool closed;
  final bool isCode;

  const _StreamingSegment.text(this.content)
      : language = '',
        closed = true,
        isCode = false;

  const _StreamingSegment.code({
    required this.content,
    required this.language,
    required this.closed,
  }) : isCode = true;
}

class _StreamingSegmentParser {
  static List<_StreamingSegment> parse(String raw) {
    final normalized = raw.replaceAll('\r\n', '\n');
    if (normalized.trim().isEmpty) {
      return const [];
    }
    final segments = <_StreamingSegment>[];
    final textBuffer = StringBuffer();
    final codeBuffer = StringBuffer();
    var inCode = false;
    var language = '';

    void flushText() {
      final text = textBuffer.toString().trimRight();
      if (text.isNotEmpty) {
        segments.add(_StreamingSegment.text(text));
      }
      textBuffer.clear();
    }

    for (final line in normalized.split('\n')) {
      final trimmedLeft = line.trimLeft();
      if (trimmedLeft.startsWith('```')) {
        if (inCode) {
          segments.add(
            _StreamingSegment.code(
              content: codeBuffer.toString().trimRight(),
              language: language,
              closed: true,
            ),
          );
          codeBuffer.clear();
          inCode = false;
          language = '';
        } else {
          flushText();
          inCode = true;
          language = trimmedLeft.substring(3).trim();
        }
        continue;
      }
      if (inCode) {
        codeBuffer.writeln(line);
      } else {
        textBuffer.writeln(line);
      }
    }

    if (inCode) {
      segments.add(
        _StreamingSegment.code(
          content: codeBuffer.toString().trimRight(),
          language: language,
          closed: false,
        ),
      );
    }
    flushText();
    return segments;
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

class _CursorState extends State<_Cursor> with SingleTickerProviderStateMixin {
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
