import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/career_assets_provider.dart';
import '../../core/providers/chat_provider.dart';
import '../theme/app_theme.dart';
import '../utils/download_stub.dart'
    if (dart.library.html) '../utils/download_web.dart';
import 'career_report.dart';
import 'markdown_body.dart';
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
    final steps = _ThinkingStep.fromLines(widget.lines);
    final visibleSteps =
        steps.length > 5 ? steps.sublist(steps.length - 5) : steps;
    final runningCount = steps.where((step) => step.kind == "running").length;
    final failedCount = steps.where((step) => step.kind == "failed").length;
    final completedCount =
        steps.where((step) => step.kind == "completed").length;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.58 : 0.9),
            AppTheme.surfaceHover
                .withValues(alpha: AppTheme.isDark ? 0.16 : 0.34),
          ],
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.68)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.18 : 0.06),
            blurRadius: 18,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
              child: Row(
                children: [
                  Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(
                      color: AppTheme.accent.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(
                        color: AppTheme.accent.withValues(alpha: 0.16),
                      ),
                    ),
                    child: Icon(
                      _expanded
                          ? Icons.expand_more_rounded
                          : Icons.chevron_right_rounded,
                      size: 17,
                      color: AppTheme.accent,
                    ),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          "执行动态",
                          style: AppTheme.ts(
                            fontSize: 12.2,
                            height: 1.15,
                            fontWeight: FontWeight.w800,
                            color: AppTheme.textSecondary,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Text(
                          "正在整理上下文、工具结果和最终回答",
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 10.5,
                            color: AppTheme.textTertiary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 10),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                    decoration: BoxDecoration(
                      color: AppTheme.surfaceActive.withValues(alpha: 0.9),
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: AppTheme.border),
                    ),
                    child: Text(
                      "${steps.length} 条",
                      style: AppTheme.ts(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.textTertiary,
                      ),
                    ),
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
                children: [
                  Wrap(
                    spacing: 7,
                    runSpacing: 7,
                    children: [
                      _ThinkingSummaryChip(
                        icon: Icons.check_circle_outline_rounded,
                        label: "$completedCount 已完成",
                        color: AppTheme.accentHover,
                      ),
                      if (runningCount > 0)
                        const _ThinkingSummaryChip(
                          icon: Icons.sync_rounded,
                          label: "处理中",
                          color: Color(0xFF2563EB),
                        ),
                      if (failedCount > 0)
                        _ThinkingSummaryChip(
                          icon: Icons.error_outline_rounded,
                          label: "$failedCount 失败",
                          color: AppTheme.danger,
                        ),
                    ],
                  ),
                  const SizedBox(height: 9),
                  for (var index = 0; index < visibleSteps.length; index++)
                    Padding(
                      padding: EdgeInsets.only(
                        bottom: index == visibleSteps.length - 1 ? 0 : 8,
                      ),
                      child: _ThinkingStepCard(step: visibleSteps[index]),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _ThinkingStepCard extends StatelessWidget {
  final _ThinkingStep step;

  const _ThinkingStepCard({required this.step});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 9),
      decoration: BoxDecoration(
        color:
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.48 : 0.82),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: step.color.withValues(alpha: 0.14)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              color: step.color.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: step.color.withValues(alpha: 0.15)),
            ),
            child: Icon(step.icon, size: 14, color: step.color),
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
                        step.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.7,
                          height: 1.2,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    const SizedBox(width: 7),
                    _ThinkingStatusPill(step: step),
                  ],
                ),
                if (step.detail.isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Text(
                    step.detail,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 10.8,
                      height: 1.38,
                      fontWeight: FontWeight.w600,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
                const SizedBox(height: 8),
                Row(
                  children: [
                    Icon(
                      Icons.schedule_rounded,
                      size: 11.5,
                      color: AppTheme.textTertiary,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      step.timeLabel,
                      style: AppTheme.ts(
                        fontSize: 10,
                        height: 1.1,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
                if (step.kind == "running") ...[
                  const SizedBox(height: 8),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      minHeight: 3,
                      color: step.color,
                      backgroundColor: step.color.withValues(alpha: 0.1),
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

class _ThinkingStatusPill extends StatelessWidget {
  final _ThinkingStep step;

  const _ThinkingStatusPill({required this.step});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: step.color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: step.color.withValues(alpha: 0.14)),
      ),
      child: Text(
        step.statusLabel,
        style: AppTheme.ts(
          fontSize: 10,
          height: 1.1,
          fontWeight: FontWeight.w800,
          color: step.color,
        ),
      ),
    );
  }
}

class _ThinkingSummaryChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;

  const _ThinkingSummaryChip({
    required this.icon,
    required this.label,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.13)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 12, color: color),
          const SizedBox(width: 5),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 10.5,
              height: 1.1,
              fontWeight: FontWeight.w800,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _ThinkingStep {
  final String kind;
  final String title;
  final String detail;
  final String statusLabel;
  final String timeLabel;
  final IconData icon;
  final Color color;

  const _ThinkingStep({
    required this.kind,
    required this.title,
    required this.detail,
    required this.statusLabel,
    required this.timeLabel,
    required this.icon,
    required this.color,
  });

  static List<_ThinkingStep> fromLines(List<String> lines) {
    return lines.map(_ThinkingStep.fromLine).toList();
  }

  factory _ThinkingStep.fromLine(String line) {
    final parsed = _parseThinkingLine(line);
    final body = parsed.body;
    if (body.startsWith("开始执行")) {
      return _ThinkingStep(
        kind: "completed",
        title: "开始执行任务",
        detail: "已创建运行上下文",
        statusLabel: "已开始",
        timeLabel: parsed.timeLabel,
        icon: Icons.play_arrow_rounded,
        color: AppTheme.accentHover,
      );
    }
    if (body.startsWith("模型思考:") || body.startsWith("模型思考：")) {
      return _ThinkingStep(
        kind: "running",
        title: "模型正在规划",
        detail: _truncateText(
          body.replaceFirst(RegExp(r"模型思考[:：]\s*"), ""),
          110,
        ),
        statusLabel: "规划中",
        timeLabel: parsed.timeLabel,
        icon: Icons.psychology_alt_outlined,
        color: const Color(0xFF7C3AED),
      );
    }
    if (body.startsWith("调用工具 ")) {
      final name = body.replaceFirst("调用工具 ", "").trim();
      return _ThinkingStep(
        kind: "running",
        title: _thinkingToolActionName(name),
        detail: _thinkingToolDetail(name, completed: false),
        statusLabel: "运行中",
        timeLabel: parsed.timeLabel,
        icon: Icons.build_circle_outlined,
        color: const Color(0xFF2563EB),
      );
    }
    if (body.startsWith("工具成功 ")) {
      final name = body.replaceFirst("工具成功 ", "").trim();
      return _ThinkingStep(
        kind: "completed",
        title: _thinkingToolActionName(name),
        detail: _thinkingToolDetail(name, completed: true),
        statusLabel: "已完成",
        timeLabel: parsed.timeLabel,
        icon: Icons.check_circle_outline_rounded,
        color: AppTheme.accentHover,
      );
    }
    if (body.startsWith("工具失败 ")) {
      final name = body.replaceFirst("工具失败 ", "").trim();
      return _ThinkingStep(
        kind: "failed",
        title: _thinkingToolActionName(name),
        detail: "工具返回失败，系统会保留已完成结果",
        statusLabel: "失败",
        timeLabel: parsed.timeLabel,
        icon: Icons.error_outline_rounded,
        color: AppTheme.danger,
      );
    }
    if (body.startsWith("执行完成")) {
      return _ThinkingStep(
        kind: "completed",
        title: "执行完成",
        detail: "正在整理最终回答",
        statusLabel: "完成",
        timeLabel: parsed.timeLabel,
        icon: Icons.flag_outlined,
        color: AppTheme.accentHover,
      );
    }
    return _ThinkingStep(
      kind: "running",
      title: "处理中",
      detail: _truncateText(body, 110),
      statusLabel: "进行中",
      timeLabel: parsed.timeLabel,
      icon: Icons.sync_rounded,
      color: const Color(0xFF2563EB),
    );
  }
}

class _ParsedThinkingLine {
  final String timeLabel;
  final String body;

  const _ParsedThinkingLine({required this.timeLabel, required this.body});
}

_ParsedThinkingLine _parseThinkingLine(String line) {
  final match = RegExp(r"^\[(\d{2}:\d{2}:\d{2})\]\s*(.*)$").firstMatch(line);
  if (match == null) {
    return _ParsedThinkingLine(timeLabel: "--:--:--", body: line.trim());
  }
  return _ParsedThinkingLine(
    timeLabel: match.group(1) ?? "--:--:--",
    body: (match.group(2) ?? "").trim(),
  );
}

String _truncateText(String value, int maxLength) {
  final normalized = value.trim().replaceAll(RegExp(r"\s+"), " ");
  if (normalized.length <= maxLength) {
    return normalized;
  }
  if (maxLength <= 1) {
    return normalized.substring(0, maxLength);
  }
  return "${normalized.substring(0, maxLength - 1)}…";
}

String _thinkingToolActionName(String name) {
  return switch (name.trim()) {
    "delegate_agents" => "委派协作 Agent",
    "agent_task_status" => "检查协作任务状态",
    "session_list_artifacts" => "查看会话文件",
    "session_plan_artifact_access" => "规划文件读取",
    "session_read_artifact" => "读取文件内容",
    "session_search_artifact" => "搜索文件内容",
    "session_create_text_artifact" => "创建文本资料",
    "publish_artifact" => "发布用户可见文件",
    "career_resume_profile_save" => "保存简历画像",
    "career_profile_merge" => "更新职业画像",
    "career_jd_analysis_save" => "保存 JD 分析",
    "career_job_fit_report_save" => "保存岗位匹配报告",
    "career_resume_version_create" => "生成简历版本",
    "memory_search" => "检索记忆",
    "memory_write" => "写入记忆",
    _ => _fallbackThinkingToolActionName(name),
  };
}

String _thinkingToolDetail(String name, {required bool completed}) {
  final action = completed ? "已返回结果" : "正在执行";
  return switch (name.trim()) {
    "delegate_agents" => completed ? "协作 Agent 已接收任务" : "正在分配子任务",
    "agent_task_status" => completed ? "已同步协作进度" : "正在读取协作进度",
    "session_read_artifact" => completed ? "文件内容已读取" : "正在读取用户资料",
    "session_search_artifact" => completed ? "已找到相关片段" : "正在检索资料内容",
    "career_resume_profile_save" => completed ? "简历画像已保存" : "正在沉淀简历画像",
    "career_profile_merge" => completed ? "职业画像已更新" : "正在合并职业画像",
    "career_jd_analysis_save" => completed ? "JD 分析已保存" : "正在保存 JD 分析",
    "career_job_fit_report_save" => completed ? "匹配报告已保存" : "正在保存匹配报告",
    _ => "$action 系统能力",
  };
}

String _fallbackThinkingToolActionName(String name) {
  final normalized = name.trim();
  if (normalized.isEmpty || normalized == "unknown") {
    return "执行系统工具";
  }
  final parts = normalized
      .split(RegExp(r"[_\-.]+"))
      .where((part) => part.trim().isNotEmpty)
      .toList();
  if (parts.isEmpty) {
    return "执行系统工具";
  }
  final last = parts.last;
  final readable = last.length <= 12 ? last : "${last.substring(0, 12)}…";
  return "执行 $readable 操作";
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
    if (CareerReportView.canRender(resolved.content)) {
      return CareerReportView(content: resolved.content);
    }
    switch (resolved.mode) {
      case _MessageRenderMode.markdownRendered:
        return AssistantMarkdownBody(content: resolved.content);
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
            ? CodeBlockCard(
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
            ? CodeBlockCard(
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
              CodeCopyButton(text: content, label: '复制全文'),
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
        CodeBlockCard(
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
    return CodeBlockCard(
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
    return AppMarkdownBody(
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
    final chat = ref.watch(chatProvider);
    final nextAction = _careerAssetRecommendedAction(assets);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 11),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppTheme.surfaceActive
                .withValues(alpha: AppTheme.isDark ? 0.48 : 0.78),
            AppTheme.surfaceHover
                .withValues(alpha: AppTheme.isDark ? 0.12 : 0.28),
          ],
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.72)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: AppTheme.accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(11),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.18),
                  ),
                ),
                child: Icon(
                  Icons.inventory_2_outlined,
                  size: 15,
                  color: AppTheme.accent,
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "已创建的求职资产",
                      style: AppTheme.ts(
                        fontSize: 12.6,
                        height: 1.15,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      "结果已整理为可预览、可继续处理的资产",
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.8,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              _CareerAssetCountBadge(count: assets.length),
            ],
          ),
          if (nextAction != null) ...[
            const SizedBox(height: 10),
            _CareerAssetNextStepCard(
              action: nextAction,
              enabled: !chat.isStreaming,
              onPressed: () async {
                await ref.read(chatProvider).sendMessage(nextAction.prompt);
              },
            ),
          ],
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

class _CareerAssetCountBadge extends StatelessWidget {
  final int count;

  const _CareerAssetCountBadge({required this.count});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.09),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.13)),
      ),
      child: Text(
        "$count 项",
        style: AppTheme.ts(
          fontSize: 10.5,
          height: 1.1,
          fontWeight: FontWeight.w800,
          color: AppTheme.accent,
        ),
      ),
    );
  }
}

