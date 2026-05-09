import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_highlight/themes/atom-one-dark.dart';
import 'package:flutter_highlight/themes/atom-one-light.dart';
import 'package:flutter_math_fork/flutter_math.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:gpt_markdown/gpt_markdown.dart';
import 'package:highlight/highlight.dart' as hl;
import 'package:highlight/highlight.dart' show Node;

import '../../core/models/api_models.dart';
import '../../core/providers/career_assets_provider.dart';
import '../../core/providers/chat_provider.dart';
import '../theme/app_theme.dart';
import '../utils/download_stub.dart'
    if (dart.library.html) '../utils/download_web.dart';
import 'run_progress_panel.dart';

const double _bubbleMaxWidth = 780;
const double _userBubbleMaxWidth = 560;
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
const int _leadParagraphMaxChars = 110;

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
    final maxBubbleWidth = isUser ? _userBubbleMaxWidth : _bubbleMaxWidth;
    final presentation = isUser
        ? null
        : _CareerMessagePresentation.fromContent(widget.message.content);
    final visibleContent = presentation?.content ?? widget.message.content;
    final attachedArtifactIds =
        _artifactIdsFromAnswerArtifacts(widget.message.artifacts);
    final detectedAssets =
        (presentation?.assets ?? const <_DetectedCareerAsset>[])
            .where((asset) =>
                asset.kind != _CareerAssetKind.artifact ||
                !attachedArtifactIds.contains(asset.id))
            .toList();
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: MouseRegion(
        onEnter: (_) => setState(() => _hovering = true),
        onExit: (_) => setState(() => _hovering = false),
        child: Container(
          constraints: BoxConstraints(maxWidth: maxBubbleWidth),
          margin: EdgeInsets.only(
            left: isUser ? 160 : 0,
            right: isUser ? 8 : 60,
            top: isUser ? 12 : 8,
            bottom: isUser ? 16 : 10,
          ),
          child: Column(
            crossAxisAlignment:
                isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
            children: [
              if (!isUser)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8, left: 6, right: 6),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const _Avatar(isUser: false),
                      const SizedBox(width: 8),
                      Text(
                        "Assistant",
                        style: AppTheme.ts(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w600,
                            color: AppTheme.textSecondary),
                      ),
                      if (_hovering) ...[
                        const SizedBox(width: 8),
                        _CopyButton(text: widget.message.content),
                      ],
                    ],
                  ),
                ),
              ConstrainedBox(
                constraints: BoxConstraints(maxWidth: maxBubbleWidth),
                child: Container(
                  padding: EdgeInsets.symmetric(
                    horizontal: isUser ? 16 : 18,
                    vertical: isUser ? 12 : 14,
                  ),
                  decoration: isUser
                      ? AppTheme.userBubbleDecoration
                      : AppTheme.assistantBubbleDecoration,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!isUser &&
                          RunProgressPanel.hasProgress(
                            widget.message.progressEvents,
                          )) ...[
                        RunProgressPanel(
                          events: widget.message.progressEvents,
                        ),
                        if (widget.message.content.isNotEmpty)
                          const SizedBox(height: 2),
                      ],
                      if (visibleContent.isNotEmpty)
                        RepaintBoundary(
                          child: _MessageBody(
                            content: visibleContent,
                            isUser: isUser,
                            isStreaming: false,
                            answerFormat: widget.message.answerFormat,
                            renderHint: widget.message.renderHint,
                            layoutHint: widget.message.layoutHint,
                          ),
                        ),
                      if (detectedAssets.isNotEmpty) ...[
                        SizedBox(height: visibleContent.isEmpty ? 0 : 12),
                        _CareerAssetReferenceStrip(assets: detectedAssets),
                      ],
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
  final List<EventView> progressEvents;
  const StreamingBubble(
      {super.key,
      required this.buffer,
      this.answerFormat,
      this.renderHint,
      this.layoutHint,
      this.artifacts = const [],
      this.thinkingLines = const [],
      this.progressEvents = const []});

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
              padding: const EdgeInsets.only(bottom: 8, left: 6),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const _Avatar(isUser: false),
                  const SizedBox(width: 8),
                  Text(
                    "Assistant",
                    style: AppTheme.ts(
                        fontSize: 12.5,
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
            // Progress section (collapsible)
            if (RunProgressPanel.hasProgress(progressEvents))
              RunProgressPanel(events: progressEvents)
            else if (thinkingLines.isNotEmpty)
              _ThinkingBlock(lines: thinkingLines),
            // Content
            if (buffer.isNotEmpty)
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: _bubbleMaxWidth),
                child: Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
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
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.54),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.84)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
              child: Row(
                children: [
                  Container(
                    width: 22,
                    height: 22,
                    decoration: BoxDecoration(
                      color: AppTheme.accent.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Icon(
                      _expanded
                          ? Icons.expand_more_rounded
                          : Icons.chevron_right_rounded,
                      size: 15,
                      color: AppTheme.accent,
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text("执行过程",
                      style: AppTheme.ts(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.textSecondary)),
                  const Spacer(),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: AppTheme.surfaceActive.withValues(alpha: 0.9),
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: AppTheme.border),
                    ),
                    child: Text("${widget.lines.length} 条",
                        style: AppTheme.ts(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w600,
                            color: AppTheme.textTertiary)),
                  ),
                ],
              ),
            ),
          ),
          if (_expanded)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: widget.lines
                    .map((l) => Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Text(l,
                              style: AppTheme.ts(
                                  fontSize: 11.5,
                                  color: AppTheme.textSecondary,
                                  height: 1.45)),
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
        borderRadius: BorderRadius.circular(9),
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
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: () {
          Clipboard.setData(ClipboardData(text: text));
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
                content: Text("已复制"), duration: Duration(seconds: 1)),
          );
        },
        child: Container(
          width: 24,
          height: 24,
          decoration: BoxDecoration(
            color: AppTheme.surface.withValues(alpha: 0.8),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: AppTheme.border.withValues(alpha: 0.82)),
          ),
          child: Icon(
            Icons.copy_rounded,
            size: 12.5,
            color: AppTheme.textTertiary,
          ),
        ),
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
    final careerReport = _CareerReportPresentation.tryParse(resolved.content);
    if (careerReport != null) {
      return _CareerReportBody(report: careerReport);
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
              style: index == 0 && _shouldUseLeadParagraph(paragraphs)
                  ? baseStyle.copyWith(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      height: 1.72,
                    )
                  : baseStyle,
              children: _buildPlainInlineSpans(
                paragraphs[index],
                index == 0 && _shouldUseLeadParagraph(paragraphs)
                    ? baseStyle.copyWith(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        height: 1.72,
                      )
                    : baseStyle,
              ),
            ),
          ),
          if (index < paragraphs.length - 1)
            SizedBox(
                height: index == 0 && _shouldUseLeadParagraph(paragraphs)
                    ? 14
                    : 10),
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
              style: index == 0 &&
                      parsed.introParagraphs.length == 1 &&
                      _isShortLeadText(parsed.introParagraphs[index])
                  ? baseStyle.copyWith(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      height: 1.72,
                    )
                  : baseStyle,
              children: _buildPlainInlineSpans(
                parsed.introParagraphs[index],
                index == 0 &&
                        parsed.introParagraphs.length == 1 &&
                        _isShortLeadText(parsed.introParagraphs[index])
                    ? baseStyle.copyWith(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        height: 1.72,
                      )
                    : baseStyle,
              ),
            ),
          ),
          SizedBox(
            height: index == 0 &&
                    parsed.introParagraphs.length == 1 &&
                    _isShortLeadText(parsed.introParagraphs[index])
                ? 16
                : 12,
          ),
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
      padding: const EdgeInsets.fromLTRB(15, 15, 15, 15),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.62),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.92)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.06 : 0.025),
            blurRadius: 10,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SelectableText.rich(
            TextSpan(
              style: baseStyle.copyWith(
                fontSize: 16.5,
                fontWeight: FontWeight.w700,
                height: 1.5,
              ),
              children: _buildPlainInlineSpans(
                section.title,
                baseStyle.copyWith(
                  fontSize: 16.5,
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
            color: AppTheme.accent.withValues(alpha: 0.08),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: AppTheme.accent.withValues(alpha: 0.14),
            ),
          ),
          child: Text(
            field.label,
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

class _CareerReportBody extends StatelessWidget {
  final _CareerReportPresentation report;

  const _CareerReportBody({required this.report});

  @override
  Widget build(BuildContext context) {
    final reportTitle = _careerReportDisplayTitle(report);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _CareerReportHeader(
            title: reportTitle, sectionCount: report.sections.length),
        const SizedBox(height: 12),
        if (report.lead.isNotEmpty) ...[
          _CareerReportLeadBlock(content: report.lead),
          const SizedBox(height: 14),
        ],
        for (var index = 0; index < report.sections.length; index++) ...[
          _CareerReportSectionBlock(section: report.sections[index]),
          if (index < report.sections.length - 1) const SizedBox(height: 12),
        ],
      ],
    );
  }
}

class _CareerReportSectionBlock extends StatelessWidget {
  final _CareerReportSection section;

  const _CareerReportSectionBlock({required this.section});

  @override
  Widget build(BuildContext context) {
    final color = _careerSectionColor(section.title);
    final body = section.body.trim();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(13, 12, 13, 13),
      decoration: BoxDecoration(
        color: AppTheme.surfaceActive.withValues(alpha: 0.62),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.86)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 26,
                height: 26,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  _careerSectionIcon(section.title),
                  size: 15,
                  color: color,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  section.title,
                  style: AppTheme.ts(
                    fontSize: 14,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ),
            ],
          ),
          if (section.body.isNotEmpty) ...[
            const SizedBox(height: 10),
            if (_isSummarySection(section.title))
              _CareerSummarySection(body: body)
            else if (_isRiskSection(section.title))
              _CareerRiskListSection(body: body)
            else if (_isInsightGridSection(section.title))
              _CareerInsightGridSection(
                body: body,
                color: color,
                icon: _careerSectionIcon(section.title),
              )
            else if (_isActionListSection(section.title))
              _CareerActionListSection(
                body: body,
                color: color,
                icon: _careerSectionIcon(section.title),
              )
            else
              _AssistantMarkdownBody(content: body),
          ],
        ],
      ),
    );
  }
}

