import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gpt_markdown/gpt_markdown.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
import '../theme/app_theme.dart';

const double _bubbleMaxWidth = 780;
const int _richMarkdownMaxChars = 6000;
const int _richMarkdownMaxLines = 160;
const int _streamStructuredMaxChars = 3200;
const int _streamStructuredMaxLines = 90;
const int _richMarkdownMaxCodeFences = 4;
const int _largeMessageChunkChars = 1600;
const int _streamingTailPreviewChars = 2200;
const int _autoCollapseCodeLines = 40;
const int _collapsedCodePreviewLines = 24;
const double _streamingSkeletonWidth = 280;

enum _MessageRenderMode {
  plainText,
  markdownRendered,
  markdownStructured,
  markdownSource,
  codeBlock,
  largePreview,
}

class _ResolvedMessageContent {
  final String content;
  final _MessageRenderMode mode;

  const _ResolvedMessageContent({
    required this.content,
    required this.mode,
  });
}

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
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  decoration: isUser
                      ? AppTheme.userBubbleDecoration
                      : AppTheme.assistantBubbleDecoration,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (widget.message.content.isNotEmpty)
                        RepaintBoundary(
                          child: _MessageBody(
                            content: widget.message.content,
                            isUser: isUser,
                            isStreaming: false,
                            answerFormat: widget.message.answerFormat,
                            renderHint: widget.message.renderHint,
                            layoutHint: widget.message.layoutHint,
                          ),
                        ),
                      if (widget.message.artifacts.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        _ArtifactList(artifacts: widget.message.artifacts),
                      ],
                      if (widget.isStreaming) const _Cursor(),
                    ],
                  ),
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
  final String? answerFormat;
  final String? renderHint;
  final String? layoutHint;
  final List<AnswerArtifactView> artifacts;
  final List<String> thinkingLines;
  const StreamingBubble(
      {super.key,
      required this.buffer,
      this.answerFormat,
      this.renderHint,
      this.layoutHint,
      this.artifacts = const [],
      this.thinkingLines = const []});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: _bubbleMaxWidth),
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
            if (thinkingLines.isNotEmpty) _ThinkingBlock(lines: thinkingLines),
            // Content
            if (buffer.isNotEmpty)
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: _bubbleMaxWidth),
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  decoration: AppTheme.assistantBubbleDecoration,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      RepaintBoundary(
                        child: _MessageBody(
                          content: buffer,
                          isUser: false,
                          isStreaming: true,
                          answerFormat: answerFormat,
                          renderHint: renderHint,
                          layoutHint: layoutHint,
                        ),
                      ),
                      if (artifacts.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        _ArtifactList(artifacts: artifacts),
                      ],
                      const _Cursor(),
                    ],
                  ),
                ),
              )
            else
              Container(
                width: _streamingSkeletonWidth,
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                decoration: AppTheme.assistantBubbleDecoration,
                child: const _StreamingSkeleton(),
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
        icon: Icon(Icons.copy_rounded, color: AppTheme.textTertiary),
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
  final String? answerFormat;
  final String? renderHint;
  final String? layoutHint;

  const _MessageBody({
    required this.content,
    required this.isUser,
    required this.isStreaming,
    this.answerFormat,
    this.renderHint,
    this.layoutHint,
  });

  @override
  Widget build(BuildContext context) {
    if (isUser) {
      return _PlainTextBody(
        content: content,
        enhanceFormatting: false,
      );
    }
    final resolved = _resolveMessageContent(
      content,
      isStreaming: isStreaming,
      answerFormat: answerFormat,
      renderHint: renderHint,
      layoutHint: layoutHint,
    );
    if (isStreaming) {
      switch (resolved.mode) {
        case _MessageRenderMode.markdownRendered:
          return _StreamingMarkdownBody(content: resolved.content);
        case _MessageRenderMode.markdownStructured:
          return _StructuredMarkdownBody(content: resolved.content);
        case _MessageRenderMode.markdownSource:
          return _StructuredSourceBody(content: resolved.content);
        case _MessageRenderMode.codeBlock:
          return _SingleCodeBlockBody(content: resolved.content);
        case _MessageRenderMode.largePreview:
          return _LargeStreamingPreview(content: resolved.content);
        case _MessageRenderMode.plainText:
          return _PlainTextBody(
            content: resolved.content,
            layoutHint: layoutHint ?? 'paragraph',
          );
      }
    }
    switch (resolved.mode) {
      case _MessageRenderMode.markdownRendered:
        return _AssistantMarkdownBody(content: resolved.content);
      case _MessageRenderMode.markdownStructured:
        return _StructuredMarkdownBody(content: resolved.content);
      case _MessageRenderMode.markdownSource:
        return _StructuredSourceBody(content: resolved.content);
      case _MessageRenderMode.codeBlock:
        return _SingleCodeBlockBody(content: resolved.content);
      case _MessageRenderMode.largePreview:
        return _LargeMessagePreview(content: resolved.content);
      case _MessageRenderMode.plainText:
        return _PlainTextBody(
          content: resolved.content,
          layoutHint: layoutHint ?? 'paragraph',
        );
    }
  }
}

class _PlainTextBody extends StatelessWidget {
  final String content;
  final bool enhanceFormatting;
  final String layoutHint;

  const _PlainTextBody({
    required this.content,
    this.enhanceFormatting = true,
    this.layoutHint = 'paragraph',
  });