class _CareerAssetNextStepCard extends StatelessWidget {
  final _CareerAssetRecommendedAction action;
  final bool enabled;
  final Future<void> Function() onPressed;

  const _CareerAssetNextStepCard({
    required this.action,
    required this.enabled,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
      decoration: BoxDecoration(
        color: action.color.withValues(alpha: AppTheme.isDark ? 0.08 : 0.06),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: action.color.withValues(alpha: 0.15)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: action.color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border:
                      Border.all(color: action.color.withValues(alpha: 0.16)),
                ),
                child: Icon(action.icon, size: 15, color: action.color),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      action.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 11.8,
                        height: 1.2,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      action.description,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.8,
                        height: 1.38,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          Align(
            alignment: Alignment.centerRight,
            child: _CareerAssetRunActionButton(
              label: action.buttonLabel,
              icon: action.buttonIcon,
              enabled: enabled,
              onPressed: onPressed,
            ),
          ),
        ],
      ),
    );
  }
}

class _CareerAssetRunActionButton extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool enabled;
  final Future<void> Function() onPressed;

  const _CareerAssetRunActionButton({
    required this.label,
    required this.icon,
    required this.enabled,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: enabled ? () => unawaited(onPressed()) : null,
      style: TextButton.styleFrom(
        foregroundColor: enabled ? AppTheme.accent : AppTheme.textTertiary,
        backgroundColor: enabled
            ? AppTheme.accent.withValues(alpha: 0.12)
            : AppTheme.textTertiary.withValues(alpha: 0.06),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        side: BorderSide(
          color: (enabled ? AppTheme.accent : AppTheme.textTertiary)
              .withValues(alpha: 0.18),
        ),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        textStyle: AppTheme.ts(
          fontSize: 11.5,
          fontWeight: FontWeight.w800,
        ),
      ),
      icon: Icon(icon, size: 14),
      label: Text(label),
    );
  }
}