class _CareerReportHeader extends StatelessWidget {
  final String title;
  final int sectionCount;

  const _CareerReportHeader({
    required this.title,
    required this.sectionCount,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 13, 14, 13),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.18)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: AppTheme.accent.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(10),
              border:
                  Border.all(color: AppTheme.accent.withValues(alpha: 0.22)),
            ),
            child: Icon(
              Icons.fact_check_outlined,
              size: 18,
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: AppTheme.ts(
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                    height: 1.2,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  "$sectionCount 个分析模块 · 已整理为结构化报告",
                  style: AppTheme.ts(
                    fontSize: 12,
                    color: AppTheme.textSecondary,
                    height: 1.35,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerReportLeadBlock extends StatelessWidget {
  final String content;

  const _CareerReportLeadBlock({required this.content});

  @override
  Widget build(BuildContext context) {
    final normalized = _careerLeadContent(content);
    if (normalized.isEmpty) {
      return const SizedBox.shrink();
    }
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: AppTheme.accent.withValues(alpha: 0.18),
        ),
      ),
      child: _CompactMarkdownBody(
        content: normalized,
        style: AppTheme.ts(
          fontSize: 13,
          height: 1.55,
          fontWeight: FontWeight.w600,
          color: AppTheme.textPrimary,
        ),
      ),
    );
  }
}

class _CareerSummarySection extends StatelessWidget {
  final String body;

  const _CareerSummarySection({required this.body});