  @override
  Widget build(BuildContext context) {
    final baseStyle = AppTheme.ts(
      fontSize: 15,
      color: AppTheme.textPrimary,
      height: 1.65,
    );
    final normalizedContent =
        enhanceFormatting ? _normalizePlainAnswerContent(content) : content;
    final paragraphs = normalizedContent
        .split(RegExp(r'\n\s*\n'))
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    if (!enhanceFormatting) {
      return SelectableText(
        normalizedContent,
        style: baseStyle,
      );
    }
    if (paragraphs.isEmpty) {
      return SelectableText('', style: baseStyle);
    }
    if (layoutHint == 'brief') {
      return SelectableText.rich(
        TextSpan(
          style: baseStyle.copyWith(
            fontSize: 16,
            fontWeight: FontWeight.w500,
            height: 1.75,
          ),
          children: _buildPlainInlineSpans(
            paragraphs.join('\n\n'),
            baseStyle.copyWith(
              fontSize: 16,
              fontWeight: FontWeight.w500,
              height: 1.75,
            ),
          ),
        ),
      );
    }
    if (layoutHint == 'bullets') {
      return _PlainBulletList(
        content: normalizedContent,
        baseStyle: baseStyle,
      );
    }
    if (layoutHint == 'steps') {
      return _PlainStepList(
        content: normalizedContent,
        baseStyle: baseStyle,
      );
    }
    final structured = _parseStructuredPlainAnswer(normalizedContent);
    if (structured != null) {
      return _StructuredPlainAnswerBody(
        parsed: structured,
        baseStyle: baseStyle,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var index = 0; index < paragraphs.length; index++) ...[
          SelectableText.rich(
            TextSpan(
              style: baseStyle,
              children: _buildPlainInlineSpans(
                paragraphs[index],
                baseStyle,
              ),
            ),
          ),
          if (index < paragraphs.length - 1) const SizedBox(height: 10),
        ],
      ],
    );
  }
}

class _StructuredPlainAnswer {
  final List<String> introParagraphs;
  final List<_StructuredPlainSection> sections;
  final String? callToAction;

  const _StructuredPlainAnswer({
    required this.introParagraphs,
    required this.sections,
    required this.callToAction,
  });
}

class _StructuredPlainSection {
  final String title;
  final List<_StructuredPlainField> fields;
  final List<String> listItems;
  final String? bodyText;

  const _StructuredPlainSection({
    required this.title,
    this.fields = const [],
    this.listItems = const [],
    this.bodyText,
  });
}

class _StructuredPlainField {
  final String label;
  final String content;

  const _StructuredPlainField({
    required this.label,
    required this.content,
  });
}

class _StructuredPlainAnswerBody extends StatelessWidget {
  final _StructuredPlainAnswer parsed;
  final TextStyle baseStyle;

  const _StructuredPlainAnswerBody({
    required this.parsed,
    required this.baseStyle,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var index = 0; index < parsed.introParagraphs.length; index++) ...[
          SelectableText.rich(
            TextSpan(
              style: baseStyle,
              children: _buildPlainInlineSpans(
                parsed.introParagraphs[index],
                baseStyle,
              ),
            ),
          ),
          const SizedBox(height: 12),
        ],
        for (var index = 0; index < parsed.sections.length; index++) ...[
          _StructuredPlainSectionCard(
            section: parsed.sections[index],
            baseStyle: baseStyle,
          ),
          if (index < parsed.sections.length - 1 || parsed.callToAction != null)
            const SizedBox(height: 12),
        ],
        if (parsed.callToAction != null)
          _PlainCallToActionCard(
            content: parsed.callToAction!,
            baseStyle: baseStyle,
          ),
      ],
    );
  }
}

class _StructuredPlainSectionCard extends StatelessWidget {
  final _StructuredPlainSection section;
  final TextStyle baseStyle;

  const _StructuredPlainSectionCard({
    required this.section,
    required this.baseStyle,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.56),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SelectableText.rich(
            TextSpan(
              style: baseStyle.copyWith(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                height: 1.5,
              ),
              children: _buildPlainInlineSpans(
                section.title,
                baseStyle.copyWith(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  height: 1.5,
                ),
              ),
            ),
          ),
          if (section.fields.isNotEmpty ||
              section.listItems.isNotEmpty ||
              (section.bodyText?.isNotEmpty ?? false))
            const SizedBox(height: 12),
          if (section.fields.isNotEmpty) ...[
            for (var index = 0; index < section.fields.length; index++) ...[
              _StructuredPlainFieldRow(
                field: section.fields[index],
                baseStyle: baseStyle,
              ),
              if (index < section.fields.length - 1) const SizedBox(height: 10),
            ],
          ],
          if (section.fields.isNotEmpty &&
              (section.listItems.isNotEmpty ||
                  (section.bodyText?.isNotEmpty ?? false)))
            const SizedBox(height: 12),
          if (section.listItems.isNotEmpty) ...[
            for (var index = 0; index < section.listItems.length; index++) ...[
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 22,
                    height: 22,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: AppTheme.accent.withValues(alpha: 0.14),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      '${index + 1}',
                      style: AppTheme.ts(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.accent,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: SelectableText.rich(
                      TextSpan(
                        style: baseStyle,
                        children: _buildPlainInlineSpans(
                          section.listItems[index],
                          baseStyle,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              if (index < section.listItems.length - 1)
                const SizedBox(height: 10),
            ],
          ],
          if (section.listItems.isNotEmpty &&
              (section.bodyText?.isNotEmpty ?? false))
            const SizedBox(height: 12),
          if (section.bodyText?.isNotEmpty ?? false)
            SelectableText.rich(
              TextSpan(
                style: baseStyle,
                children:
                    _buildPlainInlineSpans(section.bodyText ?? '', baseStyle),
              ),
            ),
        ],
      ),
    );
  }
}

class _StructuredPlainFieldRow extends StatelessWidget {
  final _StructuredPlainField field;
  final TextStyle baseStyle;

  const _StructuredPlainFieldRow({
    required this.field,
    required this.baseStyle,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
          decoration: BoxDecoration(
            color: AppTheme.surfaceActive,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: AppTheme.border),
          ),
          child: Text(
            field.label,
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: AppTheme.textSecondary,
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: SelectableText.rich(
            TextSpan(
              style: baseStyle,
              children: _buildPlainInlineSpans(field.content, baseStyle),
            ),
          ),
        ),
      ],
    );
  }
}

class _PlainCallToActionCard extends StatelessWidget {
  final String content;
  final TextStyle baseStyle;

  const _PlainCallToActionCard({
    required this.content,
    required this.baseStyle,
  });