class _CareerAssetReferenceCard extends ConsumerWidget {
  final _DetectedCareerAsset asset;

  const _CareerAssetReferenceCard({required this.asset});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final chat = ref.watch(chatProvider);
    final careerAssets = ref.watch(careerAssetsProvider);
    final sessionArtifact = asset.kind == _CareerAssetKind.artifact
        ? _findSessionArtifact(chat.sessionArtifacts, asset.id)
        : null;
    final careerRecord = asset.kind == _CareerAssetKind.artifact
        ? null
        : _findCareerRecord(careerAssets, asset);
    final title = _careerAssetReferenceTitle(
      asset,
      sessionArtifact: sessionArtifact,
      careerRecord: careerRecord,
    );
    final subtitle = _careerAssetReferenceSubtitle(
      asset,
      sessionArtifact: sessionArtifact,
      careerRecord: careerRecord,
    );

    return Container(
      width: 252,
      padding: const EdgeInsets.fromLTRB(11, 11, 11, 10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.78),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.borderLight.withValues(alpha: 0.78)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.08 : 0.025),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
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
          Text(
            subtitle,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
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
                label: "复制",
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

String _careerAssetReferenceTitle(
  _DetectedCareerAsset asset, {
  required SessionArtifactView? sessionArtifact,
  required Object? careerRecord,
}) {
  if (sessionArtifact != null) {
    return sessionArtifact.title;
  }
  if (careerRecord is ResumeProfileView) {
    return careerRecord.displayName;
  }
  if (careerRecord is CareerProfileView) {
    return careerRecord.careerGoal.trim().isEmpty
        ? "职业画像"
        : careerRecord.careerGoal.trim();
  }
  if (careerRecord is JDAnalysisView) {
    return careerRecord.displayTitle;
  }
  if (careerRecord is JobFitReportView) {
    return careerRecord.recommendation.trim().isEmpty
        ? "岗位匹配报告"
        : "匹配报告 · ${careerRecord.recommendation.trim()}";
  }
  if (careerRecord is ResumeVersionView) {
    return careerRecord.title.trim().isEmpty ? "简历版本" : careerRecord.title;
  }
  if (asset.kind == _CareerAssetKind.artifact) {
    return _shortAssetId(asset.id);
  }
  return asset.label;
}

String _careerAssetReferenceSubtitle(
  _DetectedCareerAsset asset, {
  required SessionArtifactView? sessionArtifact,
  required Object? careerRecord,
}) {
  if (sessionArtifact != null) {
    return "${sessionArtifact.sizeDisplay} · ${_artifactStatusLabel(sessionArtifact.status)}";
  }
  if (careerRecord is ResumeProfileView) {
    return "${careerRecord.skills.length} 技能 · ${careerRecord.projectExperience.length} 项目 · ${careerRecord.workExperience.length} 经历";
  }
  if (careerRecord is CareerProfileView) {
    final roles = careerRecord.targetRoles.take(2).join(" / ");
    return roles.isEmpty ? "产品记录 · 可在右侧面板查看" : roles;
  }
  if (careerRecord is JDAnalysisView) {
    final keywords = careerRecord.keywords.take(3).join(" / ");
    return keywords.isEmpty ? "JD 分析 · 可在右侧面板查看" : keywords;
  }
  if (careerRecord is JobFitReportView) {
    return "整体匹配 ${careerRecord.overallScore}/100";
  }
  if (careerRecord is ResumeVersionView) {
    return careerRecord.format.trim().isEmpty
        ? "简历版本 · 可预览下载"
        : "${careerRecord.format} · 可预览下载";
  }
  if (asset.kind == _CareerAssetKind.artifact) {
    return "文件资产 · 点击预览或下载";
  }
  return "产品记录 · 可在右侧求职资产面板查看";
}

String _shortAssetId(String value) {
  if (value.length <= 18) {
    return value;
  }
  return "${value.substring(0, 10)}...${value.substring(value.length - 4)}";
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
    builder: (sheetContext) => _SessionArtifactPreviewSheet(
      preview: preview,
      onDownload: () => _downloadSessionArtifact(sheetContext, ref, artifactId),
      onCopyContent: () => _copyText(sheetContext, preview.content, "预览内容已复制"),
      onCopyId: () => _copyText(sheetContext, preview.artifactId, "文件编号已复制"),
    ),
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
  final Future<void> Function() onDownload;
  final Future<void> Function() onCopyContent;
  final Future<void> Function() onCopyId;

  const _SessionArtifactPreviewSheet({
    required this.preview,
    required this.onDownload,
    required this.onCopyContent,
    required this.onCopyId,
  });

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final contentHeight = size.height * 0.88;
    final isCareerReport = CareerReportView.canRender(preview.content);
    final maxReaderWidth = isCareerReport ? 900.0 : 780.0;
    return SafeArea(
      top: false,
      child: Align(
        alignment: Alignment.bottomCenter,
        child: Container(
          margin: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          constraints: BoxConstraints(
            maxWidth: 980,
            maxHeight: contentHeight,
          ),
          decoration: AppTheme.floatingPanelDecoration(
            radius: 26,
            alpha: 0.96,
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _SessionPreviewHeader(
                preview: preview,
                isCareerReport: isCareerReport,
                onDownload: onDownload,
                onCopyContent: onCopyContent,
                onCopyId: onCopyId,
              ),
              Expanded(
                child: _SessionPreviewReaderStage(
                  preview: preview,
                  isCareerReport: isCareerReport,
                  maxReaderWidth: maxReaderWidth,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _SessionPreviewReaderStage extends StatelessWidget {
  final SessionArtifactContentView preview;
  final bool isCareerReport;
  final double maxReaderWidth;

  const _SessionPreviewReaderStage({
    required this.preview,
    required this.isCareerReport,
    required this.maxReaderWidth,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 760;
        final horizontalPadding = wide ? 28.0 : 14.0;
        return Stack(
          children: [
            Positioned.fill(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      AppTheme.bg
                          .withValues(alpha: AppTheme.isDark ? 0.2 : 0.48),
                      AppTheme.surfaceHover
                          .withValues(alpha: AppTheme.isDark ? 0.08 : 0.3),
                    ],
                  ),
                ),
              ),
            ),
            Scrollbar(
              child: SingleChildScrollView(
                padding: EdgeInsets.fromLTRB(
                  horizontalPadding,
                  wide ? 24 : 16,
                  horizontalPadding,
                  wide ? 42 : 28,
                ),
                child: Center(
                  child: ConstrainedBox(
                    constraints: BoxConstraints(maxWidth: maxReaderWidth),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (preview.truncated) ...[
                          const _SessionPreviewNotice(),
                          const SizedBox(height: 12),
                        ],
                        _SessionReaderSurface(
                          isCareerReport: isCareerReport,
                          child: isCareerReport
                              ? CareerReportView(
                                  content: preview.content,
                                  readerMode: true,
                                )
                              : _MessageBody(
                                  content: preview.content,
                                  isUser: false,
                                  isStreaming: false,
                                  answerFormat:
                                      _artifactAnswerFormat(preview.mediaType),
                                  renderHint:
                                      _artifactRenderHint(preview.mediaType),
                                  layoutHint: 'paragraph',
                                ),
                        ),
                        const SizedBox(height: 10),
                        _SessionReaderFootnote(
                          artifactId: preview.artifactId,
                          characterLabel:
                              "${preview.returnedChars}/${preview.totalChars} 字符",
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
            const _SessionPreviewEdgeFade(alignment: Alignment.topCenter),
            const _SessionPreviewEdgeFade(alignment: Alignment.bottomCenter),
          ],
        );
      },
    );
  }
}

class _SessionReaderSurface extends StatelessWidget {
  final bool isCareerReport;
  final Widget child;

  const _SessionReaderSurface({
    required this.isCareerReport,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final padding = EdgeInsets.fromLTRB(
      isCareerReport ? 14 : 18,
      isCareerReport ? 14 : 18,
      isCareerReport ? 14 : 18,
      isCareerReport ? 16 : 20,
    );
    return Container(
      width: double.infinity,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.68 : 0.9),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppTheme.borderLight.withValues(alpha: 0.64)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.14 : 0.055),
            blurRadius: 26,
            offset: const Offset(0, 16),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: isCareerReport ? 4 : 3,
            decoration: BoxDecoration(
              gradient: LinearGradient(
                colors: [
                  AppTheme.accent.withValues(alpha: 0.72),
                  const Color(0xFF2563EB)
                      .withValues(alpha: AppTheme.isDark ? 0.44 : 0.34),
                  AppTheme.accent.withValues(alpha: 0.12),
                ],
              ),
            ),
          ),
          Padding(
            padding: padding,
            child: child,
          ),
        ],
      ),
    );
  }
}

class _SessionReaderFootnote extends StatelessWidget {
  final String artifactId;
  final String characterLabel;

  const _SessionReaderFootnote({
    required this.artifactId,
    required this.characterLabel,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.center,
      child: Wrap(
        spacing: 8,
        runSpacing: 6,
        alignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _PreviewMetaChip(
            icon: Icons.short_text_rounded,
            label: characterLabel,
          ),
          _PreviewMetaChip(
            icon: Icons.fingerprint_rounded,
            label: "文件 ${_shortAssetId(artifactId)}",
          ),
        ],
      ),
    );
  }
}

class _SessionPreviewEdgeFade extends StatelessWidget {
  final Alignment alignment;

  const _SessionPreviewEdgeFade({required this.alignment});

  @override
  Widget build(BuildContext context) {
    final isTop = alignment == Alignment.topCenter;
    return IgnorePointer(
      child: Align(
        alignment: alignment,
        child: Container(
          height: isTop ? 18 : 34,
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: isTop ? Alignment.topCenter : Alignment.bottomCenter,
              end: isTop ? Alignment.bottomCenter : Alignment.topCenter,
              colors: [
                AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.46 : 0.66),
                AppTheme.bg.withValues(alpha: 0),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SessionPreviewHeader extends StatelessWidget {
  final SessionArtifactContentView preview;
  final bool isCareerReport;
  final Future<void> Function() onDownload;
  final Future<void> Function() onCopyContent;
  final Future<void> Function() onCopyId;

  const _SessionPreviewHeader({
    required this.preview,
    required this.isCareerReport,
    required this.onDownload,
    required this.onCopyContent,
    required this.onCopyId,
  });

  @override
  Widget build(BuildContext context) {
    final title = preview.title.trim().isEmpty ? "文件预览" : preview.title;
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 15, 14, 14),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: 0.96),
        border: Border(
          bottom: BorderSide(color: AppTheme.border.withValues(alpha: 0.64)),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: AppTheme.isDark ? 0.1 : 0.03),
            blurRadius: 14,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 700;
          final titleBlock = _SessionPreviewTitleBlock(
            title: title,
            isCareerReport: isCareerReport,
            preview: preview,
          );
          final actions = _SessionPreviewActionCluster(
            onDownload: onDownload,
            onCopyContent: onCopyContent,
            onCopyId: onCopyId,
            onClose: () => Navigator.of(context).pop(),
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _SessionPreviewIcon(isCareerReport: isCareerReport),
                    const SizedBox(width: 12),
                    Expanded(child: titleBlock),
                  ],
                ),
                const SizedBox(height: 12),
                Align(
                  alignment: Alignment.centerRight,
                  child: actions,
                ),
              ],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _SessionPreviewIcon(isCareerReport: isCareerReport),
              const SizedBox(width: 12),
              Expanded(child: titleBlock),
              const SizedBox(width: 14),
              actions,
            ],
          );
        },
      ),
    );
  }
}