  @override
  Widget build(BuildContext context) {
    final fields = _careerSummaryFields(body);
    if (fields.isEmpty) {
      return _AssistantMarkdownBody(content: body);
    }
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final field in fields)
          Container(
            constraints: const BoxConstraints(minWidth: 180, maxWidth: 310),
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
            decoration: BoxDecoration(
              color: AppTheme.bg.withValues(alpha: 0.34),
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: AppTheme.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  field.label,
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textTertiary,
                  ),
                ),
                const SizedBox(height: 4),
                _CompactMarkdownBody(
                  content: field.value,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    height: 1.4,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.textPrimary,
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _CareerRiskListSection extends StatelessWidget {
  final String body;

  const _CareerRiskListSection({required this.body});

  @override
  Widget build(BuildContext context) {
    final risks = _careerRiskItems(body);
    if (risks.isEmpty) {
      return _AssistantMarkdownBody(content: body);
    }
    return Column(
      children: [
        for (var index = 0; index < risks.length; index++) ...[
          _CareerRiskCard(risk: risks[index]),
          if (index < risks.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _CareerRiskCard extends StatelessWidget {
  final _CareerRiskItem risk;

  const _CareerRiskCard({required this.risk});

  @override
  Widget build(BuildContext context) {
    final level = _careerRiskLevel(risk.level);
    final visual = _careerItemVisual(
      "${risk.title} ${risk.detail}",
      fallbackColor: level.color,
      fallbackIcon: level.icon,
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 11),
      decoration: BoxDecoration(
        color: level.color.withValues(alpha: AppTheme.isDark ? 0.08 : 0.055),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: level.color.withValues(alpha: 0.24)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: level.color.withValues(alpha: 0.13),
              borderRadius: BorderRadius.circular(9),
              border: Border.all(color: level.color.withValues(alpha: 0.18)),
            ),
            child: Icon(visual.icon, size: 15, color: level.color),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        risk.title.isEmpty ? "待补风险" : risk.title,
                        style: AppTheme.ts(
                          fontSize: 12.8,
                          height: 1.3,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    _CareerMiniBadge(
                      label: level.label,
                      color: level.color,
                      filled: true,
                    ),
                  ],
                ),
                if (visual.label.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  _CareerMiniBadge(label: visual.label, color: visual.color),
                ],
                if (risk.detail.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _CompactMarkdownBody(
                    content: risk.detail,
                    style: AppTheme.ts(
                      fontSize: 12,
                      height: 1.55,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerInsightGridSection extends StatelessWidget {
  final String body;
  final Color color;
  final IconData icon;

  const _CareerInsightGridSection({
    required this.body,
    required this.color,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final items = _careerSectionItems(body);
    if (items.isEmpty) {
      return _AssistantMarkdownBody(content: body);
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final useGrid = constraints.maxWidth >= 560 && items.length > 1;
        if (!useGrid) {
          return Column(
            children: [
              for (var index = 0; index < items.length; index++) ...[
                _CareerReportItemCard(
                  item: items[index],
                  color: color,
                  icon: icon,
                  index: index + 1,
                  dense: false,
                ),
                if (index < items.length - 1) const SizedBox(height: 8),
              ],
            ],
          );
        }
        return Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (var index = 0; index < items.length; index++)
              SizedBox(
                width: (constraints.maxWidth - 8) / 2,
                child: _CareerReportItemCard(
                  item: items[index],
                  color: color,
                  icon: icon,
                  index: index + 1,
                  dense: true,
                ),
              ),
          ],
        );
      },
    );
  }
}

class _CareerActionListSection extends StatelessWidget {
  final String body;
  final Color color;
  final IconData icon;

  const _CareerActionListSection({
    required this.body,
    required this.color,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final items = _careerSectionItems(body);
    if (items.isEmpty) {
      return _AssistantMarkdownBody(content: body);
    }
    return Column(
      children: [
        for (var index = 0; index < items.length; index++) ...[
          _CareerReportItemCard(
            item: items[index],
            color: color,
            icon: icon,
            index: index + 1,
            dense: false,
          ),
          if (index < items.length - 1) const SizedBox(height: 8),
        ],
      ],
    );
  }
}

class _CareerReportItemCard extends StatelessWidget {
  final _CareerSectionItem item;
  final Color color;
  final IconData icon;
  final int index;
  final bool dense;

  const _CareerReportItemCard({
    required this.item,
    required this.color,
    required this.icon,
    required this.index,
    required this.dense,
  });

  @override
  Widget build(BuildContext context) {
    final visual = _careerItemVisual(
      "${item.title} ${item.detail}",
      fallbackColor: color,
      fallbackIcon: icon,
    );
    return Container(
      width: double.infinity,
      padding: EdgeInsets.fromLTRB(10, dense ? 9 : 10, 10, dense ? 9 : 10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.64),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.9)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 24,
            height: 24,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: visual.color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(8),
              border: Border.all(color: visual.color.withValues(alpha: 0.12)),
            ),
            child: Icon(visual.icon, size: 13, color: visual.color),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (visual.label.isNotEmpty) ...[
                  _CareerMiniBadge(label: visual.label, color: visual.color),
                  const SizedBox(height: 6),
                ],
                if (item.title.isNotEmpty) ...[
                  SelectableText(
                    item.title,
                    style: AppTheme.ts(
                      fontSize: 12.5,
                      height: 1.35,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                  if (item.detail.isNotEmpty) const SizedBox(height: 5),
                ],
                if (item.detail.isNotEmpty)
                  _CompactMarkdownBody(
                    content: item.detail,
                    style: AppTheme.ts(
                      fontSize: 12,
                      height: 1.5,
                      color: AppTheme.textSecondary,
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerMiniBadge extends StatelessWidget {
  final String label;
  final Color color;
  final bool filled;

  const _CareerMiniBadge({
    required this.label,
    required this.color,
    this.filled = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: filled ? 0.14 : 0.08),
        borderRadius: BorderRadius.circular(999),
        border:
            Border.all(color: color.withValues(alpha: filled ? 0.22 : 0.14)),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 10,
          height: 1.1,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }
}

class _CompactMarkdownBody extends StatelessWidget {
  final String content;
  final TextStyle style;

  const _CompactMarkdownBody({
    required this.content,
    required this.style,
  });

  @override
  Widget build(BuildContext context) {
    return _AppMarkdownBody(
      content: content,
      style: style,
      compact: true,
    );
  }
}

class _CareerSummaryField {
  final String label;
  final String value;

  const _CareerSummaryField({required this.label, required this.value});
}

class _CareerSectionItem {
  final String title;
  final String detail;

  const _CareerSectionItem({required this.title, required this.detail});
}

class _CareerLabelValue {
  final String label;
  final String value;

  const _CareerLabelValue({required this.label, required this.value});
}

class _CareerRiskItem {
  final String title;
  final String level;
  final String detail;

  const _CareerRiskItem({
    required this.title,
    required this.level,
    required this.detail,
  });
}

class _CareerItemVisual {
  final String label;
  final IconData icon;
  final Color color;

  const _CareerItemVisual({
    required this.label,
    required this.icon,
    required this.color,
  });
}

class _CareerRiskLevel {
  final String label;
  final IconData icon;
  final Color color;

  const _CareerRiskLevel({
    required this.label,
    required this.icon,
    required this.color,
  });
}

class _AssistantMarkdownBody extends StatelessWidget {
  final String content;

  const _AssistantMarkdownBody({required this.content});

  @override
  Widget build(BuildContext context) {
    return _AppMarkdownBody(
      content: content,
      style: AppTheme.ts(
        fontSize: 15,
        color: AppTheme.textPrimary,
        height: 1.65,
      ),
      enableLatex: _looksLikeLatex(content),
    );
  }
}

class _AppMarkdownBody extends StatelessWidget {
  final String content;
  final TextStyle style;
  final bool compact;
  final bool enableLatex;

  const _AppMarkdownBody({
    required this.content,
    required this.style,
    this.compact = false,
    this.enableLatex = false,
  });

  @override
  Widget build(BuildContext context) {
    if (compact) {
      return GptMarkdown(
        content,
        style: style,
        useDollarSignsForLatex: enableLatex,
        onLinkTap: (url, title) => _copyInlineMarkdownLink(context, url),
      );
    }
    return GptMarkdown(
      content,
      style: style,
      useDollarSignsForLatex: enableLatex,
      onLinkTap: (url, title) => _copyInlineMarkdownLink(context, url),
      codeBuilder: (context, name, code, closed) {
        return _CodeBlockCard(
          language: name,
          code: code,
          closed: closed,
        );
      },
      tableBuilder: (context, tableRows, textStyle, config) {
        return _MarkdownTableCard(
          tableRows: tableRows,
          textStyle: textStyle,
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

class _MarkdownTableCard extends StatelessWidget {
  final List<CustomTableRow> tableRows;
  final TextStyle textStyle;

  const _MarkdownTableCard({
    required this.tableRows,
    required this.textStyle,
  });

  @override
  Widget build(BuildContext context) {
    final normalizedRows = _normalizeTableRows(tableRows);
    if (normalizedRows.isEmpty) {
      return const SizedBox.shrink();
    }
    final schemaRow = normalizedRows.firstWhere(
      (row) => row.fields.isNotEmpty,
      orElse: () => normalizedRows.first,
    );
    final columnCount = schemaRow.fields.length;
    if (columnCount == 0) {
      return const SizedBox.shrink();
    }
    final displayRows = normalizedRows
        .map(
          (row) => CustomTableRow(
            isHeader: row.isHeader,
            fields: row.fields.take(columnCount).toList(),
          ),
        )
        .toList();
    final numericColumns = List<bool>.generate(
      columnCount,
      (columnIndex) => _looksLikeNumericTableColumn(displayRows, columnIndex),
    );

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: EdgeInsets.zero,
        child: UnconstrainedBox(
          alignment: Alignment.centerLeft,
          constrainedAxis: Axis.vertical,
          child: IntrinsicWidth(
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: AppTheme.surface.withValues(alpha: 0.58),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: AppTheme.border),
                boxShadow: [
                  BoxShadow(
                    color: AppTheme.isDark
                        ? Colors.black.withValues(alpha: 0.10)
                        : Colors.black.withValues(alpha: 0.04),
                    blurRadius: 18,
                    offset: const Offset(0, 8),
                  ),
                ],
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: Table(
                  defaultVerticalAlignment: TableCellVerticalAlignment.middle,
                  defaultColumnWidth: const IntrinsicColumnWidth(),
                  children: [
                    for (var rowIndex = 0;
                        rowIndex < displayRows.length;
                        rowIndex += 1)
                      TableRow(
                        decoration: BoxDecoration(
                          color: displayRows[rowIndex].isHeader
                              ? AppTheme.accent.withValues(
                                  alpha: AppTheme.isDark ? 0.18 : 0.12,
                                )
                              : rowIndex.isEven
                                  ? AppTheme.surface.withValues(alpha: 0.96)
                                  : AppTheme.surfaceActive.withValues(
                                      alpha: AppTheme.isDark ? 0.34 : 0.72,
                                    ),
                        ),
                        children: [
                          for (var columnIndex = 0;
                              columnIndex < columnCount;
                              columnIndex += 1)
                            _MarkdownTableCell(
                              text: columnIndex <
                                      displayRows[rowIndex].fields.length
                                  ? displayRows[rowIndex]
                                      .fields[columnIndex]
                                      .data
                                  : '',
                              textStyle: textStyle,
                              isHeader: displayRows[rowIndex].isHeader,
                              alignRight: columnIndex <
                                      displayRows[rowIndex].fields.length
                                  ? displayRows[rowIndex]
                                              .fields[columnIndex]
                                              .alignment ==
                                          TextAlign.right ||
                                      numericColumns[columnIndex]
                                  : numericColumns[columnIndex],
                              showRightBorder: columnIndex < columnCount - 1,
                              showBottomBorder:
                                  rowIndex < displayRows.length - 1,
                            ),
                        ],
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _MarkdownTableCell extends StatelessWidget {
  final String text;
  final TextStyle textStyle;
  final bool isHeader;
  final bool alignRight;
  final bool showRightBorder;
  final bool showBottomBorder;

  const _MarkdownTableCell({
    required this.text,
    required this.textStyle,
    required this.isHeader,
    required this.alignRight,
    required this.showRightBorder,
    required this.showBottomBorder,
  });

  @override
  Widget build(BuildContext context) {
    final cellStyle = textStyle.copyWith(
      fontSize: isHeader ? 13.5 : 14,
      fontWeight: isHeader ? FontWeight.w700 : FontWeight.w500,
      height: 1.55,
      color: isHeader ? AppTheme.textPrimary : AppTheme.textSecondary,
    );
    return Container(
      alignment: alignRight ? Alignment.centerRight : Alignment.centerLeft,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
      decoration: BoxDecoration(
        border: Border(
          right: showRightBorder
              ? BorderSide(color: AppTheme.border)
              : BorderSide.none,
          bottom: showBottomBorder
              ? BorderSide(color: AppTheme.border)
              : BorderSide.none,
        ),
      ),
      child: SelectableText.rich(
        TextSpan(
          style: cellStyle,
          children: _buildPlainInlineSpans(text, cellStyle),
        ),
        textAlign: alignRight ? TextAlign.right : TextAlign.left,
      ),
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
    return _AppMarkdownBody(
      content: content,
      style: AppTheme.ts(
        fontSize: 15,
        color: AppTheme.textPrimary,
        height: 1.65,
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
    final codeTheme = _codeHighlightTheme();
    final rootStyle = (codeTheme['root'] ?? const TextStyle()).merge(
      AppTheme.ts(
        fontSize: 13,
        height: 1.6,
      ).copyWith(fontFamily: 'monospace'),
    );
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 4),
      decoration: BoxDecoration(
        color: _codeSurfaceColor(),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
            decoration: BoxDecoration(
              color: _codeHeaderColor(),
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
                      color: AppTheme.isDark
                          ? const Color(0xFFC5D1DD)
                          : const Color(0xFF445468),
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
                    color: AppTheme.isDark
                        ? const Color(0xFF6D7A88)
                        : const Color(0xFF8A96A3),
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
                SelectableText.rich(
                  TextSpan(
                    style: rootStyle,
                    children: _buildHighlightedCodeSpans(
                      visibleCodeText,
                      widget.language,
                      codeTheme,
                      rootStyle,
                    ),
                  ),
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

Map<String, TextStyle> _codeHighlightTheme() {
  return AppTheme.isDark ? atomOneDarkTheme : atomOneLightTheme;
}

Color _codeSurfaceColor() {
  return AppTheme.isDark ? const Color(0xFF171C22) : const Color(0xFFF5F8FC);
}

Color _codeHeaderColor() {
  return AppTheme.isDark
      ? Colors.white.withValues(alpha: 0.04)
      : const Color(0xFFEFF3F8);
}

List<InlineSpan> _buildHighlightedCodeSpans(
  String source,
  String language,
  Map<String, TextStyle> theme,
  TextStyle rootStyle,
) {
  final normalizedLanguage = _normalizeHighlightLanguage(language);
  final result = _safeParseHighlightedCode(source, normalizedLanguage);
  final nodes = result.nodes;
  if (nodes == null || nodes.isEmpty) {
    return [TextSpan(text: source, style: rootStyle)];
  }
  return _convertHighlightNodes(nodes, theme, rootStyle);
}

hl.Result _safeParseHighlightedCode(String source, String? language) {
  try {
    return hl.highlight.parse(
      source,
      language: language,
      autoDetection: language == null,
    );
  } catch (_) {
    return hl.highlight.parse(
      source,
      autoDetection: true,
    );
  }
}

List<InlineSpan> _convertHighlightNodes(
  List<Node> nodes,
  Map<String, TextStyle> theme,
  TextStyle rootStyle,
) {
  List<InlineSpan> traverse(List<Node> input, TextStyle inheritedStyle) {
    final spans = <InlineSpan>[];
    for (final node in input) {
      final nodeStyle = node.className == null
          ? inheritedStyle
          : inheritedStyle.merge(theme[node.className!]);
      if (node.value != null) {
        spans.add(
          TextSpan(
            text: node.value,
            style: nodeStyle,
          ),
        );
        continue;
      }
      final children = node.children;
      if (children == null || children.isEmpty) {
        continue;
      }
      spans.add(
        TextSpan(
          style: nodeStyle,
          children: traverse(children, nodeStyle),
        ),
      );
    }
    return spans;
  }

  return traverse(nodes, rootStyle);
}

String? _normalizeHighlightLanguage(String language) {
  final normalized = language.trim().toLowerCase();
  if (normalized.isEmpty || normalized == 'text' || normalized == 'plaintext') {
    return null;
  }
  const aliases = <String, String>{
    'py': 'python',
    'js': 'javascript',
    'ts': 'typescript',
    'shell': 'bash',
    'sh': 'bash',
    'zsh': 'bash',
    'md': 'markdown',
    'yml': 'yaml',
    'rb': 'ruby',
    'rs': 'rust',
    'kt': 'kotlin',
    'c++': 'cpp',
    'c#': 'csharp',
    'objc': 'objectivec',
  };
  return aliases[normalized] ?? normalized;
}

bool _looksLikeNumericTableColumn(List<CustomTableRow> rows, int columnIndex) {
  final values = <String>[];
  for (final row in rows) {
    if (row.isHeader || columnIndex >= row.fields.length) {
      continue;
    }
    final value = row.fields[columnIndex].data.trim();
    if (value.isNotEmpty) {
      values.add(value);
    }
  }
  if (values.isEmpty) {
    return false;
  }
  final numericLikeCount = values.where(_looksLikeNumericTableCell).length;
  return numericLikeCount >= ((values.length + 1) ~/ 2);
}

List<CustomTableRow> _trimEmptyTableColumns(List<CustomTableRow> rows) {
  if (rows.isEmpty) {
    return const [];
  }
  final maxColumns = rows.fold<int>(
    0,
    (maxCount, row) =>
        row.fields.length > maxCount ? row.fields.length : maxCount,
  );
  if (maxColumns == 0) {
    return const [];
  }

  var start = 0;
  var end = maxColumns - 1;

  while (start <= end && _isTableColumnEmpty(rows, start)) {
    start += 1;
  }
  while (end >= start && _isTableColumnEmpty(rows, end)) {
    end -= 1;
  }

  if (start > end) {
    return const [];
  }

  return rows
      .map(
        (row) => CustomTableRow(
          isHeader: row.isHeader,
          fields: row.fields.sublist(
            start.clamp(0, row.fields.length),
            end + 1 > row.fields.length ? row.fields.length : end + 1,
          ),
        ),
      )
      .toList();
}

List<CustomTableRow> _normalizeTableRows(List<CustomTableRow> rows) {
  final trimmedRows = rows
      .map((row) {
        final normalizedFields = row.fields
            .map(
              (field) => CustomTableField(
                data: field.data.trim(),
                alignment: field.alignment,
              ),
            )
            .toList();
        var end = normalizedFields.length;
        while (end > 0 &&
            _normalizedTableCellValue(normalizedFields[end - 1].data).isEmpty) {
          end -= 1;
        }
        var start = 0;
        while (start < end &&
            _normalizedTableCellValue(normalizedFields[start].data).isEmpty) {
          start += 1;
        }
        return CustomTableRow(
          isHeader: row.isHeader,
          fields: normalizedFields.sublist(start, end),
        );
      })
      .where((row) => row.fields.isNotEmpty)
      .toList();
  return _trimEmptyTableColumns(trimmedRows);
}

bool _isTableColumnEmpty(List<CustomTableRow> rows, int columnIndex) {
  for (final row in rows) {
    if (columnIndex >= row.fields.length) {
      continue;
    }
    if (_normalizedTableCellValue(row.fields[columnIndex].data).isNotEmpty) {
      return false;
    }
  }
  return true;
}

String _normalizedTableCellValue(String value) {
  return value
      .replaceAll(RegExp(r'[\u00A0\u200B-\u200D\uFEFF]'), '')
      .replaceAll('&nbsp;', '')
      .replaceAll(RegExp(r'[\s\r\n\t]+'), '')
      .replaceAll(RegExp(r'^[:\-|]+$'), '')
      .trim();
}

bool _looksLikeNumericTableCell(String value) {
  final normalized = value.replaceAll(',', '').replaceAll('，', '').trim();
  if (normalized.isEmpty) {
    return false;
  }
  final patterns = <RegExp>[
    RegExp(r'^[¥￥$]?\d+(\.\d+)?([万千百十亿])?([/%])?$'),
    RegExp(
        r'^约?[¥￥$]?\d+(\.\d+)?\s*[-~～]\s*[¥￥$]?\d+(\.\d+)?([万千百十亿])?([/%])?$'),
    RegExp(r'^\d+\s*[-~～]\s*\d+([/%])?$'),
    RegExp(r'^\d+(\.\d+)?\s*(元|万元|天|晚|小时|km|公里|人|项)$'),
  ];
  return patterns.any((pattern) => pattern.hasMatch(normalized));
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

bool _shouldUseLeadParagraph(List<String> paragraphs) {
  if (paragraphs.length < 2) {
    return false;
  }
  return _isShortLeadText(paragraphs.first);
}

bool _isShortLeadText(String text) {
  final trimmed = text.trim();
  if (trimmed.isEmpty || trimmed.length > _leadParagraphMaxChars) {
    return false;
  }
  if (trimmed.contains('\n')) {
    return false;
  }
  if (RegExp(r'^[-*•\d]').hasMatch(trimmed)) {
    return false;
  }
  return true;
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

class _CareerAssetReferenceStrip extends ConsumerWidget {
  final List<_DetectedCareerAsset> assets;

  const _CareerAssetReferenceStrip({required this.assets});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (assets.isEmpty) {
      return const SizedBox.shrink();
    }
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.surfaceActive.withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.86)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.inventory_2_outlined,
                  size: 15, color: AppTheme.accent),
              const SizedBox(width: 7),
              Text(
                "已创建的求职资产",
                style: AppTheme.ts(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textPrimary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final asset in assets)
                _CareerAssetReferenceCard(asset: asset),
            ],
          ),
        ],
      ),
    );
  }
}

class _CareerAssetReferenceCard extends ConsumerWidget {
  final _DetectedCareerAsset asset;

  const _CareerAssetReferenceCard({required this.asset});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(chatProvider);
    final sessionArtifact = asset.kind == _CareerAssetKind.artifact
        ? _findSessionArtifact(chat.sessionArtifacts, asset.id)
        : null;
    final title = sessionArtifact?.title ?? asset.title;
    final subtitle = asset.kind == _CareerAssetKind.artifact
        ? (sessionArtifact == null
            ? "资产编号 ${asset.id}"
            : "${sessionArtifact.sizeDisplay} · ${_artifactStatusLabel(sessionArtifact.status)}")
        : asset.id;

    return Container(
      width: 238,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(9),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: asset.color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(asset.icon, size: 15, color: asset.color),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      asset.label,
                      style: AppTheme.ts(
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                        color: asset.color,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 7),
          SelectableText(
            subtitle,
            style: AppTheme.ts(
              fontSize: 10.5,
              color: AppTheme.textTertiary,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 4,
            runSpacing: 4,
            children: [
              if (asset.kind == _CareerAssetKind.artifact) ...[
                _ArtifactActionButton(
                  label: "预览",
                  icon: Icons.visibility_outlined,
                  primary: true,
                  onPressed: () =>
                      _previewSessionArtifact(context, ref, asset.id),
                ),
                _ArtifactActionButton(
                  label: "下载",
                  icon: Icons.download_rounded,
                  primary: true,
                  onPressed: () =>
                      _downloadSessionArtifact(context, ref, asset.id),
                ),
              ] else
                _ArtifactActionButton(
                  label: "详情",
                  icon: Icons.open_in_new_rounded,
                  primary: true,
                  onPressed: () => _selectCareerAsset(context, ref, asset),
                ),
              _ArtifactActionButton(
                label: "复制 ID",
                icon: Icons.content_copy_rounded,
                onPressed: () => _copyText(context, asset.id, "资产编号已复制"),
              ),
            ],
          ),
        ],
      ),
    );
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
    final artifactId = _artifactIdFromPath(artifact);
    final sessionArtifact = artifactId == null
        ? null
        : _findSessionArtifact(provider.sessionArtifacts, artifactId);
    final title =
        sessionArtifact?.title ?? artifactId ?? _displayPathName(artifact.path);
    final meta = sessionArtifact == null
        ? (artifactId == null ? artifact.path : "资产编号 $artifactId")
        : "${sessionArtifact.sizeDisplay} · ${_artifactStatusLabel(sessionArtifact.status)}";
    final isActiveArtifact =
        artifactId != null && provider.activeArtifactIds.contains(artifactId);

    return Container(
      constraints: const BoxConstraints(maxWidth: 360),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
      decoration: BoxDecoration(
        color: isGenerated
            ? AppTheme.accent.withValues(alpha: 0.08)
            : AppTheme.surfaceActive,
        borderRadius: BorderRadius.circular(10),
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
                Text(
                  title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w700,
                    color: AppTheme.textPrimary,
                  ),
                ),
                const SizedBox(height: 3),
                SelectableText(
                  meta,
                  style: AppTheme.ts(
                    fontSize: 11,
                    color: AppTheme.textTertiary,
                    height: 1.35,
                  ),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 4,
                  runSpacing: 4,
                  children: [
                    if (artifactId != null) ...[
                      _ArtifactActionButton(
                        label: "预览",
                        icon: Icons.visibility_outlined,
                        primary: true,
                        onPressed: () =>
                            _previewSessionArtifact(context, ref, artifactId),
                      ),
                      _ArtifactActionButton(
                        label: "下载",
                        icon: Icons.download_rounded,
                        primary: true,
                        onPressed: () =>
                            _downloadSessionArtifact(context, ref, artifactId),
                      ),
                      _ArtifactActionButton(
                        label: isActiveArtifact ? "已激活" : "激活资料",
                        icon: isActiveArtifact
                            ? Icons.check_circle_outline_rounded
                            : Icons.push_pin_outlined,
                        enabled: !isActiveArtifact,
                        primary: !isActiveArtifact,
                        onPressed: () async {
                          final activated = await ref
                              .read(chatProvider)
                              .activateArtifact(artifactId);
                          if (!context.mounted) return;
                          if (!activated) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                content: Text("激活资料失败"),
                                duration: Duration(seconds: 1),
                              ),
                            );
                            return;
                          }
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              content: Text(
                                sessionArtifact == null
                                    ? "已激活资料 $artifactId"
                                    : "已激活资料 ${sessionArtifact.title}",
                              ),
                              duration: const Duration(seconds: 1),
                            ),
                          );
                        },
                      ),
                      _ArtifactActionButton(
                        label: "复制 ID",
                        icon: Icons.content_copy_rounded,
                        onPressed: () =>
                            _copyText(context, artifactId, "资产编号已复制"),
                      ),
                    ] else ...[
                      _ArtifactActionButton(
                        label: "查看内容",
                        icon: Icons.visibility_outlined,
                        primary: true,
                        onPressed: () => _previewWorkspaceArtifact(
                            context, ref, artifact.path),
                      ),
                      _ArtifactActionButton(
                        label: "复制路径",
                        icon: Icons.content_copy_rounded,
                        onPressed: () =>
                            _copyText(context, artifact.path, "路径已复制"),
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
  final bool primary;
  final Future<void> Function() onPressed;

  const _ArtifactActionButton({
    required this.label,
    required this.icon,
    required this.onPressed,
    this.enabled = true,
    this.primary = false,
  });

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: enabled ? () => unawaited(onPressed()) : null,
      style: TextButton.styleFrom(
        foregroundColor: enabled
            ? (primary ? AppTheme.accent : AppTheme.textSecondary)
            : AppTheme.textTertiary,
        backgroundColor: enabled && primary
            ? AppTheme.accent.withValues(alpha: 0.1)
            : Colors.transparent,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        side: primary && enabled
            ? BorderSide(color: AppTheme.accent.withValues(alpha: 0.18))
            : BorderSide.none,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        textStyle: AppTheme.ts(
          fontSize: 12,
          fontWeight: primary ? FontWeight.w700 : FontWeight.w600,
        ),
      ),
      icon: Icon(icon, size: 14),
      label: Text(label),
    );
  }
}

Future<void> _previewSessionArtifact(
  BuildContext context,
  WidgetRef ref,
  String artifactId,
) async {
  SessionArtifactContentView preview;
  try {
    preview = await ref.read(chatProvider).readSessionArtifactContent(
          artifactId,
        );
  } catch (error) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text("读取 artifact 预览失败: $error"),
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
    builder: (sheetContext) => _SessionArtifactPreviewSheet(preview: preview),
  );
}

Future<void> _downloadSessionArtifact(
  BuildContext context,
  WidgetRef ref,
  String artifactId,
) async {
  final url = ref.read(chatProvider).sessionArtifactDownloadUrl(artifactId);
  if (url == null || url.isEmpty) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text("当前会话没有可下载的 artifact"),
        duration: Duration(seconds: 1),
      ),
    );
    return;
  }
  try {
    openDownloadUrl(url);
  } catch (_) {
    await Clipboard.setData(ClipboardData(text: url));
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text("下载链接已复制"),
        duration: Duration(seconds: 1),
      ),
    );
  }
}

Future<void> _copyText(
  BuildContext context,
  String text,
  String message,
) async {
  await Clipboard.setData(ClipboardData(text: text));
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      duration: const Duration(seconds: 1),
    ),
  );
}

Future<void> _selectCareerAsset(
  BuildContext context,
  WidgetRef ref,
  _DetectedCareerAsset asset,
) async {
  final provider = ref.read(careerAssetsProvider);
  await provider.ensureLoaded();
  Object? record = _findCareerRecord(provider, asset);
  if (record == null) {
    await provider.refresh();
    record = _findCareerRecord(provider, asset);
  }
  if (!context.mounted) return;
  if (record == null) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text("未找到求职资产 ${asset.id}"),
        duration: const Duration(seconds: 2),
      ),
    );
    return;
  }
  provider.setTab(_careerAssetsTabForKind(asset.kind));
  provider.selectRecord(record);
  ScaffoldMessenger.of(context).showSnackBar(
    const SnackBar(
      content: Text("已在右侧求职资产面板定位"),
      duration: Duration(seconds: 1),
    ),
  );
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

class _SessionArtifactPreviewSheet extends StatelessWidget {
  final SessionArtifactContentView preview;

  const _SessionArtifactPreviewSheet({required this.preview});

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
                        color: AppTheme.accent.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: AppTheme.accent.withValues(alpha: 0.22),
                        ),
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
                            preview.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                          const SizedBox(height: 4),
                          SelectableText(
                            "资产编号 ${preview.artifactId}",
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
                      label:
                          "${preview.returnedChars}/${preview.totalChars} 字符",
                    ),
                    _PreviewMetaChip(
                      icon: Icons.badge_outlined,
                      label: preview.status,
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
                      answerFormat: _artifactAnswerFormat(preview.mediaType),
                      renderHint: _artifactRenderHint(preview.mediaType),
                      layoutHint: 'paragraph',
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

String? _artifactIdFromPath(AnswerArtifactView artifact) {
  const prefix = "artifact_id:";
  if (!artifact.path.startsWith(prefix)) {
    final value = artifact.path.trim();
    return RegExp(r'^artifact_[A-Za-z0-9][A-Za-z0-9_-]*$').hasMatch(value)
        ? value
        : null;
  }
  final value = artifact.path.substring(prefix.length).trim();
  return value.isEmpty ? null : value;
}

Set<String> _artifactIdsFromAnswerArtifacts(
    List<AnswerArtifactView> artifacts) {
  final output = <String>{};
  for (final artifact in artifacts) {
    final artifactId = _artifactIdFromPath(artifact);
    if (artifactId != null) {
      output.add(artifactId);
    }
  }
  return output;
}

SessionArtifactView? _findSessionArtifact(
  List<SessionArtifactView> artifacts,
  String artifactId,
) {
  for (final artifact in artifacts) {
    if (artifact.artifactId == artifactId) {
      return artifact;
    }
  }
  return null;
}

String _displayPathName(String path) {
  final parts = path.split(RegExp(r'[\\/]'));
  final last = parts.isEmpty ? path : parts.last.trim();
  return last.isEmpty ? path : last;
}

String _artifactStatusLabel(String status) {
  return switch (status) {
    "ready" => "可预览",
    "uploaded" => "待解析",
    "failed" => "解析失败",
    _ => status,
  };
}

String _artifactAnswerFormat(String mediaType) {
  if (mediaType.contains("markdown")) {
    return "markdown";
  }
  return "plain_text";
}

String _artifactRenderHint(String mediaType) {
  if (mediaType.contains("markdown")) {
    return "markdown_document";
  }
  return "plain";
}

enum _CareerAssetKind {
  artifact,
  resumeProfile,
  careerProfile,
  jdAnalysis,
  jobFitReport,
  resumeVersion,
}

class _DetectedCareerAsset {
  final _CareerAssetKind kind;
  final String id;

  const _DetectedCareerAsset({
    required this.kind,
    required this.id,
  });

  String get label => switch (kind) {
        _CareerAssetKind.artifact => "文件",
        _CareerAssetKind.resumeProfile => "简历画像",
        _CareerAssetKind.careerProfile => "职业画像",
        _CareerAssetKind.jdAnalysis => "JD 分析",
        _CareerAssetKind.jobFitReport => "匹配报告",
        _CareerAssetKind.resumeVersion => "简历版本",
      };

  String get title => switch (kind) {
        _CareerAssetKind.artifact => id,
        _ => label,
      };

  IconData get icon => switch (kind) {
        _CareerAssetKind.artifact => Icons.description_outlined,
        _CareerAssetKind.resumeProfile => Icons.badge_outlined,
        _CareerAssetKind.careerProfile => Icons.track_changes_rounded,
        _CareerAssetKind.jdAnalysis => Icons.article_outlined,
        _CareerAssetKind.jobFitReport => Icons.fact_check_outlined,
        _CareerAssetKind.resumeVersion => Icons.edit_note_rounded,
      };

  Color get color => switch (kind) {
        _CareerAssetKind.artifact => AppTheme.accent,
        _CareerAssetKind.resumeProfile => const Color(0xFF0F9B78),
        _CareerAssetKind.careerProfile => const Color(0xFF2563EB),
        _CareerAssetKind.jdAnalysis => const Color(0xFF7C3AED),
        _CareerAssetKind.jobFitReport => const Color(0xFFB45309),
        _CareerAssetKind.resumeVersion => const Color(0xFFDC2626),
      };
}

class _CareerMessagePresentation {
  final String content;
  final List<_DetectedCareerAsset> assets;

  const _CareerMessagePresentation({
    required this.content,
    required this.assets,
  });

  factory _CareerMessagePresentation.fromContent(String rawContent) {
    final assets = _extractCareerAssets(rawContent);
    final content = assets.isEmpty
        ? rawContent.trim()
        : _removeCareerAssetReferenceBlock(rawContent, assets);
    return _CareerMessagePresentation(content: content, assets: assets);
  }
}

List<_DetectedCareerAsset> _extractCareerAssets(String content) {
  final byId = <String, _DetectedCareerAsset>{};
  void collect(RegExp pattern, _CareerAssetKind kind) {
    for (final match in pattern.allMatches(content)) {
      final id = match.group(0)?.trim();
      if (id == null || id.isEmpty) continue;
      if (_isCareerAssetFieldName(id)) continue;
      byId.putIfAbsent(id, () => _DetectedCareerAsset(kind: kind, id: id));
    }
  }

  collect(RegExp(r'\bartifact_[A-Za-z0-9][A-Za-z0-9_-]*\b'),
      _CareerAssetKind.artifact);
  collect(RegExp(r'\bresume_profile_[A-Za-z0-9][A-Za-z0-9_-]*\b'),
      _CareerAssetKind.resumeProfile);
  collect(RegExp(r'\bcareer_profile_[A-Za-z0-9][A-Za-z0-9_-]*\b'),
      _CareerAssetKind.careerProfile);
  collect(
      RegExp(r'\bjd_[A-Za-z0-9][A-Za-z0-9_-]*\b'), _CareerAssetKind.jdAnalysis);
  collect(RegExp(r'\bfit_[A-Za-z0-9][A-Za-z0-9_-]*\b'),
      _CareerAssetKind.jobFitReport);
  collect(RegExp(r'\bresume_version_[A-Za-z0-9][A-Za-z0-9_-]*\b'),
      _CareerAssetKind.resumeVersion);
  return byId.values.toList();
}

bool _isCareerAssetFieldName(String id) {
  return {
    "artifact_id",
    "resume_profile_id",
    "career_profile_id",
    "jd_analysis",
    "jd_analysis_id",
    "fit_report_id",
    "job_fit_report_id",
    "resume_version_id",
  }.contains(id);
}

String _removeCareerAssetReferenceBlock(
  String content,
  List<_DetectedCareerAsset> assets,
) {
  final lines =
      content.replaceAll('\r\n', '\n').replaceAll('\r', '\n').split('\n');
  final output = <String>[];
  var inAssetBlock = false;
  for (final line in lines) {
    final trimmed = line.trim();
    if (_isCareerAssetBlockHeader(trimmed)) {
      inAssetBlock = true;
      continue;
    }
    if (inAssetBlock) {
      if (trimmed.isEmpty) {
        continue;
      }
      if (_lineContainsKnownAsset(trimmed, assets) ||
          RegExp(r'^[-*•]\s*').hasMatch(trimmed)) {
        continue;
      }
      inAssetBlock = false;
    }
    if (_isStandaloneAssetLine(trimmed, assets)) {
      continue;
    }
    output.add(line);
  }
  return output.join('\n').replaceAll(RegExp(r'\n{3,}'), '\n\n').trim();
}

bool _isCareerAssetBlockHeader(String line) {
  return RegExp(r'已创建.*(产品记录|求职资产)').hasMatch(line) ||
      RegExp(r'^(产品记录|求职资产)[:：]?$').hasMatch(line);
}

bool _lineContainsKnownAsset(
  String line,
  List<_DetectedCareerAsset> assets,
) {
  return assets.any((asset) => line.contains(asset.id));
}

bool _isStandaloneAssetLine(
  String line,
  List<_DetectedCareerAsset> assets,
) {
  if (!_lineContainsKnownAsset(line, assets)) {
    return false;
  }
  if (RegExp(r'^[-*•]\s*').hasMatch(line)) {
    return true;
  }
  return RegExp(r'^(简历画像|诊断报告|职业档案|职业画像|JD 分析|匹配报告|简历版本|来源文件)[:：]')
      .hasMatch(line);
}

Object? _findCareerRecord(
  CareerAssetsProvider provider,
  _DetectedCareerAsset asset,
) {
  if (asset.kind == _CareerAssetKind.resumeProfile) {
    for (final record in provider.resumeProfiles) {
      if (record.resumeProfileId == asset.id) return record;
    }
    return null;
  }
  if (asset.kind == _CareerAssetKind.careerProfile) {
    for (final record in provider.careerProfiles) {
      if (record.careerProfileId == asset.id) return record;
    }
    return null;
  }
  if (asset.kind == _CareerAssetKind.jdAnalysis) {
    for (final record in provider.jdAnalyses) {
      if (record.jdAnalysisId == asset.id) return record;
    }
    return null;
  }
  if (asset.kind == _CareerAssetKind.jobFitReport) {
    for (final record in provider.jobFitReports) {
      if (record.jobFitReportId == asset.id) return record;
    }
    return null;
  }
  if (asset.kind == _CareerAssetKind.resumeVersion) {
    for (final record in provider.resumeVersions) {
      if (record.resumeVersionId == asset.id) return record;
    }
    return null;
  }
  return null;
}

CareerAssetsTab _careerAssetsTabForKind(_CareerAssetKind kind) {
  return switch (kind) {
    _CareerAssetKind.resumeProfile => CareerAssetsTab.resumes,
    _CareerAssetKind.careerProfile => CareerAssetsTab.profiles,
    _CareerAssetKind.jdAnalysis => CareerAssetsTab.jobs,
    _CareerAssetKind.jobFitReport => CareerAssetsTab.fitReports,
    _CareerAssetKind.resumeVersion => CareerAssetsTab.versions,
    _CareerAssetKind.artifact => CareerAssetsTab.all,
  };
}

class _CareerReportPresentation {
  final String lead;
  final List<_CareerReportSection> sections;

  const _CareerReportPresentation({
    required this.lead,
    required this.sections,
  });

  static _CareerReportPresentation? tryParse(String content) {
    final normalized =
        content.replaceAll('\r\n', '\n').replaceAll('\r', '\n').trim();
    if (!_looksLikeCareerReport(normalized)) {
      return null;
    }
    final leadLines = <String>[];
    final sections = <_CareerReportSection>[];
    String? currentTitle;
    final currentBody = <String>[];

    void flushSection() {
      final title = currentTitle;
      if (title == null) return;
      sections.add(
        _CareerReportSection(
          title: title,
          body: currentBody.join('\n').trim(),
        ),
      );
      currentBody.clear();
    }

    for (final rawLine in normalized.split('\n')) {
      final heading = _careerSectionHeading(rawLine);
      if (heading != null) {
        flushSection();
        currentTitle = heading;
        continue;
      }
      final trimmed = rawLine.trim();
      if (currentTitle == null) {
        if (trimmed == '---' || trimmed.isEmpty) {
          continue;
        }
        leadLines.add(rawLine);
      } else {
        currentBody.add(rawLine);
      }
    }
    flushSection();
    if (sections.length < 2) {
      return null;
    }
    return _CareerReportPresentation(
      lead: leadLines.join('\n').trim(),
      sections: sections,
    );
  }
}

class _CareerReportSection {
  final String title;
  final String body;

  const _CareerReportSection({
    required this.title,
    required this.body,
  });
}

String _careerReportDisplayTitle(_CareerReportPresentation report) {
  final joinedTitles =
      report.sections.map((section) => section.title).join(" ");
  if (joinedTitles.contains("匹配") || joinedTitles.contains("差距")) {
    return "岗位匹配报告";
  }
  if (joinedTitles.contains("JD")) {
    return "JD 分析报告";
  }
  if (joinedTitles.contains("优化")) {
    return "简历优化报告";
  }
  return "简历诊断报告";
}

String _careerLeadContent(String content) {
  final lines =
      content.replaceAll("\r\n", "\n").replaceAll("\r", "\n").split("\n");
  final output = <String>[];
  for (final rawLine in lines) {
    final trimmed = rawLine.trim();
    if (trimmed.isEmpty || trimmed == "---") {
      continue;
    }
    final heading = trimmed.replaceFirst(RegExp(r"^#{1,6}\s*"), "").trim();
    final duplicatedReportTitle = trimmed.startsWith("#") &&
        (heading.contains("诊断报告") ||
            heading.contains("匹配报告") ||
            heading.contains("分析报告") ||
            heading.contains("优化报告"));
    if (duplicatedReportTitle) {
      continue;
    }
    output.add(rawLine);
  }
  return output.join("\n").trim();
}

bool _isSummarySection(String title) {
  return title.contains("摘要");
}

bool _isInsightGridSection(String title) {
  return title.contains("优势");
}

bool _isRiskSection(String title) {
  return title.contains("风险") || title.contains("差距");
}

bool _isActionListSection(String title) {
  return title.contains("建议") || title.contains("优化") || title.contains("面试");
}

List<_CareerSummaryField> _careerSummaryFields(String body) {
  final fields = <_CareerSummaryField>[];
  for (final rawLine in body.split("\n")) {
    final line = _careerDisplayLine(rawLine);
    if (line.isEmpty) {
      continue;
    }
    final field = _splitCareerLabelValue(line, maxLabelChars: 24);
    if (field == null) {
      continue;
    }
    fields.add(_CareerSummaryField(label: field.label, value: field.value));
    if (fields.length >= 8) {
      break;
    }
  }
  return fields;
}

List<_CareerSectionItem> _careerSectionItems(String body) {
  final groups = <String>[];
  final current = <String>[];

  void flush() {
    final value = current.join("\n").trim();
    if (value.isNotEmpty) {
      groups.add(value);
    }
    current.clear();
  }

  for (final rawLine in body.split("\n")) {
    final trimmed = rawLine.trim();
    if (trimmed.isEmpty) {
      continue;
    }
    final startsItem = RegExp(r"^(\d+[\.\)、]|[-*•])\s+").hasMatch(trimmed);
    final line = _careerDisplayLine(rawLine);
    if (line.isEmpty) {
      continue;
    }
    if (startsItem) {
      flush();
    }
    current.add(line);
  }
  flush();
  if (groups.isEmpty && body.trim().isNotEmpty) {
    groups.add(_careerDisplayBlock(body));
  }
  return groups
      .where((item) => item.isNotEmpty)
      .map(_careerSectionItemFromText)
      .toList();
}

_CareerSectionItem _careerSectionItemFromText(String text) {
  final normalized = text.trim();
  final field = _splitCareerLabelValue(normalized, maxLabelChars: 36);
  if (field != null) {
    return _CareerSectionItem(title: field.label, detail: field.value);
  }
  return _CareerSectionItem(title: "", detail: normalized);
}

String _normalizeCareerReportLine(String value) {
  return _stripMarkdownInline(_careerDisplayLine(value))
      .replaceAll(RegExp(r"[ \t]+"), " ")
      .trim();
}

String _careerDisplayLine(String value) {
  return value
      .trim()
      .replaceFirst(RegExp(r"^#{1,6}\s*"), "")
      .replaceFirst(RegExp(r"^(\d+[\.\)、]|[-*•])\s+"), "")
      .trim();
}

String _careerDisplayBlock(String value) {
  return value
      .replaceAll("\r\n", "\n")
      .replaceAll("\r", "\n")
      .split("\n")
      .map(_careerDisplayLine)
      .where((line) => line.isNotEmpty)
      .join("\n")
      .trim();
}

_CareerLabelValue? _splitCareerLabelValue(
  String line, {
  required int maxLabelChars,
}) {
  final normalized = line.trim();
  if (normalized.isEmpty) {
    return null;
  }
  final boldLabelPatterns = [
    RegExp(r"^\*\*([^*\n:：]{1,48})[:：]\*\*\s*(.+)$", dotAll: true),
    RegExp(r"^__([^_\n:：]{1,48})[:：]__\s*(.+)$", dotAll: true),
    RegExp(r"^\*\*([^*\n]{1,48})\*\*\s*[:：]\s*(.+)$", dotAll: true),
    RegExp(r"^__([^_\n]{1,48})__\s*[:：]\s*(.+)$", dotAll: true),
  ];
  for (final pattern in boldLabelPatterns) {
    final match = pattern.firstMatch(normalized);
    if (match == null) {
      continue;
    }
    final label = _stripMarkdownInline(match.group(1) ?? "").trim();
    final value = _cleanCareerMarkdownValue(match.group(2) ?? "");
    if (label.isNotEmpty && label.length <= maxLabelChars && value.isNotEmpty) {
      return _CareerLabelValue(label: label, value: value);
    }
  }
  final separator = RegExp(r"[:：]").firstMatch(normalized);
  if (separator == null || separator.start == 0) {
    return null;
  }
  final label =
      _stripMarkdownInline(normalized.substring(0, separator.start)).trim();
  final value = _cleanCareerMarkdownValue(normalized.substring(separator.end));
  if (label.isEmpty || label.length > maxLabelChars || value.isEmpty) {
    return null;
  }
  return _CareerLabelValue(label: label, value: value);
}

String _cleanCareerMarkdownValue(String value) {
  return value
      .trim()
      .replaceFirst(RegExp(r"^(\*\*|__)\s*"), "")
      .replaceFirst(RegExp(r"\s*(\*\*|__)$"), "")
      .trim();
}

String _stripMarkdownInline(String value) {
  return value
      .replaceAllMapped(
        RegExp(r"\*\*([^*]+)\*\*"),
        (match) => match.group(1) ?? "",
      )
      .replaceAllMapped(
        RegExp(r"__([^_]+)__"),
        (match) => match.group(1) ?? "",
      )
      .replaceAllMapped(
        RegExp(r"\[([^\]]+)\]\([^)]+\)"),
        (match) => match.group(1) ?? "",
      )
      .replaceAllMapped(
        RegExp(r"`([^`]+)`"),
        (match) => match.group(1) ?? "",
      )
      .trim();
}

List<_CareerRiskItem> _careerRiskItems(String body) {
  final risks = <_CareerRiskItem>[];
  final fallbackItems = <_CareerSectionItem>[];

  for (final rawLine in body.split("\n")) {
    final displayLine = _careerDisplayLine(rawLine);
    final plainLine = _normalizeCareerReportLine(rawLine);
    if (displayLine.isEmpty || _isMarkdownTableDivider(displayLine)) {
      continue;
    }
    final risk = _riskItemFromPipeLine(displayLine);
    if (risk != null) {
      risks.add(risk);
      continue;
    }
    if (!_isMarkdownTableHeader(plainLine)) {
      fallbackItems.add(_careerSectionItemFromText(displayLine));
    }
  }

  if (risks.isNotEmpty) {
    return risks;
  }

  return fallbackItems
      .where((item) => item.title.isNotEmpty || item.detail.isNotEmpty)
      .map(
        (item) => _CareerRiskItem(
          title: item.title.isEmpty
              ? _riskTitleFromDetail(item.detail)
              : item.title,
          level: _riskLevelFromText("${item.title} ${item.detail}"),
          detail: item.title.isEmpty ? item.detail : item.detail,
        ),
      )
      .toList();
}

_CareerRiskItem? _riskItemFromPipeLine(String line) {
  var normalized = line
      .replaceFirst(RegExp(r"^\|"), "")
      .replaceFirst(RegExp(r"\|$"), "")
      .trim();
  normalized = normalized
      .replaceFirst(RegExp(r"^\[[^\]]*(风险项|等级|说明)[^\]]*\]\s*\|?\s*"), "")
      .trim();
  if (_isMarkdownTableHeader(normalized)) {
    return null;
  }
  final delimiter = normalized.contains("|") ? "|" : "｜";
  final parts = normalized
      .split(delimiter)
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();
  if (parts.length < 3) {
    return null;
  }
  final title = _stripMarkdownInline(parts[0]).trim();
  final level = _stripMarkdownInline(parts[1]).trim();
  final detail = _cleanCareerMarkdownValue(parts.sublist(2).join(" | "));
  if (title.isEmpty || detail.isEmpty) {
    return null;
  }
  return _CareerRiskItem(title: title, level: level, detail: detail);
}

bool _isMarkdownTableHeader(String line) {
  final compact = _stripMarkdownInline(line).replaceAll(" ", "");
  return compact.contains("风险项") &&
      compact.contains("等级") &&
      compact.contains("说明");
}

bool _isMarkdownTableDivider(String line) {
  return RegExp(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$").hasMatch(line);
}

String _riskTitleFromDetail(String detail) {
  final clean = _stripMarkdownInline(detail).trim();
  final separator = RegExp(r"[，,。；;]").firstMatch(clean);
  if (separator == null || separator.start < 4) {
    return clean.length > 18 ? "${clean.substring(0, 18)}..." : clean;
  }
  return clean.substring(0, separator.start).trim();
}

String _riskLevelFromText(String text) {
  if (RegExp(r"(高风险|严重|高\s*[｜|:]|等级[:：]?\s*高)").hasMatch(text)) {
    return "高";
  }
  if (RegExp(r"(低风险|轻微|低\s*[｜|:]|等级[:：]?\s*低)").hasMatch(text)) {
    return "低";
  }
  if (RegExp(r"(中风险|中等|中\s*[｜|:]|等级[:：]?\s*中)").hasMatch(text)) {
    return "中";
  }
  return "中";
}

_CareerRiskLevel _careerRiskLevel(String value) {
  final normalized = value.trim();
  if (normalized.contains("高")) {
    return const _CareerRiskLevel(
      label: "高风险",
      icon: Icons.priority_high_rounded,
      color: Color(0xFFDC2626),
    );
  }
  if (normalized.contains("低")) {
    return const _CareerRiskLevel(
      label: "低风险",
      icon: Icons.info_outline_rounded,
      color: Color(0xFF0F766E),
    );
  }
  return const _CareerRiskLevel(
    label: "中风险",
    icon: Icons.warning_amber_rounded,
    color: Color(0xFFB45309),
  );
}

_CareerItemVisual _careerItemVisual(
  String text, {
  required Color fallbackColor,
  required IconData fallbackIcon,
}) {
  final value = _stripMarkdownInline(text).toLowerCase();
  if (_containsAny(value, [
    "python",
    "fastapi",
    "postgres",
    "redis",
    "mysql",
    "elasticsearch",
    "pydantic",
    "技术栈",
    "后端"
  ])) {
    return const _CareerItemVisual(
      label: "技术栈",
      icon: Icons.terminal_rounded,
      color: Color(0xFF0F9B78),
    );
  }
  if (_containsAny(value,
      ["pytest", "mypy", "测试", "覆盖率", "ci", "cd", "github actions", "质量"])) {
    return const _CareerItemVisual(
      label: "质量验证",
      icon: Icons.verified_outlined,
      color: Color(0xFF2563EB),
    );
  }
  if (_containsAny(value, [
    "架构",
    "runtime",
    "langchain",
    "agent",
    "multi-agent",
    "工具调用",
    "事件",
    "审计",
    "jsonl"
  ])) {
    return const _CareerItemVisual(
      label: "架构能力",
      icon: Icons.account_tree_rounded,
      color: Color(0xFF7C3AED),
    );
  }
  if (_containsAny(value, ["性能", "延迟", "失败率", "吞吐", "压测", "压力", "优化", "效率"])) {
    return const _CareerItemVisual(
      label: "性能优化",
      icon: Icons.speed_rounded,
      color: Color(0xFFB45309),
    );
  }
  if (_containsAny(value, ["项目", "成果", "量化", "指标", "贡献", "落地", "实践"])) {
    return const _CareerItemVisual(
      label: "项目成果",
      icon: Icons.insights_rounded,
      color: Color(0xFF0E7490),
    );
  }
  if (_containsAny(value, ["模型", "机器学习", "训练", "mlops", "算法", "llm"])) {
    return const _CareerItemVisual(
      label: "模型经验",
      icon: Icons.psychology_alt_outlined,
      color: Color(0xFFB45309),
    );
  }
  if (_containsAny(value, ["简历", "表达", "描述", "措辞", "补充", "改写"])) {
    return const _CareerItemVisual(
      label: "表达优化",
      icon: Icons.edit_note_rounded,
      color: Color(0xFF2563EB),
    );
  }
  if (_containsAny(value, ["岗位", "jd", "匹配", "筛选", "投递"])) {
    return const _CareerItemVisual(
      label: "岗位匹配",
      icon: Icons.work_outline_rounded,
      color: Color(0xFF0F766E),
    );
  }
  return _CareerItemVisual(
    label: "",
    icon: fallbackIcon,
    color: fallbackColor,
  );
}

bool _containsAny(String value, List<String> keywords) {
  return keywords.any((keyword) => value.contains(keyword.toLowerCase()));
}

void _copyInlineMarkdownLink(BuildContext context, String url) {
  Clipboard.setData(ClipboardData(text: url));
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(url.isEmpty ? "链接为空" : "链接已复制"),
      duration: const Duration(seconds: 1),
    ),
  );
}

bool _looksLikeCareerReport(String content) {
  if (content.isEmpty) {
    return false;
  }
  final hits =
      _careerSectionTitles.where((title) => content.contains(title)).length;
  return hits >= 2 &&
      (content.contains("简历") ||
          content.contains("诊断") ||
          content.contains("JD") ||
          content.contains("匹配"));
}

String? _careerSectionHeading(String line) {
  var text = line.trim();
  if (text.isEmpty) {
    return null;
  }
  text = text
      .replaceFirst(RegExp(r'^#{1,6}\s*'), '')
      .replaceFirst(RegExp(r'^\d+[\.、]\s*'), '')
      .replaceAll(RegExp(r'[:：]\s*$'), '')
      .trim();
  for (final title in _careerSectionTitles) {
    if (text == title || text.startsWith("$title ")) {
      return title;
    }
  }
  return null;
}

const _careerSectionTitles = [
  "诊断摘要",
  "核心优势",
  "风险点",
  "关键改进建议",
  "改进建议",
  "匹配摘要",
  "主要差距",
  "简历优化方向",
  "面试准备重点",
];

IconData _careerSectionIcon(String title) {
  if (title.contains("优势")) return Icons.trending_up_rounded;
  if (title.contains("风险") || title.contains("差距")) {
    return Icons.warning_amber_rounded;
  }
  if (title.contains("建议") || title.contains("优化")) {
    return Icons.auto_fix_high_rounded;
  }
  if (title.contains("面试")) return Icons.record_voice_over_outlined;
  return Icons.summarize_outlined;
}

Color _careerSectionColor(String title) {
  if (title.contains("优势")) return AppTheme.accent;
  if (title.contains("风险") || title.contains("差距")) {
    return const Color(0xFFB45309);
  }
  if (title.contains("建议") || title.contains("优化")) {
    return const Color(0xFF2563EB);
  }
  if (title.contains("面试")) return const Color(0xFF7C3AED);
  return AppTheme.textSecondary;
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