  @override
  Widget build(BuildContext context) {
    final emphasisStyle = baseStyle.copyWith(
      fontWeight: FontWeight.w600,
      height: 1.7,
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.22)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: EdgeInsets.only(top: 2),
            child: Icon(
              Icons.arrow_forward_rounded,
              size: 16,
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: SelectableText.rich(
              TextSpan(
                style: emphasisStyle,
                children: _buildPlainInlineSpans(content, emphasisStyle),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PlainBulletList extends StatelessWidget {
  final String content;
  final TextStyle baseStyle;

  const _PlainBulletList({
    required this.content,
    required this.baseStyle,
  });

  @override
  Widget build(BuildContext context) {
    final items = _extractPlainListItems(content);
    if (items.items.isEmpty) {
      return _PlainTextBody(
        content: content,
        layoutHint: 'paragraph',
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (items.leadText != null) ...[
          SelectableText.rich(
            TextSpan(
              style: baseStyle,
              children: _buildPlainInlineSpans(items.leadText!, baseStyle),
            ),
          ),
          const SizedBox(height: 10),
        ],
        for (var index = 0; index < items.items.length; index++) ...[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Container(
                  width: 6,
                  height: 6,
                  decoration: BoxDecoration(
                    color: AppTheme.accent,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: SelectableText.rich(
                  TextSpan(
                    style: baseStyle,
                    children:
                        _buildPlainInlineSpans(items.items[index], baseStyle),
                  ),
                ),
              ),
            ],
          ),
          if (index < items.items.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _PlainStepList extends StatelessWidget {
  final String content;
  final TextStyle baseStyle;

  const _PlainStepList({
    required this.content,
    required this.baseStyle,
  });

  @override
  Widget build(BuildContext context) {
    final items = _extractPlainListItems(content);
    if (items.items.isEmpty) {
      return _PlainTextBody(
        content: content,
        layoutHint: 'paragraph',
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (items.leadText != null) ...[
          SelectableText.rich(
            TextSpan(
              style: baseStyle,
              children: _buildPlainInlineSpans(items.leadText!, baseStyle),
            ),
          ),
          const SizedBox(height: 10),
        ],
        for (var index = 0; index < items.items.length; index++) ...[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 24,
                height: 24,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.24),
                  ),
                ),
                child: Text(
                  '${index + 1}',
                  style: AppTheme.ts(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.accent,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(top: 1),
                  child: SelectableText.rich(
                    TextSpan(
                      style: baseStyle,
                      children:
                          _buildPlainInlineSpans(items.items[index], baseStyle),
                    ),
                  ),
                ),
              ),
            ],
          ),
          if (index < items.items.length - 1) const SizedBox(height: 10),
        ],
      ],
    );
  }
}

class _AssistantMarkdownBody extends StatelessWidget {
  final String content;

  const _AssistantMarkdownBody({required this.content});

  @override
  Widget build(BuildContext context) {
    final enableLatex = _looksLikeLatex(content);
    return GptMarkdown(
      content,
      style: AppTheme.ts(
        fontSize: 15,
        color: AppTheme.textPrimary,
        height: 1.65,
      ),
      useDollarSignsForLatex: enableLatex,
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

class _StructuredMarkdownBody extends StatelessWidget {
  final String content;

  const _StructuredMarkdownBody({required this.content});

  @override
  Widget build(BuildContext context) {
    final segments = _StreamingSegmentParser.parse(content);
    if (segments.isEmpty) {
      return _PlainTextBody(content: content);
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

class _StreamingMarkdownBody extends StatelessWidget {
  final String content;

  const _StreamingMarkdownBody({required this.content});

  @override
  Widget build(BuildContext context) {
    if (_shouldDegradeStreamingMarkdown(content)) {
      return _LargeStreamingPreview(content: content);
    }
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

class _LargeMessagePreview extends StatelessWidget {
  final String content;

  const _LargeMessagePreview({
    required this.content,
  });

  @override
  Widget build(BuildContext context) {
    final lineCount = _countLines(content);
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.text_snippet_outlined,
                size: 16,
                color: AppTheme.accent,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '长内容已切换为轻量渲染',
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ),
              Text(
                '${content.length} 字 / $lineCount 行',
                style: AppTheme.ts(
                  fontSize: 11,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          _ChunkedPlainTextView(
            content: content,
            chunkChars: _largeMessageChunkChars,
            summaryText: '内容较长，已改为分段渲染，按需继续展开。',
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 8,
            children: [
              _CodeCopyButton(text: content, label: '复制全文'),
            ],
          ),
        ],
      ),
    );
  }
}

class _StructuredSourceBody extends StatelessWidget {
  final String content;

  const _StructuredSourceBody({required this.content});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '按 Markdown 源码展示',
          style: AppTheme.ts(
            fontSize: 12,
            color: AppTheme.textTertiary,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 10),
        _CodeBlockCard(
          language: 'markdown',
          code: content,
          closed: true,
        ),
      ],
    );
  }
}

class _SingleCodeBlockBody extends StatelessWidget {
  final String content;

  const _SingleCodeBlockBody({required this.content});

  @override
  Widget build(BuildContext context) {
    final parsed = _extractSingleFencedCodeBlock(content);
    if (parsed == null) {
      return _StructuredSourceBody(content: content);
    }
    return _CodeBlockCard(
      language: parsed.$1,
      code: parsed.$2,
      closed: true,
    );
  }
}

class _LargeStreamingPreview extends StatelessWidget {
  final String content;

  const _LargeStreamingPreview({required this.content});

  @override
  Widget build(BuildContext context) {
    final preview = _streamingTailText(content);
    final truncated = preview != content;
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.42),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (truncated) ...[
            Text(
              '生成中内容较长，当前仅显示最近一段输出。',
              style: AppTheme.ts(
                fontSize: 12,
                color: AppTheme.textTertiary,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 8),
          ],
          SelectableText(
            preview,
            style: AppTheme.ts(
              fontSize: 15,
              color: AppTheme.textPrimary,
              height: 1.65,
            ),
          ),
        ],
      ),
    );
  }
}

class _ChunkedPlainTextView extends StatefulWidget {
  final String content;
  final int chunkChars;
  final String summaryText;

  const _ChunkedPlainTextView({
    required this.content,
    required this.chunkChars,
    required this.summaryText,
  });

  @override
  State<_ChunkedPlainTextView> createState() => _ChunkedPlainTextViewState();
}

class _ChunkedPlainTextViewState extends State<_ChunkedPlainTextView> {
  int _visibleChunks = 1;

  @override
  Widget build(BuildContext context) {
    final chunks = _splitIntoChunks(widget.content, widget.chunkChars);
    final visibleCount = _visibleChunks.clamp(1, chunks.length);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.summaryText,
          style: AppTheme.ts(
            fontSize: 12,
            color: AppTheme.textTertiary,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 10),
        for (var index = 0; index < visibleCount; index++) ...[
          SelectableText(
            chunks[index],
            style: AppTheme.ts(
              fontSize: 15,
              color: AppTheme.textPrimary,
              height: 1.65,
            ),
          ),
          if (index != visibleCount - 1) const SizedBox(height: 12),
        ],
        if (visibleCount < chunks.length) ...[
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => setState(() => _visibleChunks += 1),
            icon: const Icon(Icons.expand_more_rounded, size: 16),
            label: Text('继续展开 ($visibleCount/${chunks.length})'),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppTheme.textPrimary,
              side: BorderSide(color: AppTheme.borderLight),
              textStyle: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
              padding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 10,
              ),
            ),
          ),
        ],
      ],
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
        final darkAlpha = 0.22 + (_controller.value * 0.18);
        final lightColor = Color.lerp(
          AppTheme.surfaceActive,
          AppTheme.borderLight.withValues(alpha: 0.92),
          _controller.value,
        )!;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _SkeletonLine(
              widthFactor: 0.92,
              color: AppTheme.isDark
                  ? Colors.white.withValues(alpha: darkAlpha)
                  : lightColor,
            ),
            const SizedBox(height: 8),
            _SkeletonLine(
              widthFactor: 0.78,
              color: AppTheme.isDark
                  ? Colors.white.withValues(alpha: darkAlpha * 0.9)
                  : Color.lerp(lightColor, AppTheme.surfaceActive, 0.18)!,
            ),
            const SizedBox(height: 8),
            _SkeletonLine(
              widthFactor: 0.56,
              color: AppTheme.isDark
                  ? Colors.white.withValues(alpha: darkAlpha * 0.8)
                  : Color.lerp(lightColor, AppTheme.surfaceActive, 0.3)!,
            ),
          ],
        );
      },
    );
  }
}