class _SessionPreviewIcon extends StatelessWidget {
  final bool isCareerReport;

  const _SessionPreviewIcon({required this.isCareerReport});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.11),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.2)),
      ),
      child: Icon(
        isCareerReport ? Icons.fact_check_outlined : Icons.article_outlined,
        size: 19,
        color: AppTheme.accent,
      ),
    );
  }
}

class _SessionPreviewTitleBlock extends StatelessWidget {
  final String title;
  final bool isCareerReport;
  final SessionArtifactContentView preview;

  const _SessionPreviewTitleBlock({
    required this.title,
    required this.isCareerReport,
    required this.preview,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          isCareerReport ? "报告阅读器" : "文档预览",
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppTheme.ts(
            fontSize: 10.5,
            height: 1.1,
            fontWeight: FontWeight.w800,
            color: AppTheme.accent,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          title,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: AppTheme.ts(
            fontSize: 15.5,
            height: 1.22,
            fontWeight: FontWeight.w800,
            color: AppTheme.textPrimary,
          ),
        ),
        const SizedBox(height: 9),
        Wrap(
          spacing: 7,
          runSpacing: 7,
          children: [
            _PreviewMetaChip(
              icon: isCareerReport
                  ? Icons.dashboard_customize_outlined
                  : Icons.notes_rounded,
              label: isCareerReport ? "报告阅读" : "Markdown 预览",
            ),
            _PreviewMetaChip(
              icon: Icons.short_text_rounded,
              label: "${preview.returnedChars}/${preview.totalChars} 字符",
            ),
            _PreviewMetaChip(
              icon: Icons.fingerprint_rounded,
              label: "文件 ${_shortAssetId(preview.artifactId)}",
            ),
          ],
        ),
      ],
    );
  }
}