class _SkeletonLine extends StatelessWidget {
  final double widthFactor;
  final Color color;

  const _SkeletonLine({required this.widthFactor, required this.color});

  @override
  Widget build(BuildContext context) {
    return FractionallySizedBox(
      widthFactor: widthFactor,
      child: Container(
        height: 12,
        decoration: BoxDecoration(
          color: color,
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

class _CodeBlockCard extends StatefulWidget {
  final String language;
  final String code;
  final bool closed;

  const _CodeBlockCard({
    required this.language,
    required this.code,
    required this.closed,
  });

  @override
  State<_CodeBlockCard> createState() => _CodeBlockCardState();
}

class _CodeBlockCardState extends State<_CodeBlockCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final codeText = widget.code.trimRight();
    final lines = (codeText.isEmpty ? const [''] : codeText.split('\n'));
    final shouldCollapse =
        widget.closed && lines.length > _autoCollapseCodeLines;
    final visibleLines = shouldCollapse && !_expanded
        ? lines.take(_collapsedCodePreviewLines).toList()
        : lines;
    final lineNumbers = List<String>.generate(
      visibleLines.length,
      (index) => '${index + 1}',
    ).join('\n');
    final visibleCodeText = visibleLines.join('\n');
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
                    widget.language.trim().isEmpty
                        ? 'code'
                        : widget.language.trim(),
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.textSecondary,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                if (!widget.closed) ...[
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
                if (shouldCollapse) ...[
                  const SizedBox(width: 8),
                  Text(
                    _expanded
                        ? '已展开 ${lines.length} 行'
                        : '预览 ${visibleLines.length}/${lines.length} 行',
                    style: AppTheme.ts(
                      fontSize: 11,
                      color: AppTheme.textTertiary,
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
                  height: (visibleLines.length * 22)
                      .toDouble()
                      .clamp(24, 1200)
                      .toDouble(),
                  margin: const EdgeInsets.symmetric(horizontal: 12),
                  color: AppTheme.border,
                ),
                SelectableText(
                  visibleCodeText,
                  style: AppTheme.ts(
                    fontSize: 13,
                    color: const Color(0xFFE6EDF3),
                    height: 1.6,
                  ).copyWith(fontFamily: 'monospace'),
                ),
              ],
            ),
          ),
          if (shouldCollapse)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: () => setState(() => _expanded = !_expanded),
                  style: TextButton.styleFrom(
                    foregroundColor: AppTheme.textPrimary,
                    textStyle: AppTheme.ts(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  icon: Icon(
                    _expanded
                        ? Icons.expand_less_rounded
                        : Icons.expand_more_rounded,
                    size: 16,
                  ),
                  label: Text(_expanded ? '收起代码' : '展开完整代码'),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _CodeCopyButton extends StatelessWidget {
  final String text;
  final String label;

  const _CodeCopyButton({
    required this.text,
    this.label = '复制',
  });

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
      label: Text(label),
    );
  }
}

bool _shouldDegradeRichMarkdown(String content) {
  return content.length > _richMarkdownMaxChars ||
      _countLines(content) > _richMarkdownMaxLines ||
      _countOccurrences(content, '```') > _richMarkdownMaxCodeFences;
}

bool _shouldDegradeStreamingMarkdown(String content) {
  return content.length > _streamStructuredMaxChars ||
      _countLines(content) > _streamStructuredMaxLines;
}

bool _looksLikeLatex(String content) {
  if (content.contains(r'\(') || content.contains(r'\[')) {
    return true;
  }
  if (content.contains(r'$$')) {
    return true;
  }
  return RegExp(r'(?<!\\)\$[^$\n]{1,120}(?<!\\)\$').hasMatch(content);
}

String _normalizePlainAnswerContent(String content) {
  final normalized =
      content.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trim();
  if (normalized.isEmpty) {
    return '';
  }
  final paragraphs = <String>[];
  final currentLines = <String>[];
  for (final rawLine in normalized.split('\n')) {
    final line = rawLine.trim();
    if (line.isEmpty) {
      if (currentLines.isNotEmpty) {
        paragraphs.add(_collapsePlainParagraph(currentLines));
        currentLines.clear();
      }
      continue;
    }
    currentLines.add(line);
  }
  if (currentLines.isNotEmpty) {
    paragraphs.add(_collapsePlainParagraph(currentLines));
  }
  return paragraphs.join('\n\n');
}

_StructuredPlainAnswer? _parseStructuredPlainAnswer(String content) {
  final paragraphs = content
      .split(RegExp(r'\n\s*\n'))
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();
  if (paragraphs.length < 3) {
    return null;
  }

  final introParagraphs = <String>[];
  final sections = <_StructuredPlainSection>[];
  String? callToAction;

  for (var index = 0; index < paragraphs.length; index++) {
    final paragraph = paragraphs[index];
    final isLast = index == paragraphs.length - 1;

    if (isLast && _looksLikeCallToActionParagraph(paragraph)) {
      callToAction = paragraph;
      continue;
    }

    if (_looksLikeSectionTitle(paragraph)) {
      final parsedSection = _parseStructuredSection(paragraph);
      if (parsedSection != null) {
        sections.add(parsedSection);
        continue;
      }
    }

    if (sections.isEmpty) {
      introParagraphs.add(paragraph);
      continue;
    }

    final lastSection = sections.removeLast();
    final mergedBody = [
      if (lastSection.bodyText?.isNotEmpty ?? false) lastSection.bodyText!,
      paragraph,
    ].join('\n\n');
    sections.add(
      _StructuredPlainSection(
        title: lastSection.title,
        fields: lastSection.fields,
        listItems: lastSection.listItems,
        bodyText: mergedBody,
      ),
    );
  }

  final hasEnoughStructure = sections.length >= 2 ||
      sections.any((section) =>
          section.fields.length >= 2 ||
          section.listItems.length >= 3 ||
          section.title.startsWith('方案'));
  if (!hasEnoughStructure) {
    return null;
  }

  return _StructuredPlainAnswer(
    introParagraphs: introParagraphs,
    sections: sections,
    callToAction: callToAction,
  );
}

bool _looksLikeSectionTitle(String paragraph) {
  final firstLine = paragraph
      .split('\n')
      .map((item) => item.trim())
      .firstWhere((item) => item.isNotEmpty, orElse: () => '');
  if (firstLine.isEmpty) {
    return false;
  }

  final patterns = <RegExp>[
    RegExp(r'^方案[一二三四五六七八九十0-9]+\s*[：:].+$'),
    RegExp(r'^(推荐|路线|选项)[一二三四五六七八九十0-9]*\s*[：:].+$'),
    RegExp(r'^(通用建议|补充建议|注意事项|结论|总结|下一步)\s*[：:]?$'),
  ];
  if (patterns.any((pattern) => pattern.hasMatch(firstLine))) {
    return true;
  }

  return firstLine.length <= 24 &&
      firstLine.endsWith('：') &&
      !RegExp(r'^\d+[.)、]').hasMatch(firstLine);
}

_StructuredPlainSection? _parseStructuredSection(String paragraph) {
  final lines = paragraph
      .split('\n')
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();
  if (lines.isEmpty) {
    return null;
  }

  final fields = <_StructuredPlainField>[];
  final listItems = <String>[];
  final bodyParts = <String>[];

  for (final line in lines.skip(1)) {
    final field = _parseStructuredField(line);
    if (field != null) {
      fields.add(field);
      continue;
    }
    if (_looksLikePlainListLine(line)) {
      listItems.add(_stripPlainListPrefix(line));
      continue;
    }
    if (fields.isNotEmpty) {
      final last = fields.removeLast();
      fields.add(
        _StructuredPlainField(
          label: last.label,
          content: '${last.content} $line'.trim(),
        ),
      );
      continue;
    }
    if (listItems.isNotEmpty) {
      listItems[listItems.length - 1] = '${listItems.last} $line'.trim();
      continue;
    }
    bodyParts.add(line);
  }

  return _StructuredPlainSection(
    title: lines.first,
    fields: fields,
    listItems: listItems,
    bodyText: bodyParts.isEmpty ? null : bodyParts.join('\n'),
  );
}

_StructuredPlainField? _parseStructuredField(String line) {
  final match =
      RegExp(r'^\s*[-•]?\s*([^：:]{1,12})[：:]\s*(.+)$').firstMatch(line);
  if (match == null) {
    return null;
  }

  final label = (match.group(1) ?? '').trim();
  final content = (match.group(2) ?? '').trim();
  if (label.isEmpty || content.isEmpty || _looksLikeSectionTitle(label)) {
    return null;
  }
  return _StructuredPlainField(
    label: label,
    content: content,
  );
}

bool _looksLikeCallToActionParagraph(String paragraph) {
  final normalized = paragraph.trim();
  if (normalized.isEmpty || normalized.length > 140) {
    return false;
  }
  if (!(normalized.contains('？') || normalized.contains('?'))) {
    return false;
  }
  return normalized.startsWith('你') ||
      normalized.startsWith('如果你') ||
      normalized.startsWith('要不要') ||
      normalized.startsWith('是否');
}

String _collapsePlainParagraph(List<String> lines) {
  if (lines.length <= 1) {
    return lines.first;
  }
  if (lines.any(_looksLikePlainListLine)) {
    return lines.join('\n');
  }
  return lines.join(' ');
}

bool _looksLikePlainListLine(String line) {
  final patterns = <RegExp>[
    RegExp(r'^\s*[-*•]\s+\S'),
    RegExp(r'^\s*\d+[.)、]\s+\S'),
    RegExp(r'^\s*[一二三四五六七八九十]+[、.]\s*\S'),
  ];
  return patterns.any((pattern) => pattern.hasMatch(line));
}

class _PlainListParseResult {
  final String? leadText;
  final List<String> items;

  const _PlainListParseResult({
    required this.leadText,
    required this.items,
  });
}

_PlainListParseResult _extractPlainListItems(String content) {
  final lines = content
      .split('\n')
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();
  if (lines.isEmpty) {
    return const _PlainListParseResult(leadText: null, items: []);
  }

  final items = <String>[];
  final leadParts = <String>[];
  var listStarted = false;
  for (final line in lines) {
    if (_looksLikePlainListLine(line)) {
      listStarted = true;
      items.add(_stripPlainListPrefix(line));
      continue;
    }
    if (!listStarted) {
      leadParts.add(line);
      continue;
    }
    if (items.isNotEmpty) {
      items[items.length - 1] = '${items.last} $line';
    }
  }
  final leadText = leadParts.isEmpty ? null : leadParts.join(' ');
  return _PlainListParseResult(
    leadText: leadText,
    items: items,
  );
}

String _stripPlainListPrefix(String line) {
  return line
      .replaceFirst(RegExp(r'^\s*[-*•]\s+'), '')
      .replaceFirst(RegExp(r'^\s*\d+[.)、]\s+'), '')
      .replaceFirst(RegExp(r'^\s*[一二三四五六七八九十]+[、.]\s*'), '')
      .trim();
}

List<InlineSpan> _buildPlainInlineSpans(String text, TextStyle baseStyle) {
  final spans = <InlineSpan>[];
  var index = 0;
  while (index < text.length) {
    if (text.startsWith('**', index)) {
      final closing = text.indexOf('**', index + 2);
      if (closing > index + 2) {
        final value = text.substring(index + 2, closing);
        if (!value.contains('\n')) {
          spans.add(
            TextSpan(
              text: value,
              style: baseStyle.copyWith(
                fontWeight: FontWeight.w700,
                color: AppTheme.textPrimary,
              ),
            ),
          );
          index = closing + 2;
          continue;
        }
      }
    }
    if (text.startsWith('`', index)) {
      final closing = text.indexOf('`', index + 1);
      if (closing > index + 1) {
        final value = text.substring(index + 1, closing);
        if (!value.contains('\n')) {
          spans.add(
            TextSpan(
              text: value,
              style: baseStyle.copyWith(
                fontFamily: 'monospace',
                fontSize: 14,
                color: AppTheme.accent,
                backgroundColor: AppTheme.surfaceActive,
              ),
            ),
          );
          index = closing + 1;
          continue;
        }
      }
    }
    if (text.startsWith('*', index) && !text.startsWith('**', index)) {
      final closing = text.indexOf('*', index + 1);
      if (closing > index + 1 && !text.startsWith('*', closing)) {
        final value = text.substring(index + 1, closing);
        if (!value.contains('\n')) {
          spans.add(
            TextSpan(
              text: value,
              style: baseStyle.copyWith(
                fontStyle: FontStyle.italic,
                color: AppTheme.textPrimary,
              ),
            ),
          );
          index = closing + 1;
          continue;
        }
      }
    }

    final nextSpecial = _findNextInlineSpecial(text, index);
    if (nextSpecial == index) {
      spans.add(TextSpan(text: text[index], style: baseStyle));
      index += 1;
      continue;
    }
    spans.add(
        TextSpan(text: text.substring(index, nextSpecial), style: baseStyle));
    index = nextSpecial;
  }
  return spans;
}

int _findNextInlineSpecial(String text, int start) {
  var next = text.length;
  for (final token in const ['**', '`', '*']) {
    final found = text.indexOf(token, start);
    if (found >= 0 && found < next) {
      next = found;
    }
  }
  return next;
}

_ResolvedMessageContent _resolveMessageContent(
  String content, {
  required bool isStreaming,
  String? answerFormat,
  String? renderHint,
  String? layoutHint,
}) {
  final normalized = content.trim();
  if (normalized.isEmpty) {
    return const _ResolvedMessageContent(
      content: '',
      mode: _MessageRenderMode.plainText,
    );
  }

  final protocolMode = _messageRenderModeFromProtocol(
    renderHint: renderHint,
    answerFormat: answerFormat,
  );
  if (protocolMode != null) {
    return _ResolvedMessageContent(
      content: normalized,
      mode: protocolMode,
    );
  }

  final unwrappedMarkdown =
      isStreaming ? null : _unwrapMarkdownDocumentWrapper(normalized);
  final effectiveContent = unwrappedMarkdown ?? normalized;

  if (_looksLikeMarkdownSource(normalized) && unwrappedMarkdown == null) {
    return _ResolvedMessageContent(
      content: normalized,
      mode: _MessageRenderMode.markdownSource,
    );
  }

  if (_shouldDegradeRichMarkdown(effectiveContent)) {
    return _ResolvedMessageContent(
      content: effectiveContent,
      mode: _MessageRenderMode.largePreview,
    );
  }

  if (_shouldUseStructuredMarkdown(effectiveContent)) {
    return _ResolvedMessageContent(
      content: effectiveContent,
      mode: _MessageRenderMode.markdownStructured,
    );
  }

  if (_looksLikeRichMarkdown(effectiveContent)) {
    return _ResolvedMessageContent(
      content: effectiveContent,
      mode: _MessageRenderMode.markdownRendered,
    );
  }

  return _ResolvedMessageContent(
    content: effectiveContent,
    mode: _MessageRenderMode.plainText,
  );
}

_MessageRenderMode? _messageRenderModeFromProtocol({
  String? renderHint,
  String? answerFormat,
}) {
  switch ((renderHint ?? '').trim()) {
    case 'markdown_document':
      return _MessageRenderMode.markdownRendered;
    case 'markdown_source':
      return _MessageRenderMode.markdownSource;
    case 'code_block':
      return _MessageRenderMode.codeBlock;
    case 'large_document':
      return _MessageRenderMode.largePreview;
    case 'plain':
      return _MessageRenderMode.plainText;
  }

  switch ((answerFormat ?? '').trim()) {
    case 'markdown':
      return _MessageRenderMode.markdownRendered;
    case 'markdown_source':
      return _MessageRenderMode.markdownSource;
    case 'code':
      return _MessageRenderMode.codeBlock;
    case 'plain_text':
      return _MessageRenderMode.plainText;
  }
  return null;
}

bool _looksLikeMarkdownSource(String content) {
  final normalized = content.trimLeft().toLowerCase();
  return normalized.startsWith('```markdown') || normalized.startsWith('```md');
}

bool _looksLikeRichMarkdown(String content) {
  final patterns = <RegExp>[
    RegExp(r'^\s{0,3}#{1,6}\s+\S', multiLine: true),
    RegExp(r'^\s*[-*+]\s+\S', multiLine: true),
    RegExp(r'^\s*\d+\.\s+\S', multiLine: true),
    RegExp(r'^\s*>\s+\S', multiLine: true),
    RegExp(r'^\s*\|.+\|', multiLine: true),
    RegExp(r'^\s*-\s+\[[ xX]\]\s+', multiLine: true),
    RegExp(r'```'),
    RegExp(r'`[^`\n]+`'),
    RegExp(r'\*\*[^*\n]+\*\*'),
    RegExp(r'(?<!\*)\*[^*\n]+\*(?!\*)'),
    RegExp(r'!\[[^\]]*\]\([^)]+\)'),
    RegExp(r'\[[^\]]+\]\([^)]+\)'),
  ];
  if (_looksLikeLatex(content)) {
    return true;
  }
  return patterns.any((pattern) => pattern.hasMatch(content));
}

bool _shouldUseStructuredMarkdown(String content) {
  return _looksLikeRichMarkdown(content) &&
      (content.length > 900 ||
          _countLines(content) > 48 ||
          _countOccurrences(content, '```') > 2 ||
          content.contains('|') ||
          _looksLikeLatex(content));
}

String? _unwrapMarkdownDocumentWrapper(String content) {
  final lines = content.replaceAll('\r\n', '\n').split('\n');
  final openPattern =
      RegExp(r'^\s*```(?:markdown|md)\s*$', caseSensitive: false);
  final closePattern = RegExp(r'^\s*```\s*$');

  final openIndex = lines.indexWhere((line) => openPattern.hasMatch(line));
  if (openIndex < 0) {
    return null;
  }

  var closeIndex = -1;
  for (var index = lines.length - 1; index > openIndex; index -= 1) {
    if (closePattern.hasMatch(lines[index])) {
      closeIndex = index;
      break;
    }
  }
  if (closeIndex <= openIndex + 1) {
    return null;
  }

  final inner = lines.sublist(openIndex + 1, closeIndex).join('\n').trim();
  if (inner.isEmpty || !_looksLikeRichMarkdown(inner)) {
    return null;
  }

  final prefix = lines.sublist(0, openIndex).join('\n').trim();
  final suffix = lines.sublist(closeIndex + 1).join('\n').trim();
  final parts = <String>[
    if (prefix.isNotEmpty) prefix,
    inner,
    if (suffix.isNotEmpty) suffix,
  ];
  if (parts.isEmpty) {
    return null;
  }
  return parts.join('\n\n');
}

(String, String)? _extractSingleFencedCodeBlock(String content) {
  final match = RegExp(
    r'^\s*```([^\n`]*)\n([\s\S]*?)\n?```\s*$',
    dotAll: true,
  ).firstMatch(content);
  if (match == null) {
    return null;
  }
  final language = (match.group(1) ?? '').trim();
  final code = match.group(2) ?? '';
  return (language, code);
}

int _countLines(String content) {
  if (content.isEmpty) {
    return 0;
  }
  return '\n'.allMatches(content).length + 1;
}

int _countOccurrences(String source, String pattern) {
  if (pattern.isEmpty) {
    return 0;
  }
  return pattern.allMatches(source).length;
}

List<String> _splitIntoChunks(String content, int chunkChars) {
  final normalized = content.trim();
  if (normalized.isEmpty) {
    return const [''];
  }
  final chunks = <String>[];
  var index = 0;
  while (index < normalized.length) {
    final end = (index + chunkChars).clamp(0, normalized.length);
    chunks.add(normalized.substring(index, end));
    index = end;
  }
  return chunks;
}

String _streamingTailText(String content) {
  if (content.length <= _streamingTailPreviewChars) {
    return content;
  }
  return '……前文已省略，仅展示最近输出\n\n${content.substring(content.length - _streamingTailPreviewChars)}';
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

class _ArtifactList extends StatelessWidget {
  final List<AnswerArtifactView> artifacts;

  const _ArtifactList({required this.artifacts});

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: artifacts
          .map((artifact) => _ArtifactCard(artifact: artifact))
          .toList(),
    );
  }
}

class _ArtifactCard extends ConsumerWidget {
  final AnswerArtifactView artifact;

  const _ArtifactCard({required this.artifact});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final provider = ref.watch(chatProvider);
    final isGenerated = artifact.role == "generated";
    final label = switch (artifact.role) {
      "generated" => "已生成文件",
      "source" => "来源文件",
      "reference" => "参考文件",
      _ => "文件",
    };
    final icon = switch (artifact.role) {
      "generated" => Icons.description_rounded,
      "source" => Icons.file_open_rounded,
      "reference" => Icons.bookmark_outline_rounded,
      _ => Icons.insert_drive_file_rounded,
    };
    final fileId = _artifactFileId(artifact);
    SessionFileView? sessionFile;
    if (fileId != null) {
      for (final item in provider.sessionFiles) {
        if (item.fileId == fileId) {
          sessionFile = item;
          break;
        }
      }
    }
    final displayPath = sessionFile == null
        ? artifact.path
        : "${sessionFile.filename} (${sessionFile.fileId})";
    final isActiveFile =
        fileId != null && provider.activeFileIds.contains(fileId);

    return Container(
      constraints: const BoxConstraints(maxWidth: 320),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: isGenerated
            ? AppTheme.accent.withValues(alpha: 0.08)
            : AppTheme.surfaceActive,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isGenerated
              ? AppTheme.accent.withValues(alpha: 0.28)
              : AppTheme.border,
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            icon,
            size: 16,
            color: isGenerated ? AppTheme.accent : AppTheme.textSecondary,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    color:
                        isGenerated ? AppTheme.accent : AppTheme.textSecondary,
                  ),
                ),
                const SizedBox(height: 3),
                SelectableText(
                  displayPath,
                  style: AppTheme.ts(
                    fontSize: 12,
                    color: AppTheme.textPrimary,
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 4,
                  runSpacing: 4,
                  children: [
                    if (fileId != null)
                      _ArtifactActionButton(
                        label: isActiveFile ? "已激活" : "激活文件",
                        icon: isActiveFile
                            ? Icons.check_circle_outline_rounded
                            : Icons.push_pin_outlined,
                        enabled: !isActiveFile,
                        onPressed: () async {
                          final activated = await ref
                              .read(chatProvider)
                              .activateFileFromArtifact(fileId);
                          if (!context.mounted) return;
                          if (!activated) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text("激活文件失败"),
                                duration: Duration(seconds: 1),
                              ),
                            );
                            return;
                          }
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(
                                sessionFile == null
                                    ? "已激活文件 $fileId"
                                    : "已激活文件 ${sessionFile.filename}",
                              ),
                              duration: const Duration(seconds: 1),
                            ),
                          );
                        },
                      )
                    else ...[
                      _ArtifactActionButton(
                        label: "查看内容",
                        icon: Icons.visibility_outlined,
                        onPressed: () => _previewWorkspaceArtifact(
                            context, ref, artifact.path),
                      ),
                      _ArtifactActionButton(
                        label: "复制路径",
                        icon: Icons.content_copy_rounded,
                        onPressed: () async {
                          await Clipboard.setData(
                            ClipboardData(text: artifact.path),
                          );
                          if (!context.mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(
                            const SnackBar(
                              content: Text("路径已复制"),
                              duration: Duration(seconds: 1),
                            ),
                          );
                        },
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ArtifactActionButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool enabled;
  final Future<void> Function() onPressed;

  const _ArtifactActionButton({
    required this.label,
    required this.icon,
    required this.onPressed,
    this.enabled = true,
  });

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: enabled ? () => unawaited(onPressed()) : null,
      style: TextButton.styleFrom(
        foregroundColor:
            enabled ? AppTheme.textSecondary : AppTheme.textTertiary,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        textStyle: AppTheme.ts(
          fontSize: 12,
          fontWeight: FontWeight.w600,
        ),
      ),
      icon: Icon(icon, size: 14),
      label: Text(label),
    );
  }
}

Future<void> _previewWorkspaceArtifact(
  BuildContext context,
  WidgetRef ref,
  String path,
) async {
  WorkspaceFilePreview preview;
  try {
    preview = await ref.read(chatProvider).previewWorkspaceFile(path);
  } catch (error) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text("读取文件预览失败: $error"),
        duration: const Duration(seconds: 2),
      ),
    );
    return;
  }
  if (!context.mounted) return;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (sheetContext) => _WorkspacePreviewSheet(preview: preview),
  );
}

class _WorkspacePreviewSheet extends StatelessWidget {
  final WorkspaceFilePreview preview;

  const _WorkspacePreviewSheet({required this.preview});

  @override
  Widget build(BuildContext context) {
    final contentHeight = MediaQuery.sizeOf(context).height * 0.82;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
        child: Container(
          constraints: BoxConstraints(
            maxWidth: 960,
            maxHeight: contentHeight,
          ),
          decoration: AppTheme.floatingPanelDecoration(
            radius: 28,
            alpha: 0.96,
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 18, 14, 12),
                child: Row(
                  children: [
                    Container(
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: AppTheme.surfaceActive,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: AppTheme.border),
                      ),
                      child: Icon(
                        Icons.description_outlined,
                        size: 18,
                        color: AppTheme.accent,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            "文件预览",
                            style: AppTheme.ts(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 4),
                          SelectableText(
                            preview.path,
                            style: AppTheme.ts(
                              fontSize: 12,
                              color: AppTheme.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    IconButton(
                      tooltip: "关闭",
                      onPressed: () => Navigator.of(context).pop(),
                      icon: const Icon(Icons.close_rounded),
                      color: AppTheme.textSecondary,
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    _PreviewMetaChip(
                      icon: Icons.text_snippet_outlined,
                      label: "${preview.totalChars} 字符",
                    ),
                    _PreviewMetaChip(
                      icon: Icons.sd_storage_outlined,
                      label: _formatBytes(preview.sizeBytes),
                    ),
                    if (preview.truncated)
                      const _PreviewMetaChip(
                        icon: Icons.content_cut_rounded,
                        label: "当前为截断预览",
                      ),
                  ],
                ),
              ),
              Expanded(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                  child: Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AppTheme.surface.withValues(alpha: 0.82),
                      borderRadius: BorderRadius.circular(20),
                      border: Border.all(color: AppTheme.border),
                    ),
                    child: _MessageBody(
                      content: preview.content,
                      isUser: false,
                      isStreaming: false,
                      answerFormat: preview.answerFormat,
                      renderHint: preview.renderHint,
                      layoutHint: preview.layoutHint,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PreviewMetaChip extends StatelessWidget {
  final IconData icon;
  final String label;

  const _PreviewMetaChip({
    required this.icon,
    required this.label,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: AppTheme.surfaceActive,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: AppTheme.textSecondary),
          const SizedBox(width: 6),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppTheme.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

String _formatBytes(int value) {
  if (value < 1024) {
    return "$value B";
  }
  if (value < 1024 * 1024) {
    return "${(value / 1024).toStringAsFixed(1)} KB";
  }
  return "${(value / 1024 / 1024).toStringAsFixed(1)} MB";
}

String? _artifactFileId(AnswerArtifactView artifact) {
  const prefix = "file_id:";
  if (!artifact.path.startsWith(prefix)) {
    return null;
  }
  final value = artifact.path.substring(prefix.length).trim();
  return value.isEmpty ? null : value;
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