class _SessionPreviewActionCluster extends StatelessWidget {
  final Future<void> Function() onDownload;
  final Future<void> Function() onCopyContent;
  final Future<void> Function() onCopyId;
  final VoidCallback onClose;

  const _SessionPreviewActionCluster({
    required this.onDownload,
    required this.onCopyContent,
    required this.onCopyId,
    required this.onClose,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.34 : 0.58),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.7)),
      ),
      child: Wrap(
        spacing: 4,
        runSpacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _SessionPreviewPrimaryButton(
            icon: Icons.download_rounded,
            label: "下载",
            onTap: onDownload,
          ),
          _SessionPreviewIconButton(
            icon: Icons.content_copy_rounded,
            tooltip: "复制内容",
            onTap: onCopyContent,
          ),
          _SessionPreviewIconButton(
            icon: Icons.tag_rounded,
            tooltip: "复制文件编号",
            onTap: onCopyId,
          ),
          _SessionPreviewIconButton(
            icon: Icons.close_rounded,
            tooltip: "关闭",
            onTap: () async => onClose(),
          ),
        ],
      ),
    );
  }
}

class _SessionPreviewPrimaryButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final Future<void> Function() onTap;

  const _SessionPreviewPrimaryButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return TextButton.icon(
      onPressed: () => unawaited(onTap()),
      style: TextButton.styleFrom(
        foregroundColor: AppTheme.accent,
        backgroundColor: AppTheme.accent.withValues(alpha: 0.13),
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 8),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        side: BorderSide(color: AppTheme.accent.withValues(alpha: 0.23)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        textStyle: AppTheme.ts(
          fontSize: 11.5,
          height: 1,
          fontWeight: FontWeight.w800,
        ),
      ),
      icon: Icon(icon, size: 15),
      label: Text(label),
    );
  }
}

class _SessionPreviewIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final Future<void> Function() onTap;

  const _SessionPreviewIconButton({
    required this.icon,
    required this.tooltip,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => unawaited(onTap()),
          child: Container(
            width: 34,
            height: 34,
            decoration: BoxDecoration(
              color: AppTheme.surface.withValues(alpha: 0.82),
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppTheme.border),
            ),
            child: Icon(icon, size: 16, color: AppTheme.textSecondary),
          ),
        ),
      ),
    );
  }
}

class _SessionPreviewNotice extends StatelessWidget {
  const _SessionPreviewNotice();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: const Color(0xFFB45309)
            .withValues(alpha: AppTheme.isDark ? 0.11 : 0.08),
        borderRadius: BorderRadius.circular(14),
        border:
            Border.all(color: const Color(0xFFB45309).withValues(alpha: 0.18)),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.content_cut_rounded,
            size: 15,
            color: Color(0xFFB45309),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              "当前为预览片段，下载原文件可查看完整内容。",
              style: AppTheme.ts(
                fontSize: 11.2,
                height: 1.35,
                fontWeight: FontWeight.w700,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
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

class _CareerAssetRecommendedAction {
  final String title;
  final String description;
  final String buttonLabel;
  final String prompt;
  final IconData icon;
  final IconData buttonIcon;
  final Color color;

  const _CareerAssetRecommendedAction({
    required this.title,
    required this.description,
    required this.buttonLabel,
    required this.prompt,
    required this.icon,
    required this.buttonIcon,
    required this.color,
  });
}

_CareerAssetRecommendedAction? _careerAssetRecommendedAction(
  List<_DetectedCareerAsset> assets,
) {
  final fitReport = _firstAssetOfKind(assets, _CareerAssetKind.jobFitReport);
  if (fitReport != null) {
    return _CareerAssetRecommendedAction(
      title: "建议下一步：生成定制简历",
      description: "基于匹配报告把优势、项目和关键词转成可投递版本。",
      buttonLabel: "生成定制简历",
      prompt:
          "请基于匹配报告 ${fitReport.id} 生成一版面向目标岗位的中文 Markdown 定制简历。要求：只使用已有简历事实，不编造经历；突出与 JD 匹配的项目、技能和量化结果；最后列出改动摘要。",
      icon: Icons.edit_note_rounded,
      buttonIcon: Icons.auto_awesome_rounded,
      color: const Color(0xFFB45309),
    );
  }

  final resumeProfile =
      _firstAssetOfKind(assets, _CareerAssetKind.resumeProfile);
  final jdAnalysis = _firstAssetOfKind(assets, _CareerAssetKind.jdAnalysis);
  if (resumeProfile != null && jdAnalysis != null) {
    return _CareerAssetRecommendedAction(
      title: "建议下一步：生成匹配报告",
      description: "把简历画像和 JD 分析合并，产出岗位匹配结论和风险建议。",
      buttonLabel: "生成匹配报告",
      prompt:
          "请基于简历画像 ${resumeProfile.id} 和 JD 分析 ${jdAnalysis.id} 生成岗位匹配报告，并沉淀为可复用求职资产。",
      icon: Icons.fact_check_outlined,
      buttonIcon: Icons.play_arrow_rounded,
      color: AppTheme.accent,
    );
  }

  final resumeVersion =
      _firstAssetOfKind(assets, _CareerAssetKind.resumeVersion);
  if (resumeVersion != null) {
    return _CareerAssetRecommendedAction(
      title: "建议下一步：检查可投递性",
      description: "对已生成版本做投递前检查，确认关键词、风险和表达是否到位。",
      buttonLabel: "检查简历",
      prompt:
          "请基于简历版本 ${resumeVersion.id} 做一次投递前检查，重点看岗位关键词覆盖、项目表达、量化结果、风险点和可读性，并给出修改建议。",
      icon: Icons.rule_rounded,
      buttonIcon: Icons.search_rounded,
      color: const Color(0xFFDC2626),
    );
  }

  if (resumeProfile != null) {
    return _CareerAssetRecommendedAction(
      title: "建议下一步：匹配目标岗位",
      description: "继续提供 JD 后，可以基于这份画像生成岗位匹配报告。",
      buttonLabel: "准备匹配 JD",
      prompt:
          "我想基于简历画像 ${resumeProfile.id} 匹配一个目标岗位。请告诉我需要提供哪些 JD 信息，并在我提供后生成 JD 分析和匹配报告。",
      icon: Icons.route_outlined,
      buttonIcon: Icons.arrow_forward_rounded,
      color: const Color(0xFF0F9B78),
    );
  }

  if (jdAnalysis != null) {
    return _CareerAssetRecommendedAction(
      title: "建议下一步：补齐候选人证据",
      description: "先把 JD 需求转成简历证据清单，方便后续匹配画像。",
      buttonLabel: "生成证据清单",
      prompt: "请基于 JD 分析 ${jdAnalysis.id} 提炼一份候选人需要补齐的简历证据清单，按硬性要求、加分项、风险项分组。",
      icon: Icons.checklist_rounded,
      buttonIcon: Icons.play_arrow_rounded,
      color: const Color(0xFF7C3AED),
    );
  }

  return null;
}

_DetectedCareerAsset? _firstAssetOfKind(
  List<_DetectedCareerAsset> assets,
  _CareerAssetKind kind,
) {
  for (final asset in assets) {
    if (asset.kind == kind) {
      return asset;
    }
  }
  return null;
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
