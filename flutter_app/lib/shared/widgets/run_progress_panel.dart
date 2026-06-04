import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../theme/app_theme.dart';

const _agentTaskEventTypes = {
  "agent_task_group_created",
  "agent_task_started",
  "agent_task_progress",
  "agent_task_completed",
  "agent_task_failed",
  "agent_task_group_completed",
};

const _executionEventTypes = {
  "run_started",
  "assistant_thinking",
  "tool_call",
  "tool_result",
  "run_finished",
};

enum RunProgressPanelStyle { detailed, compact }

class RunProgressPanel extends StatefulWidget {
  final List<EventView> events;
  final RunProgressPanelStyle style;

  const RunProgressPanel({
    super.key,
    required this.events,
    this.style = RunProgressPanelStyle.detailed,
  });

  static bool hasProgress(List<EventView> events) {
    return events.any(
      (event) =>
          _agentTaskEventTypes.contains(event.type) ||
          _executionEventTypes.contains(event.type),
    );
  }

  @override
  State<RunProgressPanel> createState() => _RunProgressPanelState();
}

class _RunProgressPanelState extends State<RunProgressPanel> {
  bool? _expandedOverride;

  @override
  Widget build(BuildContext context) {
    final snapshot = _RunProgressSnapshot.fromEvents(widget.events);
    if (snapshot.tasks.isEmpty && snapshot.executionItems.isEmpty) {
      return const SizedBox.shrink();
    }
    if (widget.style == RunProgressPanelStyle.compact) {
      return _CompactRunProgressPanel(snapshot: snapshot);
    }

    final summaryParts = snapshot.tasks.isNotEmpty
        ? [
            "${snapshot.tasks.length} 个 agent",
            if (snapshot.runningCount > 0) "${snapshot.runningCount} 运行中",
            if (snapshot.waitingCount > 0) "${snapshot.waitingCount} 等待中",
            if (snapshot.completedCount > 0) "${snapshot.completedCount} 已完成",
            if (snapshot.failedCount > 0) "${snapshot.failedCount} 失败",
            if (snapshot.executionItems.isNotEmpty)
              "${snapshot.executionItems.length} 条操作",
          ]
        : [
            "${snapshot.executionItems.length} 条执行动态",
          ];
    final accent = _statusColor(snapshot.status);
    final expanded =
        _expandedOverride ?? !_shouldCollapseDetailsByDefault(snapshot);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.8 : 0.94),
            AppTheme.surfaceHover
                .withValues(alpha: AppTheme.isDark ? 0.34 : 0.48),
          ],
        ),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(
          color: accent.withValues(alpha: AppTheme.isDark ? 0.28 : 0.22),
        ),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.24 : 0.08),
            blurRadius: 24,
            offset: const Offset(0, 12),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(18),
            onTap: () => setState(() => _expandedOverride = !expanded),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 13, 12, 12),
              child: Row(
                children: [
                  _RunStatusIcon(status: snapshot.status),
                  const SizedBox(width: 11),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                _titleForStatus(snapshot.status),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: AppTheme.ts(
                                  fontSize: 13.5,
                                  fontWeight: FontWeight.w800,
                                  color: AppTheme.textPrimary,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            _ProgressMetricPill(
                              label:
                                  "${(snapshot.progressRatio * 100).round()}%",
                              color: accent,
                            ),
                          ],
                        ),
                        const SizedBox(height: 3),
                        Text(
                          summaryParts.join(" · "),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 11,
                            color: AppTheme.textTertiary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 10),
                  _StatusBadge(status: snapshot.status),
                  const SizedBox(width: 8),
                  Icon(
                    expanded
                        ? Icons.keyboard_arrow_up_rounded
                        : Icons.keyboard_arrow_down_rounded,
                    size: 20,
                    color: AppTheme.textTertiary,
                  ),
                ],
              ),
            ),
          ),
          Padding(
            padding: EdgeInsets.fromLTRB(14, 0, 14, expanded ? 12 : 13),
            child: Column(
              children: [
                if (snapshot.tasks.isNotEmpty) ...[
                  _ProgressTrack(snapshot: snapshot),
                  const SizedBox(height: 10),
                ],
                _RunStageRail(snapshot: snapshot),
                const SizedBox(height: 10),
                _RunFocusCard(snapshot: snapshot),
                if (_RunActivityDigestCard.hasContent(snapshot)) ...[
                  const SizedBox(height: 10),
                  _RunActivityDigestCard(snapshot: snapshot),
                ],
                if (snapshot.tasks.length > 1) ...[
                  const SizedBox(height: 10),
                  _AgentPipeline(tasks: snapshot.tasks),
                ],
              ],
            ),
          ),
          AnimatedSize(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOutCubic,
            alignment: Alignment.topCenter,
            child: expanded
                ? Padding(
                    padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                    child: Column(
                      children: [
                        for (final task in snapshot.tasks) ...[
                          _AgentTaskCard(task: task),
                          if (task != snapshot.tasks.last)
                            const SizedBox(height: 9),
                        ],
                        if (snapshot.executionItems.isNotEmpty) ...[
                          if (snapshot.tasks.isNotEmpty)
                            const SizedBox(height: 9),
                          _ExecutionTraceSection(
                            items: snapshot.executionItems,
                          ),
                        ],
                        const SizedBox(height: 11),
                        _RunProgressFooter(snapshot: snapshot),
                      ],
                    ),
                  )
                : const SizedBox.shrink(),
          ),
        ],
      ),
    );
  }
}

class _CompactRunProgressPanel extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _CompactRunProgressPanel({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final ratio = (snapshot.progressRatio * 100).round();
    final tasks = snapshot.tasks.take(4).toList();
    final steps = tasks.isEmpty
        ? const [
            _CompactStepData('接收请求', '创建运行上下文', 'completed'),
            _CompactStepData('执行工具', '读取资料或处理任务', 'running'),
            _CompactStepData('输出结果', '整理最终回答', 'queued'),
          ]
        : [
            for (final task in tasks)
              _CompactStepData(
                _agentDisplayName(task.targetAgentId),
                _compactTaskDetail(task),
                task.status,
              ),
          ];

    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppTheme.border),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 11),
            child: Row(
              children: [
                Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: AppTheme.accent.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(
                    Icons.hub_outlined,
                    size: 16,
                    color: AppTheme.accent,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'Agent 执行进度',
                    style: AppTheme.ts(
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.textPrimary,
                    ),
                  ),
                ),
                Container(
                  height: 24,
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  decoration: BoxDecoration(
                    color: AppTheme.accent.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(
                      color: AppTheme.accent.withValues(alpha: 0.16),
                    ),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    '$ratio%',
                    style: AppTheme.ts(
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                      color: AppTheme.accent,
                    ),
                  ),
                ),
              ],
            ),
          ),
          Divider(height: 1, color: AppTheme.border),
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
            child: _CompactStepper(steps: steps),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: _CompactResultSummary(snapshot: snapshot),
          ),
        ],
      ),
    );
  }
}

class _CompactStepData {
  final String title;
  final String detail;
  final String status;

  const _CompactStepData(this.title, this.detail, this.status);
}

class _CompactStepper extends StatelessWidget {
  final List<_CompactStepData> steps;

  const _CompactStepper({required this.steps});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 560;
        if (compact) {
          return Column(
            children: [
              for (final step in steps) ...[
                _CompactStepTile(step: step, horizontal: false),
                if (step != steps.last) const SizedBox(height: 10),
              ],
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var index = 0; index < steps.length; index++) ...[
              Expanded(
                child: _CompactStepTile(
                  step: steps[index],
                  horizontal: true,
                ),
              ),
              if (index != steps.length - 1)
                Padding(
                  padding: const EdgeInsets.only(top: 15),
                  child: Container(
                    width: 42,
                    height: 1,
                    color: AppTheme.borderLight,
                  ),
                ),
            ],
          ],
        );
      },
    );
  }
}

class _CompactStepTile extends StatelessWidget {
  final _CompactStepData step;
  final bool horizontal;

  const _CompactStepTile({
    required this.step,
    required this.horizontal,
  });

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(step.status);
    final done = _isTerminalTaskStatus(step.status);
    final running = step.status == 'running';
    final node = Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        color: done || running ? color : AppTheme.surface,
        shape: BoxShape.circle,
        border: Border.all(
          color: done || running ? color : AppTheme.borderLight,
        ),
        boxShadow: running
            ? [
                BoxShadow(
                  color: color.withValues(alpha: 0.16),
                  blurRadius: 14,
                  spreadRadius: 3,
                ),
              ]
            : null,
      ),
      alignment: Alignment.center,
      child: Icon(
        done
            ? Icons.check_rounded
            : running
                ? Icons.sync_rounded
                : Icons.circle,
        size: done || running ? 17 : 8,
        color: done || running ? Colors.white : AppTheme.textTertiary,
      ),
    );

    final texts = Column(
      crossAxisAlignment:
          horizontal ? CrossAxisAlignment.center : CrossAxisAlignment.start,
      children: [
        Text(
          step.title,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          textAlign: horizontal ? TextAlign.center : TextAlign.start,
          style: AppTheme.ts(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: AppTheme.textPrimary,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          step.detail,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          textAlign: horizontal ? TextAlign.center : TextAlign.start,
          style: AppTheme.ts(
            fontSize: 12,
            height: 1.3,
            color: AppTheme.textTertiary,
          ),
        ),
      ],
    );

    if (!horizontal) {
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          node,
          const SizedBox(width: 10),
          Expanded(child: texts),
        ],
      );
    }

    return Column(
      children: [
        node,
        const SizedBox(height: 8),
        texts,
      ],
    );
  }
}

class _CompactResultSummary extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _CompactResultSummary({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final metrics = [
      ('进行中任务', snapshot.runningCount.toString(), Icons.sync_rounded),
      ('已完成任务', snapshot.completedCount.toString(), Icons.check_rounded),
      ('总任务数', snapshot.tasks.length.toString(), Icons.layers_outlined),
      ('整体进度', '${(snapshot.progressRatio * 100).round()}%', Icons.adjust),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '结果摘要',
          style: AppTheme.ts(
            fontSize: 14,
            fontWeight: FontWeight.w800,
            color: AppTheme.textPrimary,
          ),
        ),
        const SizedBox(height: 10),
        LayoutBuilder(
          builder: (context, constraints) {
            final columns = constraints.maxWidth < 560 ? 2 : 4;
            return GridView.count(
              crossAxisCount: columns,
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: columns == 2 ? 2.8 : 1.62,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              children: [
                for (final metric in metrics)
                  _CompactMetricCard(
                    label: metric.$1,
                    value: metric.$2,
                    icon: metric.$3,
                  ),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _CompactMetricCard extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;

  const _CompactMetricCard({
    required this.label,
    required this.value,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover.withValues(alpha: 0.7),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border),
      ),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: AppTheme.accent.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Icon(icon, size: 15, color: AppTheme.accent),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    color: AppTheme.textTertiary,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  value,
                  style: AppTheme.ts(
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                    color: label == '整体进度'
                        ? AppTheme.accent
                        : AppTheme.textPrimary,
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

class _RunStatusIcon extends StatelessWidget {
  final String status;

  const _RunStatusIcon({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Container(
      width: 34,
      height: 34,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.2)),
      ),
      child: Center(
        child: status == "running"
            ? SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: color,
                  backgroundColor: color.withValues(alpha: 0.12),
                ),
              )
            : Icon(_statusIcon(status), size: 18, color: color),
      ),
    );
  }
}

class _ProgressMetricPill extends StatelessWidget {
  final String label;
  final Color color;

  const _ProgressMetricPill({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.14)),
      ),
      child: Text(
        label,
        style: AppTheme.ts(
          fontSize: 10,
          fontWeight: FontWeight.w800,
          color: color,
        ),
      ),
    );
  }
}

class _ProgressTrack extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _ProgressTrack({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(snapshot.status);
    final ratio = snapshot.progressRatio;
    final displayRatio =
        ratio == 0 && snapshot.status == "running" ? 0.08 : ratio;
    return LayoutBuilder(
      builder: (context, constraints) {
        return Container(
          height: 5,
          decoration: BoxDecoration(
            color: AppTheme.border.withValues(alpha: 0.38),
            borderRadius: BorderRadius.circular(999),
          ),
          clipBehavior: Clip.antiAlias,
          child: Align(
            alignment: Alignment.centerLeft,
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 260),
              curve: Curves.easeOutCubic,
              width: constraints.maxWidth * displayRatio.clamp(0.0, 1.0),
              decoration: BoxDecoration(
                color: color,
                borderRadius: BorderRadius.circular(999),
                boxShadow: [
                  BoxShadow(
                    color: color.withValues(alpha: 0.22),
                    blurRadius: 10,
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

class _RunStageRail extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _RunStageRail({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final stages = _runStages(snapshot);
    if (stages.isEmpty) {
      return const SizedBox.shrink();
    }
    final activeStage = stages.lastWhere(
      (stage) => stage.status == "running",
      orElse: () => stages.lastWhere(
        (stage) => stage.status == "queued" || stage.status == "pending",
        orElse: () => stages.last,
      ),
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 11),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.2 : 0.38),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.58)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.route_outlined,
                size: 14,
                color: AppTheme.textTertiary,
              ),
              const SizedBox(width: 6),
              Text(
                "执行阶段",
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textSecondary,
                ),
              ),
              const Spacer(),
              Text(
                "当前：${activeStage.label}",
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  color: _statusColor(activeStage.status),
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          LayoutBuilder(
            builder: (context, constraints) {
              final columns = constraints.maxWidth >= 720
                  ? stages.length
                  : constraints.maxWidth >= 560
                      ? 3
                      : constraints.maxWidth >= 390
                          ? 2
                          : 1;
              final actualColumns =
                  stages.length < columns ? stages.length : columns;
              final tileWidth = actualColumns <= 1
                  ? constraints.maxWidth
                  : (constraints.maxWidth - (actualColumns - 1) * 8) /
                      actualColumns;
              return Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (var index = 0; index < stages.length; index++)
                    SizedBox(
                      width: tileWidth,
                      child: _RunStageTile(
                        stage: stages[index],
                        index: index + 1,
                      ),
                    ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _RunStageTile extends StatelessWidget {
  final _RunStage stage;
  final int index;

  const _RunStageTile({
    required this.stage,
    required this.index,
  });

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(stage.status);
    final active = stage.status == "running";
    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOutCubic,
      constraints: const BoxConstraints(minHeight: 74),
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            color.withValues(alpha: active ? 0.12 : 0.06),
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.18 : 0.44),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(12),
        border:
            Border.all(color: color.withValues(alpha: active ? 0.24 : 0.13)),
        boxShadow: active
            ? [
                BoxShadow(
                  color: color.withValues(alpha: AppTheme.isDark ? 0.18 : 0.1),
                  blurRadius: 14,
                  offset: const Offset(0, 7),
                ),
              ]
            : const [],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 30,
            height: 30,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: color.withValues(alpha: active ? 0.16 : 0.1),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: color.withValues(alpha: 0.18)),
            ),
            child: active
                ? SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(
                      strokeWidth: 1.8,
                      color: color,
                      backgroundColor: color.withValues(alpha: 0.12),
                    ),
                  )
                : Icon(
                    stage.status == "completed"
                        ? Icons.check_rounded
                        : stage.icon,
                    size: 15,
                    color: color,
                  ),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      index.toString().padLeft(2, "0"),
                      style: AppTheme.ts(
                        fontSize: 10,
                        height: 1,
                        fontWeight: FontWeight.w900,
                        color: color,
                      ),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        stage.label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.5,
                          height: 1.15,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                Text(
                  stage.description,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    height: 1.3,
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

class _RunFocusCard extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _RunFocusCard({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final focus = _RunFocus.fromSnapshot(snapshot);
    if (focus == null) {
      return const SizedBox.shrink();
    }
    final color = _statusColor(focus.status);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            color.withValues(alpha: AppTheme.isDark ? 0.12 : 0.075),
            AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.18 : 0.42),
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: color.withValues(alpha: 0.18)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(11),
              border: Border.all(color: color.withValues(alpha: 0.18)),
            ),
            child: Center(
              child: focus.status == "running"
                  ? SizedBox(
                      width: 15,
                      height: 15,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.8,
                        color: color,
                        backgroundColor: color.withValues(alpha: 0.12),
                      ),
                    )
                  : Icon(focus.icon, size: 16, color: color),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    _ProgressMetricPill(label: focus.label, color: color),
                    if (focus.stage.isNotEmpty) ...[
                      const SizedBox(width: 7),
                      Flexible(
                        child: Text(
                          focus.stage,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 10.8,
                            fontWeight: FontWeight.w800,
                            color: color,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 7),
                Text(
                  focus.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.8,
                    height: 1.25,
                    fontWeight: FontWeight.w800,
                    color: AppTheme.textPrimary,
                  ),
                ),
                if (focus.detail.isNotEmpty) ...[
                  const SizedBox(height: 5),
                  Text(
                    focus.detail,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11.4,
                      height: 1.42,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
                if (focus.nextAction.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _NextActionHint(label: focus.nextAction),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _RunActivityDigestCard extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _RunActivityDigestCard({required this.snapshot});

  static bool hasContent(_RunProgressSnapshot snapshot) {
    return _activeTaskForSnapshot(snapshot) != null ||
        snapshot.executionItems.isNotEmpty ||
        snapshot.productRefs.isNotEmpty ||
        snapshot.artifactRefs.isNotEmpty;
  }

  @override
  Widget build(BuildContext context) {
    final activeTask = _activeTaskForSnapshot(snapshot);
    final latestItem =
        snapshot.executionItems.isEmpty ? null : snapshot.executionItems.last;
    final outputText = _outputDigestText(snapshot);
    final tiles = <_ActivityDigestTileData>[
      if (activeTask != null)
        _ActivityDigestTileData(
          icon: _agentIcon(activeTask.targetAgentId),
          label: "正在处理",
          value: _taskDescription(activeTask),
          color: _statusColor(activeTask.status),
        ),
      if (latestItem != null)
        _ActivityDigestTileData(
          icon: latestItem.icon,
          label: "最近操作",
          value: _latestExecutionDigest(latestItem),
          color: _executionTraceColor(latestItem.kind),
        ),
      if (activeTask?.nextAction.isNotEmpty == true)
        _ActivityDigestTileData(
          icon: Icons.arrow_forward_rounded,
          label: "下一步",
          value: activeTask!.nextAction,
          color: AppTheme.textSecondary,
        ),
      if (outputText.isNotEmpty)
        _ActivityDigestTileData(
          icon: Icons.inventory_2_outlined,
          label: "已产出",
          value: outputText,
          color: AppTheme.accentHover,
        ),
    ];
    if (tiles.isEmpty) {
      return const SizedBox.shrink();
    }
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 11),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.18 : 0.36),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.58)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.monitor_heart_outlined,
                size: 14,
                color: AppTheme.textTertiary,
              ),
              const SizedBox(width: 6),
              Text(
                "实时动态",
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textSecondary,
                ),
              ),
              const Spacer(),
              Text(
                _activityStatusLabel(snapshot),
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  color: _statusColor(snapshot.status),
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          LayoutBuilder(
            builder: (context, constraints) {
              final columnCount = constraints.maxWidth >= 620
                  ? 2
                  : constraints.maxWidth >= 420
                      ? 2
                      : 1;
              final actualColumns =
                  tiles.length < columnCount ? tiles.length : columnCount;
              final tileWidth = actualColumns <= 1
                  ? constraints.maxWidth
                  : (constraints.maxWidth - (actualColumns - 1) * 8) /
                      actualColumns;
              return Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final tile in tiles)
                    SizedBox(
                      width: tileWidth,
                      child: _ActivityDigestTile(data: tile),
                    ),
                ],
              );
            },
          ),
          if (snapshot.productRefs.isNotEmpty ||
              snapshot.artifactRefs.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 9),
              child: _ReferenceWrap(
                icon: Icons.inventory_2_outlined,
                values: [
                  ...snapshot.productRefs,
                  ...snapshot.artifactRefs,
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _ActivityDigestTileData {
  final IconData icon;
  final String label;
  final String value;
  final Color color;

  const _ActivityDigestTileData({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });
}

class _ActivityDigestTile extends StatelessWidget {
  final _ActivityDigestTileData data;

  const _ActivityDigestTile({required this.data});

  @override
  Widget build(BuildContext context) {
    return Container(
      constraints: const BoxConstraints(minHeight: 72),
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: data.color.withValues(alpha: AppTheme.isDark ? 0.08 : 0.045),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: data.color.withValues(alpha: 0.15)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: data.color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: data.color.withValues(alpha: 0.18)),
            ),
            child: Icon(data.icon, size: 14, color: data.color),
          ),
          const SizedBox(width: 9),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  data.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 10.5,
                    height: 1.1,
                    fontWeight: FontWeight.w800,
                    color: data.color,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  data.value,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11,
                    height: 1.35,
                    fontWeight: FontWeight.w600,
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

class _AgentPipeline extends StatelessWidget {
  final List<_AgentTaskProgress> tasks;

  const _AgentPipeline({required this.tasks});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 11),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.18 : 0.36),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.58)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(
                Icons.account_tree_outlined,
                size: 14,
                color: AppTheme.textTertiary,
              ),
              const SizedBox(width: 6),
              Text(
                "Agent 流程",
                style: AppTheme.ts(
                  fontSize: 11.5,
                  fontWeight: FontWeight.w800,
                  color: AppTheme.textSecondary,
                ),
              ),
              const Spacer(),
              Text(
                "${tasks.length} 个协作者",
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          LayoutBuilder(
            builder: (context, constraints) {
              final columnCount = constraints.maxWidth >= 620
                  ? 3
                  : constraints.maxWidth >= 420
                      ? 2
                      : 1;
              final actualColumns =
                  tasks.length < columnCount ? tasks.length : columnCount;
              final tileWidth = actualColumns <= 1
                  ? constraints.maxWidth
                  : (constraints.maxWidth - (actualColumns - 1) * 8) /
                      actualColumns;
              return Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final task in tasks)
                    SizedBox(
                      width: tileWidth,
                      child: _AgentPipelineTile(task: task),
                    ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _AgentPipelineTile extends StatelessWidget {
  final _AgentTaskProgress task;

  const _AgentPipelineTile({required this.task});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(task.status);
    final description = _agentPipelineDescription(task);
    return Container(
      constraints: const BoxConstraints(minHeight: 78),
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: AppTheme.isDark ? 0.08 : 0.045),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.16)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: color.withValues(alpha: 0.18)),
            ),
            child: Icon(_agentIcon(task.targetAgentId), size: 14, color: color),
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
                        _agentDisplayName(task.targetAgentId),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11.5,
                          height: 1.2,
                          fontWeight: FontWeight.w800,
                          color: AppTheme.textPrimary,
                        ),
                      ),
                    ),
                    const SizedBox(width: 6),
                    _StatusBadge(status: task.status, compact: true),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  description,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 10.8,
                    height: 1.35,
                    color: AppTheme.textSecondary,
                  ),
                ),
                if (task.hasStepProgress) ...[
                  const SizedBox(height: 8),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      value: task.progressRatio.clamp(0.0, 1.0),
                      minHeight: 3,
                      color: color,
                      backgroundColor: color.withValues(alpha: 0.12),
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

class _AgentTaskCard extends StatelessWidget {
  final _AgentTaskProgress task;

  const _AgentTaskCard({required this.task});

  @override
  Widget build(BuildContext context) {
    final taskDescription = _taskDescription(task);
    final color = _statusColor(task.status);
    return Container(
      width: double.infinity,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color:
            AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.54 : 0.78),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.78)),
      ),
      child: Stack(
        children: [
          Positioned.fill(
            left: 0,
            child: Align(
              alignment: Alignment.centerLeft,
              child: Container(
                width: 3,
                color: color.withValues(alpha: 0.78),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(13, 12, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _AgentStatusAvatar(task: task),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Flexible(
                                child: Text(
                                  _agentDisplayName(task.targetAgentId),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: AppTheme.ts(
                                    fontSize: 12.5,
                                    fontWeight: FontWeight.w800,
                                    color: AppTheme.textPrimary,
                                  ),
                                ),
                              ),
                              const SizedBox(width: 8),
                              _StatusBadge(status: task.status, compact: true),
                            ],
                          ),
                          const SizedBox(height: 3),
                          Text(
                            _agentRoleLabel(task.targetAgentId),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 10.5,
                              fontWeight: FontWeight.w600,
                              color: AppTheme.textTertiary,
                            ),
                          ),
                          if (task.hasStepProgress) ...[
                            const SizedBox(height: 7),
                            _TaskStepTrack(task: task),
                          ],
                        ],
                      ),
                    ),
                  ],
                ),
                if (taskDescription.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Text(
                    taskDescription,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 11.5,
                      height: 1.45,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ],
                if (task.currentStage.isNotEmpty) ...[
                  const SizedBox(height: 9),
                  _StageChip(label: task.currentStage, status: task.status),
                ],
                if (task.nextAction.isNotEmpty &&
                    !_isTerminalTaskStatus(task.status)) ...[
                  const SizedBox(height: 8),
                  _NextActionHint(label: task.nextAction),
                ],
                if (task.status == "running") ...[
                  const SizedBox(height: 10),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(999),
                    child: LinearProgressIndicator(
                      minHeight: 3,
                      color: color,
                      backgroundColor: color.withValues(alpha: 0.1),
                    ),
                  ),
                ],
                if (task.timeline.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  _AgentTaskTimeline(items: task.timeline),
                ],
                if (task.artifactRefs.isNotEmpty) ...[
                  const SizedBox(height: 9),
                  _ReferenceWrap(
                    icon: Icons.insert_drive_file_outlined,
                    values: task.artifactRefs,
                  ),
                ],
                if (task.productRefs.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  _ReferenceWrap(
                    icon: Icons.inventory_2_outlined,
                    values: task.productRefs,
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

class _AgentStatusAvatar extends StatelessWidget {
  final _AgentTaskProgress task;

  const _AgentStatusAvatar({required this.task});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(task.status);
    return Container(
      width: 34,
      height: 34,
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.16)),
      ),
      child: Center(
        child: task.status == "running"
            ? SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 1.9,
                  color: color,
                  backgroundColor: color.withValues(alpha: 0.1),
                ),
              )
            : Icon(_agentIcon(task.targetAgentId), size: 17, color: color),
      ),
    );
  }
}

class _TaskStepTrack extends StatelessWidget {
  final _AgentTaskProgress task;

  const _TaskStepTrack({required this.task});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(task.status);
    return Row(
      children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: task.progressRatio.clamp(0.0, 1.0),
              minHeight: 4,
              color: color,
              backgroundColor: color.withValues(alpha: 0.1),
            ),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          "${task.stepIndex}/${task.totalSteps}",
          style: AppTheme.ts(
            fontSize: 10.5,
            fontWeight: FontWeight.w800,
            color: color,
          ),
        ),
      ],
    );
  }
}

class _NextActionHint extends StatelessWidget {
  final String label;

  const _NextActionHint({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 7),
      decoration: BoxDecoration(
        color: AppTheme.surfaceHover
            .withValues(alpha: AppTheme.isDark ? 0.32 : 0.58),
        borderRadius: BorderRadius.circular(11),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.58)),
      ),
      child: Row(
        children: [
          Icon(
            Icons.arrow_forward_rounded,
            size: 13,
            color: AppTheme.textTertiary,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              "下一步：$label",
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 10.8,
                fontWeight: FontWeight.w600,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AgentTaskTimeline extends StatelessWidget {
  final List<_TimelineItem> items;

  const _AgentTaskTimeline({required this.items});

  @override
  Widget build(BuildContext context) {
    final compactItems = _compactTimelineItems(items);
    final visibleItems = compactItems.length > 4
        ? compactItems.sublist(compactItems.length - 4)
        : compactItems;
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 3),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.22 : 0.36),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.62)),
      ),
      child: Column(
        children: [
          for (var index = 0; index < visibleItems.length; index++)
            Padding(
              padding: EdgeInsets.only(
                bottom: index == visibleItems.length - 1 ? 6 : 9,
              ),
              child: _TimelineRow(
                item: visibleItems[index],
                showConnector: index != visibleItems.length - 1,
              ),
            ),
        ],
      ),
    );
  }
}

class _TimelineRow extends StatelessWidget {
  final _TimelineItem item;
  final bool showConnector;

  const _TimelineRow({required this.item, required this.showConnector});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(item.status);
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 10,
            child: Column(
              children: [
                Container(
                  width: 7,
                  height: 7,
                  margin: const EdgeInsets.only(top: 5),
                  decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                    boxShadow: item.status == "running"
                        ? [
                            BoxShadow(
                              color: color.withValues(alpha: 0.26),
                              blurRadius: 9,
                              spreadRadius: 1,
                            ),
                          ]
                        : const [],
                  ),
                ),
                if (showConnector)
                  Expanded(
                    child: Container(
                      width: 1,
                      margin: const EdgeInsets.only(top: 3),
                      color: AppTheme.border.withValues(alpha: 0.54),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            DateFormat("HH:mm:ss").format(item.createdAt),
            style: AppTheme.ts(fontSize: 10.5, color: AppTheme.textTertiary),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              item.detail,
              style: AppTheme.ts(
                fontSize: 11,
                height: 1.4,
                color: AppTheme.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _RunProgressFooter extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _RunProgressFooter({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(snapshot.status);
    final text = switch (snapshot.status) {
      "completed" => "已完成，可在右侧求职资产中查看结果",
      "failed" => "任务失败，请查看失败 agent 的错误信息",
      "partial_failed" => "部分任务失败，已保留成功产物",
      _ => "完成后将刷新右侧求职资产",
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.12)),
      ),
      child: Row(
        children: [
          Icon(_statusIcon(snapshot.status), size: 14, color: color),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              text,
              style: AppTheme.ts(
                fontSize: 11,
                color: AppTheme.textSecondary,
                height: 1.35,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ExecutionTraceSection extends StatelessWidget {
  final List<_ExecutionTraceItem> items;

  const _ExecutionTraceSection({required this.items});

  @override
  Widget build(BuildContext context) {
    final visibleItems =
        items.length > 6 ? items.sublist(items.length - 6) : items;
    final summary = _ExecutionTraceSummary.fromItems(items);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(11, 11, 11, 10),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.22 : 0.42),
            AppTheme.surfaceHover
                .withValues(alpha: AppTheme.isDark ? 0.16 : 0.34),
          ],
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.58)),
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
                  color: AppTheme.accent.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(
                    color: AppTheme.accent.withValues(alpha: 0.15),
                  ),
                ),
                child: Icon(
                  Icons.bolt_outlined,
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
                      "执行动态",
                      style: AppTheme.ts(
                        fontSize: 11.8,
                        height: 1.15,
                        fontWeight: FontWeight.w800,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      "模型规划、工具执行和结果整理",
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
              Text(
                "${items.length} 条",
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w700,
                  color: AppTheme.textTertiary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          _ExecutionTraceSummaryStrip(summary: summary),
          const SizedBox(height: 9),
          for (var index = 0; index < visibleItems.length; index++)
            Padding(
              padding: EdgeInsets.only(
                bottom: index == visibleItems.length - 1 ? 0 : 8,
              ),
              child: _ExecutionTraceRow(item: visibleItems[index]),
            ),
        ],
      ),
    );
  }
}

class _ExecutionTraceRow extends StatelessWidget {
  final _ExecutionTraceItem item;

  const _ExecutionTraceRow({required this.item});

  @override
  Widget build(BuildContext context) {
    final color = _executionTraceColor(item.kind);
    final running = item.kind == "tool" || item.kind == "thinking";
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOutCubic,
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 9),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.5 : 0.8),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.14)),
        boxShadow: [
          BoxShadow(
            color:
                Colors.black.withValues(alpha: AppTheme.isDark ? 0.12 : 0.035),
            blurRadius: 12,
            offset: const Offset(0, 5),
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
                width: 30,
                height: 30,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: color.withValues(alpha: 0.15)),
                ),
                child: Icon(item.icon, size: 14, color: color),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        Expanded(
                          child: Text(
                            item.title,
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
                        const SizedBox(width: 8),
                        _ExecutionTraceStatusPill(item: item),
                      ],
                    ),
                    if (item.detail.isNotEmpty) ...[
                      const SizedBox(height: 5),
                      Text(
                        item.detail,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 10.9,
                          height: 1.38,
                          fontWeight: FontWeight.w600,
                          color: AppTheme.textSecondary,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              _ExecutionTraceMetaChip(
                icon: Icons.schedule_rounded,
                label: DateFormat("HH:mm:ss").format(item.createdAt),
              ),
              if (item.durationLabel.isNotEmpty) ...[
                const SizedBox(width: 7),
                _ExecutionTraceMetaChip(
                  icon: Icons.timer_outlined,
                  label: item.durationLabel.replaceFirst("耗时 ", ""),
                ),
              ],
              if (running) ...[
                const SizedBox(width: 7),
                _ExecutionTraceMetaChip(
                  icon: Icons.sync_rounded,
                  label: "持续处理中",
                  color: color,
                ),
              ],
            ],
          ),
          if (running) ...[
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: LinearProgressIndicator(
                minHeight: 3,
                color: color,
                backgroundColor: color.withValues(alpha: 0.1),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ExecutionTraceSummaryStrip extends StatelessWidget {
  final _ExecutionTraceSummary summary;

  const _ExecutionTraceSummaryStrip({required this.summary});

  @override
  Widget build(BuildContext context) {
    final chips = [
      _TraceSummaryChipData(
        icon: Icons.check_circle_outline_rounded,
        label: "${summary.completedCount} 已完成",
        color: AppTheme.accentHover,
      ),
      if (summary.runningCount > 0)
        _TraceSummaryChipData(
          icon: Icons.sync_rounded,
          label: "${summary.runningCount} 处理中",
          color: const Color(0xFF2563EB),
        ),
      if (summary.failedCount > 0)
        _TraceSummaryChipData(
          icon: Icons.error_outline_rounded,
          label: "${summary.failedCount} 失败",
          color: AppTheme.danger,
        ),
      if (summary.planningCount > 0)
        _TraceSummaryChipData(
          icon: Icons.psychology_alt_outlined,
          label: "${summary.planningCount} 次规划",
          color: const Color(0xFF7C3AED),
        ),
    ];
    return Wrap(
      spacing: 7,
      runSpacing: 7,
      children: [
        for (final chip in chips) _TraceSummaryChip(data: chip),
      ],
    );
  }
}

class _TraceSummaryChipData {
  final IconData icon;
  final String label;
  final Color color;

  const _TraceSummaryChipData({
    required this.icon,
    required this.label,
    required this.color,
  });
}

class _TraceSummaryChip extends StatelessWidget {
  final _TraceSummaryChipData data;

  const _TraceSummaryChip({required this.data});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: data.color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: data.color.withValues(alpha: 0.13)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(data.icon, size: 12, color: data.color),
          const SizedBox(width: 5),
          Text(
            data.label,
            style: AppTheme.ts(
              fontSize: 10.5,
              height: 1.1,
              fontWeight: FontWeight.w800,
              color: data.color,
            ),
          ),
        ],
      ),
    );
  }
}

class _ExecutionTraceMetaChip extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color? color;

  const _ExecutionTraceMetaChip({
    required this.icon,
    required this.label,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    final resolvedColor = color ?? AppTheme.textTertiary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.24 : 0.48),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.58)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 11.5, color: resolvedColor),
          const SizedBox(width: 4),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 10,
              height: 1.1,
              fontWeight: FontWeight.w700,
              color: resolvedColor,
            ),
          ),
        ],
      ),
    );
  }
}

class _ExecutionTraceSummary {
  final int completedCount;
  final int runningCount;
  final int failedCount;
  final int planningCount;

  const _ExecutionTraceSummary({
    required this.completedCount,
    required this.runningCount,
    required this.failedCount,
    required this.planningCount,
  });

  factory _ExecutionTraceSummary.fromItems(List<_ExecutionTraceItem> items) {
    var completed = 0;
    var running = 0;
    var failed = 0;
    var planning = 0;
    for (final item in items) {
      switch (item.kind) {
        case "tool_success":
        case "finished":
        case "started":
          completed += 1;
          break;
        case "tool":
          running += 1;
          break;
        case "tool_failed":
          failed += 1;
          break;
        case "thinking":
          planning += 1;
          break;
      }
    }
    return _ExecutionTraceSummary(
      completedCount: completed,
      runningCount: running,
      failedCount: failed,
      planningCount: planning,
    );
  }
}

class _ExecutionTraceStatusPill extends StatelessWidget {
  final _ExecutionTraceItem item;

  const _ExecutionTraceStatusPill({required this.item});

  @override
  Widget build(BuildContext context) {
    final color = _executionTraceColor(item.kind);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.14)),
      ),
      child: Text(
        item.statusLabel,
        style: AppTheme.ts(
          fontSize: 10,
          height: 1.1,
          fontWeight: FontWeight.w800,
          color: color,
        ),
      ),
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final String status;
  final bool compact;

  const _StatusBadge({required this.status, this.compact = false});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 6 : 7,
        vertical: compact ? 2.5 : 3,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.11),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.12)),
      ),
      child: Text(
        _statusLabel(status),
        style: AppTheme.ts(
          fontSize: compact ? 10 : 10.5,
          fontWeight: FontWeight.w800,
          color: color,
        ),
      ),
    );
  }
}

class _StageChip extends StatelessWidget {
  final String label;
  final String status;

  const _StageChip({required this.label, required this.status});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.14)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (status == "running")
            SizedBox(
              width: 8,
              height: 8,
              child: CircularProgressIndicator(
                strokeWidth: 1.5,
                color: color,
              ),
            )
          else
            Icon(_statusIcon(status), size: 12, color: color),
          const SizedBox(width: 6),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 10.5,
              fontWeight: FontWeight.w800,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

class _ReferenceWrap extends StatelessWidget {
  final IconData icon;
  final List<String> values;

  const _ReferenceWrap({required this.icon, required this.values});

  @override
  Widget build(BuildContext context) {
    final visibleValues = values.take(4).toList();
    return Wrap(
      spacing: 7,
      runSpacing: 7,
      children: [
        for (final value in visibleValues)
          Tooltip(
            message: value,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
              decoration: BoxDecoration(
                color:
                    AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.2 : 0.5),
                borderRadius: BorderRadius.circular(9),
                border:
                    Border.all(color: AppTheme.border.withValues(alpha: 0.74)),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon, size: 12, color: AppTheme.textTertiary),
                  const SizedBox(width: 5),
                  ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 138),
                    child: Text(
                      _referenceLabel(value),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.5,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.textSecondary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        if (values.length > visibleValues.length)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
            decoration: BoxDecoration(
              color: AppTheme.surfaceHover.withValues(alpha: 0.52),
              borderRadius: BorderRadius.circular(9),
              border:
                  Border.all(color: AppTheme.border.withValues(alpha: 0.74)),
            ),
            child: Text(
              "+${values.length - visibleValues.length}",
              style: AppTheme.ts(
                fontSize: 10.5,
                fontWeight: FontWeight.w800,
                color: AppTheme.textTertiary,
              ),
            ),
          ),
      ],
    );
  }
}

class _RunProgressSnapshot {
  final String status;
  final List<_AgentTaskProgress> tasks;
  final List<_ExecutionTraceItem> executionItems;

  const _RunProgressSnapshot({
    required this.status,
    required this.tasks,
    required this.executionItems,
  });

  int get runningCount =>
      tasks.where((task) => task.status == "running").length;

  int get waitingCount => tasks
      .where((task) => task.status == "queued" || task.status == "pending")
      .length;

  int get completedCount =>
      tasks.where((task) => task.status == "completed").length;

  int get failedCount => tasks.where((task) => task.status == "failed").length;

  List<String> get artifactRefs => _uniqueRefs(
        tasks.expand((task) => task.artifactRefs),
      );

  List<String> get productRefs => _uniqueRefs(
        tasks.expand((task) => task.productRefs),
      );

  double get progressRatio {
    if (tasks.isEmpty) {
      return status == "completed" ? 1 : 0.22;
    }
    final total = tasks.fold<double>(
      0,
      (sum, task) => sum + task.progressRatio,
    );
    return (total / tasks.length).clamp(0.0, 1.0).toDouble();
  }

  factory _RunProgressSnapshot.fromEvents(List<EventView> events) {
    final executionItems = _executionTraceItems(events);
    final filtered = events
        .where((event) => _agentTaskEventTypes.contains(event.type))
        .toList()
      ..sort((left, right) => left.createdAt.compareTo(right.createdAt));
    String status = executionItems.any((item) => item.kind == "finished")
        ? "completed"
        : "running";
    final tasks = <String, _AgentTaskProgress>{};
    final taskIdsByChildRunId = <String, String>{};

    for (final event in filtered) {
      final payload = event.payload;
      if (event.type == "agent_task_group_created") {
        status = _payloadText(payload, "status", fallback: status);
        final rawTasks = payload["tasks"];
        if (rawTasks is List) {
          for (final raw in rawTasks) {
            if (raw is! Map) continue;
            final taskPayload = Map<String, dynamic>.from(raw);
            final taskId = _payloadText(taskPayload, "task_id");
            if (taskId.isEmpty) continue;
            final task = _AgentTaskProgress.fromPayload(taskPayload);
            task.timeline.add(
              _TimelineItem(
                detail: "已分配任务",
                stage: "queued",
                status: task.status,
                createdAt: event.createdAt,
              ),
            );
            tasks[taskId] = task;
            final childRunId = task.childRunId;
            if (childRunId.isNotEmpty) {
              taskIdsByChildRunId[childRunId] = taskId;
            }
          }
        }
        continue;
      }
      if (event.type == "agent_task_group_completed") {
        status = _payloadText(payload, "status", fallback: status);
        continue;
      }

      var taskId = _payloadText(payload, "task_id");
      if (taskId.isEmpty) {
        final childRunId = _payloadText(payload, "child_run_id");
        taskId = taskIdsByChildRunId[childRunId] ?? "";
      }
      if (taskId.isEmpty) continue;
      final previous = tasks[taskId];
      final next = event.type == "agent_task_progress"
          ? _AgentTaskProgress.fromProgressPayload(
              payload,
              previous: previous,
            )
          : _AgentTaskProgress.fromPayload(payload, previous: previous);
      next.timeline.addAll(previous?.timeline ?? const []);
      next.timeline.add(
        _TimelineItem(
          detail: _timelineDetail(event.type, next),
          stage: next.currentStage,
          status: event.type == "agent_task_progress"
              ? _payloadText(payload, "status", fallback: next.status)
              : next.status,
          createdAt: event.createdAt,
        ),
      );
      tasks[taskId] = next;
      final childRunId = next.childRunId;
      if (childRunId.isNotEmpty) {
        taskIdsByChildRunId[childRunId] = taskId;
      }
    }

    if (tasks.values.any((task) => task.status == "running")) {
      status = "running";
    } else if (tasks.values.isNotEmpty &&
        tasks.values.every((task) => task.status == "completed")) {
      status = "completed";
    } else if (tasks.values.any((task) => task.status == "failed") &&
        tasks.values.any((task) => task.status == "completed")) {
      status = "partial_failed";
    } else if (tasks.values.isNotEmpty &&
        tasks.values.every((task) => task.status == "failed")) {
      status = "failed";
    }

    return _RunProgressSnapshot(
      status: status,
      tasks: tasks.values.toList(),
      executionItems: executionItems,
    );
  }
}

class _ExecutionTraceItem {
  final String kind;
  final String title;
  final String detail;
  final String statusLabel;
  final String durationLabel;
  final IconData icon;
  final DateTime createdAt;

  const _ExecutionTraceItem({
    required this.kind,
    required this.title,
    required this.detail,
    required this.statusLabel,
    this.durationLabel = "",
    required this.icon,
    required this.createdAt,
  });
}

class _PendingToolOperation {
  final String toolCallId;
  final String name;
  final String action;
  final String detail;
  final DateTime createdAt;

  const _PendingToolOperation({
    required this.toolCallId,
    required this.name,
    required this.action,
    required this.detail,
    required this.createdAt,
  });
}

class _RunStage {
  final String label;
  final String description;
  final String status;
  final IconData icon;

  const _RunStage({
    required this.label,
    required this.description,
    required this.status,
    required this.icon,
  });
}

bool _shouldCollapseDetailsByDefault(_RunProgressSnapshot snapshot) {
  return snapshot.status == "completed";
}

class _RunFocus {
  final String label;
  final String title;
  final String detail;
  final String stage;
  final String nextAction;
  final String status;
  final IconData icon;

  const _RunFocus({
    required this.label,
    required this.title,
    required this.detail,
    required this.stage,
    required this.nextAction,
    required this.status,
    required this.icon,
  });

  static _RunFocus? fromSnapshot(_RunProgressSnapshot snapshot) {
    final runningTasks =
        snapshot.tasks.where((task) => task.status == "running").toList();
    if (runningTasks.isNotEmpty) {
      final task = runningTasks.reduce((left, right) {
        final leftTime = left.timeline.isEmpty
            ? DateTime.fromMillisecondsSinceEpoch(0)
            : left.timeline.last.createdAt;
        final rightTime = right.timeline.isEmpty
            ? DateTime.fromMillisecondsSinceEpoch(0)
            : right.timeline.last.createdAt;
        return rightTime.isAfter(leftTime) ? right : left;
      });
      return _RunFocus(
        label: "当前处理",
        title: _agentDisplayName(task.targetAgentId),
        detail: _taskDescription(task),
        stage: task.currentStage.isEmpty ? task.title : task.currentStage,
        nextAction: task.nextAction,
        status: task.status,
        icon: _agentIcon(task.targetAgentId),
      );
    }

    final failedTasks =
        snapshot.tasks.where((task) => task.status == "failed").toList();
    if (failedTasks.isNotEmpty) {
      final task = failedTasks.last;
      return _RunFocus(
        label: "需要关注",
        title: _agentDisplayName(task.targetAgentId),
        detail: _taskDescription(task),
        stage: "任务失败",
        nextAction: "",
        status: task.status,
        icon: Icons.warning_amber_rounded,
      );
    }

    final waitingTasks = snapshot.tasks
        .where((task) => task.status == "queued" || task.status == "pending")
        .toList();
    if (waitingTasks.isNotEmpty) {
      final task = waitingTasks.first;
      return _RunFocus(
        label: "排队中",
        title: _agentDisplayName(task.targetAgentId),
        detail: _taskDescription(task),
        stage: task.title,
        nextAction: "",
        status: task.status,
        icon: _agentIcon(task.targetAgentId),
      );
    }

    if (snapshot.status == "completed" && snapshot.tasks.isNotEmpty) {
      return _RunFocus(
        label: "已完成",
        title: "协作结果已返回",
        detail: "可在右侧求职资产查看生成的画像、报告或版本记录",
        stage: "结果整理",
        nextAction: "",
        status: snapshot.status,
        icon: Icons.check_rounded,
      );
    }

    if (snapshot.executionItems.isNotEmpty) {
      final item = snapshot.executionItems.last;
      return _RunFocus(
        label: snapshot.status == "completed" ? "已完成" : "当前处理",
        title: item.title,
        detail: item.detail,
        stage: _executionStageLabel(item.kind),
        nextAction: "",
        status: snapshot.status,
        icon: item.icon,
      );
    }
    return null;
  }
}

_AgentTaskProgress? _activeTaskForSnapshot(_RunProgressSnapshot snapshot) {
  final runningTasks =
      snapshot.tasks.where((task) => task.status == "running").toList();
  if (runningTasks.isNotEmpty) {
    return runningTasks.reduce((left, right) {
      final leftTime = left.timeline.isEmpty
          ? DateTime.fromMillisecondsSinceEpoch(0)
          : left.timeline.last.createdAt;
      final rightTime = right.timeline.isEmpty
          ? DateTime.fromMillisecondsSinceEpoch(0)
          : right.timeline.last.createdAt;
      return rightTime.isAfter(leftTime) ? right : left;
    });
  }
  final waitingTasks = snapshot.tasks
      .where((task) => task.status == "queued" || task.status == "pending")
      .toList();
  if (waitingTasks.isNotEmpty) return waitingTasks.first;
  final failedTasks =
      snapshot.tasks.where((task) => task.status == "failed").toList();
  if (failedTasks.isNotEmpty) return failedTasks.last;
  if (snapshot.tasks.isNotEmpty) return snapshot.tasks.last;
  return null;
}

String _latestExecutionDigest(_ExecutionTraceItem item) {
  final detail = item.detail.trim();
  if (detail.isEmpty) return item.title;
  return _truncateText("${item.title}：$detail", 96);
}

String _outputDigestText(_RunProgressSnapshot snapshot) {
  final parts = <String>[];
  final productCount = snapshot.productRefs.length;
  final artifactCount = snapshot.artifactRefs.length;
  if (productCount > 0) {
    parts.add("$productCount 个产品记录");
  }
  if (artifactCount > 0) {
    parts.add("$artifactCount 个文件引用");
  }
  return parts.join(" · ");
}

String _activityStatusLabel(_RunProgressSnapshot snapshot) {
  if (snapshot.runningCount > 0) {
    return "处理中";
  }
  if (snapshot.waitingCount > 0) {
    return "排队中";
  }
  return _statusLabel(snapshot.status);
}

class _AgentTaskProgress {
  final String taskId;
  final String taskGroupId;
  final String targetAgentId;
  final String childRunId;
  final String status;
  final String title;
  final String detail;
  final String currentStage;
  final String phase;
  final String currentAction;
  final String nextAction;
  final int stepIndex;
  final int totalSteps;
  final List<String> artifactRefs;
  final List<String> productRefs;
  final List<_TimelineItem> timeline;

  _AgentTaskProgress({
    required this.taskId,
    required this.taskGroupId,
    required this.targetAgentId,
    required this.childRunId,
    required this.status,
    required this.title,
    required this.detail,
    required this.currentStage,
    required this.phase,
    required this.currentAction,
    required this.nextAction,
    required this.stepIndex,
    required this.totalSteps,
    required this.artifactRefs,
    required this.productRefs,
    required this.timeline,
  });

  bool get hasStepProgress => stepIndex > 0 && totalSteps > 0;

  double get progressRatio {
    if (status == "completed") return 1;
    if (status == "failed" || status == "cancelled") return 1;
    if (hasStepProgress) {
      return (stepIndex / totalSteps).clamp(0.0, 1.0).toDouble();
    }
    if (status == "running") return 0.35;
    return 0;
  }

  factory _AgentTaskProgress.fromPayload(
    Map<String, dynamic> payload, {
    _AgentTaskProgress? previous,
  }) {
    final nextStatus =
        _payloadText(payload, "status", fallback: previous?.status ?? "queued");
    final nextStage = _isTerminalTaskStatus(nextStatus)
        ? ""
        : _payloadText(
            payload,
            "stage",
            fallback: previous?.currentStage ?? "",
          );
    return _AgentTaskProgress(
      taskId:
          _payloadText(payload, "task_id", fallback: previous?.taskId ?? ""),
      taskGroupId: _payloadText(
        payload,
        "task_group_id",
        fallback: previous?.taskGroupId ?? "",
      ),
      targetAgentId: _payloadText(
        payload,
        "target_agent_id",
        fallback: previous?.targetAgentId ?? "agent",
      ),
      childRunId: _payloadText(
        payload,
        "child_run_id",
        fallback: previous?.childRunId ?? "",
      ),
      status: nextStatus,
      title:
          _payloadText(payload, "title", fallback: previous?.title ?? "执行任务"),
      detail: _payloadText(payload, "detail", fallback: previous?.detail ?? ""),
      currentStage: nextStage,
      phase: _payloadText(payload, "phase", fallback: previous?.phase ?? ""),
      currentAction: _payloadText(
        payload,
        "current_action",
        fallback: previous?.currentAction ?? "",
      ),
      nextAction: _payloadText(
        payload,
        "next_action",
        fallback: previous?.nextAction ?? "",
      ),
      stepIndex: _payloadInt(payload["step_index"], previous?.stepIndex ?? 0),
      totalSteps:
          _payloadInt(payload["total_steps"], previous?.totalSteps ?? 0),
      artifactRefs:
          _payloadStringList(payload["artifact_refs"], previous?.artifactRefs),
      productRefs:
          _payloadStringList(payload["product_refs"], previous?.productRefs),
      timeline: [],
    );
  }

  factory _AgentTaskProgress.fromProgressPayload(
    Map<String, dynamic> payload, {
    _AgentTaskProgress? previous,
  }) {
    final progressStatus = _payloadText(payload, "status", fallback: "running");
    final nextStatus = previous?.status == "completed" ||
            previous?.status == "failed" ||
            previous?.status == "cancelled"
        ? previous!.status
        : progressStatus == "failed"
            ? "running"
            : previous?.status ?? "running";
    return _AgentTaskProgress(
      taskId:
          _payloadText(payload, "task_id", fallback: previous?.taskId ?? ""),
      taskGroupId: _payloadText(
        payload,
        "task_group_id",
        fallback: previous?.taskGroupId ?? "",
      ),
      targetAgentId: _payloadText(
        payload,
        "target_agent_id",
        fallback: previous?.targetAgentId ?? "agent",
      ),
      childRunId: _payloadText(
        payload,
        "child_run_id",
        fallback: previous?.childRunId ?? "",
      ),
      status: nextStatus,
      title:
          _payloadText(payload, "title", fallback: previous?.title ?? "执行任务"),
      detail: _payloadText(payload, "detail", fallback: previous?.detail ?? ""),
      currentStage: _stageLabel(_payloadText(payload, "stage")),
      phase: _payloadText(payload, "phase", fallback: previous?.phase ?? ""),
      currentAction: _payloadText(
        payload,
        "current_action",
        fallback: previous?.currentAction ?? "",
      ),
      nextAction: _payloadText(
        payload,
        "next_action",
        fallback: previous?.nextAction ?? "",
      ),
      stepIndex: _payloadInt(payload["step_index"], previous?.stepIndex ?? 0),
      totalSteps:
          _payloadInt(payload["total_steps"], previous?.totalSteps ?? 0),
      artifactRefs: _mergePayloadStringLists(
        previous?.artifactRefs,
        payload["artifact_refs"],
      ),
      productRefs: _mergePayloadStringLists(
        previous?.productRefs,
        payload["product_refs"],
      ),
      timeline: [],
    );
  }
}

class _TimelineItem {
  final String detail;
  final String stage;
  final String status;
  final DateTime createdAt;

  const _TimelineItem({
    required this.detail,
    required this.stage,
    required this.status,
    required this.createdAt,
  });
}

String _timelineDetail(String eventType, _AgentTaskProgress task) {
  if (eventType == "agent_task_started") {
    return _compactProgressText(
      title: task.title,
      detail: task.detail,
      fallback: "开始执行",
      maxLength: 64,
    );
  }
  if (eventType == "agent_task_progress") {
    final stage = task.currentStage;
    if (task.currentAction.isNotEmpty) {
      if (stage.isEmpty || task.currentAction.startsWith(stage)) {
        return _truncateText(task.currentAction, 84);
      }
      return _truncateText("$stage：${task.currentAction}", 84);
    }
    final detail = _compactProgressText(
      title: task.title,
      detail: task.detail,
      fallback: stage.isEmpty ? "状态更新" : stage,
      maxLength: 72,
    );
    if (stage.isEmpty || detail.startsWith(stage)) {
      return detail;
    }
    return _truncateText("$stage：$detail", 84);
  }
  if (eventType == "agent_task_completed") {
    return "任务完成";
  }
  if (eventType == "agent_task_failed") {
    return _compactProgressText(
      title: task.title,
      detail: task.detail,
      fallback: "任务失败",
      maxLength: 84,
    );
  }
  return _compactProgressText(
    title: task.title,
    detail: task.detail,
    fallback: "状态更新",
    maxLength: 72,
  );
}

String _taskDescription(_AgentTaskProgress task) {
  if (task.status == "completed") {
    if (task.currentAction.isNotEmpty) return task.currentAction;
    return "已完成，产物已同步到求职资产";
  }
  if (task.status == "failed") {
    return _compactProgressText(
      title: task.title,
      detail: task.detail,
      fallback: "任务失败",
      maxLength: 92,
    );
  }
  if (task.currentAction.isNotEmpty) {
    return _truncateText(task.currentAction, 120);
  }
  return _compactProgressText(
    title: task.title,
    detail: task.detail,
    fallback: task.status == "running" ? "正在处理任务" : "等待执行",
    maxLength: 92,
  );
}

String _agentPipelineDescription(_AgentTaskProgress task) {
  if (task.status == "completed") {
    if (task.productRefs.isNotEmpty) {
      return "已产出 ${task.productRefs.length} 个产品记录";
    }
    return "已完成当前子任务";
  }
  if (task.status == "failed") {
    return _taskDescription(task);
  }
  if (task.status == "running") {
    if (task.currentAction.isNotEmpty) {
      return _truncateText(task.currentAction, 72);
    }
    if (task.currentStage.isNotEmpty) {
      return "正在${task.currentStage}";
    }
    return _taskDescription(task);
  }
  return task.title.isEmpty ? "等待主控 Agent 分配执行" : "等待执行：${task.title}";
}

String _compactTaskDetail(_AgentTaskProgress task) {
  final stage = task.currentStage.trim();
  if (stage.isNotEmpty) {
    return _truncateText(stage, 18);
  }
  final description = _taskDescription(task).trim();
  if (description.isNotEmpty) {
    return _truncateText(description, 18);
  }
  return switch (task.status) {
    "completed" => "已完成",
    "running" => "执行中",
    "failed" => "需处理",
    _ => "等待执行",
  };
}

String _executionStageLabel(String kind) {
  return switch (kind) {
    "started" => "启动",
    "thinking" => "规划",
    "tool" => "调用工具",
    "tool_success" => "工具完成",
    "tool_failed" => "工具失败",
    "finished" => "收尾",
    _ => "执行明细",
  };
}

List<_TimelineItem> _compactTimelineItems(List<_TimelineItem> items) {
  final output = <_TimelineItem>[];
  for (final item in items) {
    if (output.isNotEmpty && output.last.detail == item.detail) {
      output[output.length - 1] = item;
      continue;
    }
    output.add(item);
  }
  return output;
}

List<String> _uniqueRefs(Iterable<String> refs) {
  final output = <String>[];
  for (final ref in refs) {
    final normalized = ref.trim();
    if (normalized.isNotEmpty && !output.contains(normalized)) {
      output.add(normalized);
    }
  }
  return output;
}

List<_ExecutionTraceItem> _executionTraceItems(List<EventView> events) {
  final output = <_ExecutionTraceItem>[];
  final pendingTools = <_PendingToolOperation>[];
  final sorted = events
      .where((event) => _executionEventTypes.contains(event.type))
      .toList()
    ..sort((left, right) => left.createdAt.compareTo(right.createdAt));

  for (final event in sorted) {
    final payload = event.payload;
    switch (event.type) {
      case "run_started":
        output.add(
          _ExecutionTraceItem(
            kind: "started",
            title: "开始执行任务",
            detail: _truncateText(_payloadText(payload, "message"), 96),
            statusLabel: "已开始",
            icon: Icons.play_arrow_rounded,
            createdAt: event.createdAt,
          ),
        );
        break;
      case "assistant_thinking":
        final content = _payloadText(payload, "content");
        output.add(
          _ExecutionTraceItem(
            kind: "thinking",
            title: "模型正在规划",
            detail: _truncateText(content, 120),
            statusLabel: "规划中",
            icon: Icons.psychology_alt_outlined,
            createdAt: event.createdAt,
          ),
        );
        break;
      case "tool_call":
        final name = _payloadText(payload, "name", fallback: "unknown");
        pendingTools.add(
          _PendingToolOperation(
            toolCallId: _payloadText(payload, "tool_call_id"),
            name: name,
            action: _toolActionName(name),
            detail: _toolCallDetail(payload),
            createdAt: event.createdAt,
          ),
        );
        break;
      case "tool_result":
        final name = _payloadText(payload, "tool_name", fallback: "unknown");
        final success = payload["success"] == true;
        final pending = _takePendingToolOperation(
          pendingTools,
          toolCallId: _payloadText(payload, "tool_call_id"),
          name: name,
        );
        output.add(
          _toolExecutionTraceItem(
            pending ??
                _PendingToolOperation(
                  toolCallId: _payloadText(payload, "tool_call_id"),
                  name: name,
                  action: _toolActionName(name),
                  detail: "",
                  createdAt: event.createdAt,
                ),
            resultPayload: payload,
            success: success,
            finishedAt: event.createdAt,
          ),
        );
        break;
      case "run_finished":
        _flushPendingToolOperations(
          output,
          pendingTools,
          finishedAt: event.createdAt,
          assumeCompleted: true,
        );
        output.add(
          _ExecutionTraceItem(
            kind: "finished",
            title: "执行完成",
            detail: "正在整理最终回答和求职资产",
            statusLabel: "完成",
            icon: Icons.flag_outlined,
            createdAt: event.createdAt,
          ),
        );
        break;
    }
  }
  _flushPendingToolOperations(output, pendingTools);
  output.sort((left, right) => left.createdAt.compareTo(right.createdAt));
  return output;
}

_PendingToolOperation? _takePendingToolOperation(
  List<_PendingToolOperation> pendingTools, {
  required String toolCallId,
  required String name,
}) {
  if (toolCallId.isNotEmpty) {
    for (var index = pendingTools.length - 1; index >= 0; index--) {
      if (pendingTools[index].toolCallId == toolCallId) {
        return pendingTools.removeAt(index);
      }
    }
  }
  for (var index = pendingTools.length - 1; index >= 0; index--) {
    if (pendingTools[index].name == name) {
      return pendingTools.removeAt(index);
    }
  }
  return null;
}

void _flushPendingToolOperations(
  List<_ExecutionTraceItem> output,
  List<_PendingToolOperation> pendingTools, {
  DateTime? finishedAt,
  bool assumeCompleted = false,
}) {
  if (pendingTools.isEmpty) {
    return;
  }
  final pending = List<_PendingToolOperation>.from(pendingTools);
  pendingTools.clear();
  for (final item in pending) {
    output.add(
      _toolExecutionTraceItem(
        item,
        success: assumeCompleted ? true : null,
        finishedAt: finishedAt,
      ),
    );
  }
}

_ExecutionTraceItem _toolExecutionTraceItem(
  _PendingToolOperation pending, {
  Map<String, dynamic>? resultPayload,
  bool? success,
  DateTime? finishedAt,
}) {
  final completed = success == true;
  final failed = success == false;
  final resultDetail =
      resultPayload == null ? "" : _toolResultDetail(resultPayload);
  final detail = resultDetail.isNotEmpty ? resultDetail : pending.detail;
  return _ExecutionTraceItem(
    kind: failed
        ? "tool_failed"
        : completed
            ? "tool_success"
            : "tool",
    title: pending.action,
    detail: detail,
    statusLabel: failed
        ? "失败"
        : completed
            ? "已完成"
            : "运行中",
    durationLabel: _durationLabel(pending.createdAt, finishedAt),
    icon: failed
        ? Icons.error_outline_rounded
        : completed
            ? Icons.check_circle_outline_rounded
            : Icons.build_circle_outlined,
    createdAt: pending.createdAt,
  );
}

String _durationLabel(DateTime startedAt, DateTime? finishedAt) {
  if (finishedAt == null || finishedAt.isBefore(startedAt)) {
    return "";
  }
  final elapsed = finishedAt.difference(startedAt);
  if (elapsed.inMilliseconds < 1000) {
    return "耗时 <1 秒";
  }
  if (elapsed.inMinutes < 1) {
    return "耗时 ${elapsed.inSeconds} 秒";
  }
  final seconds = elapsed.inSeconds % 60;
  return "耗时 ${elapsed.inMinutes} 分 $seconds 秒";
}

List<_RunStage> _runStages(_RunProgressSnapshot snapshot) {
  if (snapshot.tasks.isEmpty) {
    return _genericExecutionStages(snapshot);
  }
  final resumeTask = _taskForAgent(snapshot, "resume_agent");
  final jobTask = _taskForAgent(snapshot, "job_agent");
  return [
    _RunStage(
      label: "读取资料",
      description: "定位简历、JD 和会话上下文",
      status: _fileStageStatus(snapshot),
      icon: Icons.folder_open_outlined,
    ),
    _RunStage(
      label: "简历诊断",
      description: _stageDescriptionFromTask(resumeTask, "提取画像与诊断信号"),
      status: _taskStageStatus(resumeTask),
      icon: Icons.badge_outlined,
    ),
    _RunStage(
      label: "岗位匹配",
      description: _stageDescriptionFromTask(jobTask, "分析 JD 并计算匹配点"),
      status: _taskStageStatus(jobTask),
      icon: Icons.fact_check_outlined,
    ),
    _RunStage(
      label: "报告生成",
      description: "整理匹配结论、风险和建议",
      status: _reportStageStatus(snapshot, jobTask),
      icon: Icons.summarize_outlined,
    ),
    _RunStage(
      label: "资产同步",
      description: "沉淀画像、报告和版本记录",
      status: _assetStageStatus(snapshot),
      icon: Icons.inventory_2_outlined,
    ),
  ];
}

List<_RunStage> _genericExecutionStages(_RunProgressSnapshot snapshot) {
  final toolStatus = _latestToolExecutionStatus(snapshot);
  final normalizedToolStatus =
      snapshot.status == "completed" && toolStatus != "failed"
          ? "completed"
          : toolStatus;
  return [
    _RunStage(
      label: "接收请求",
      description: "创建运行上下文",
      status: snapshot.executionItems.any((item) => item.kind == "started")
          ? "completed"
          : "running",
      icon: Icons.play_arrow_rounded,
    ),
    _RunStage(
      label: "执行工具",
      description: "读取资料或处理任务",
      status: normalizedToolStatus.isEmpty
          ? (snapshot.status == "completed" ? "completed" : "running")
          : normalizedToolStatus,
      icon: Icons.build_circle_outlined,
    ),
    _RunStage(
      label: "输出结果",
      description: "整理最终回答",
      status: snapshot.status == "completed" ? "completed" : "queued",
      icon: Icons.flag_outlined,
    ),
  ];
}

_AgentTaskProgress? _taskForAgent(
  _RunProgressSnapshot snapshot,
  String agentId,
) {
  for (final task in snapshot.tasks) {
    if (task.targetAgentId == agentId) {
      return task;
    }
  }
  return null;
}

String _taskStageStatus(_AgentTaskProgress? task) {
  return task?.status ?? "queued";
}

String _stageDescriptionFromTask(
  _AgentTaskProgress? task,
  String fallback,
) {
  if (task == null) {
    return fallback;
  }
  if (task.status == "completed") {
    return "已完成当前阶段";
  }
  if (task.status == "failed") {
    return _truncateText(_taskDescription(task), 36);
  }
  final text = task.currentAction.isNotEmpty
      ? task.currentAction
      : task.currentStage.isNotEmpty
          ? task.currentStage
          : task.title;
  return _truncateText(text.isEmpty ? fallback : text, 36);
}

String _fileStageStatus(_RunProgressSnapshot snapshot) {
  final latest = _latestExecutionStatusByTitle(
    snapshot,
    const [
      "读取文件内容",
      "搜索文件内容",
      "查看会话文件",
      "规划文件读取",
      "创建文本资料",
    ],
  );
  if (latest.isNotEmpty) {
    return latest == "running" && snapshot.tasks.isNotEmpty
        ? "completed"
        : latest;
  }
  if (snapshot.tasks.isNotEmpty || snapshot.status == "completed") {
    return "completed";
  }
  return "running";
}

String _reportStageStatus(
  _RunProgressSnapshot snapshot,
  _AgentTaskProgress? jobTask,
) {
  final latest = _latestExecutionStatusByTitle(
    snapshot,
    const [
      "保存岗位匹配报告",
      "生成简历版本",
      "发布用户可见文件",
    ],
  );
  if (latest.isNotEmpty) {
    return latest;
  }
  if (jobTask?.status == "failed") {
    return "failed";
  }
  if (snapshot.status == "completed" && jobTask?.status == "completed") {
    return "completed";
  }
  final jobDescription = jobTask == null ? "" : _taskDescription(jobTask);
  if (jobTask?.status == "running" &&
      (jobDescription.contains("报告") || jobDescription.contains("匹配"))) {
    return "running";
  }
  return "queued";
}

String _assetStageStatus(_RunProgressSnapshot snapshot) {
  if (snapshot.status == "completed") {
    return "completed";
  }
  if (snapshot.status == "failed" || snapshot.status == "partial_failed") {
    return snapshot.status;
  }
  final latest = _latestExecutionStatusByTitle(
    snapshot,
    const [
      "保存岗位匹配报告",
      "更新职业画像",
      "生成简历版本",
      "发布用户可见文件",
    ],
  );
  if (latest == "failed") {
    return "failed";
  }
  if (latest == "running" || latest == "completed") {
    return "running";
  }
  return "queued";
}

String _latestExecutionStatusByTitle(
  _RunProgressSnapshot snapshot,
  List<String> tokens,
) {
  for (final item in snapshot.executionItems.reversed) {
    if (!tokens.any((token) => item.title.contains(token))) {
      continue;
    }
    return switch (item.kind) {
      "tool_failed" => "failed",
      "tool" || "thinking" || "started" => "running",
      "tool_success" || "finished" => "completed",
      _ => "",
    };
  }
  return "";
}

String _latestToolExecutionStatus(_RunProgressSnapshot snapshot) {
  for (final item in snapshot.executionItems.reversed) {
    if (!item.kind.startsWith("tool")) {
      continue;
    }
    return switch (item.kind) {
      "tool_failed" => "failed",
      "tool_success" => "completed",
      "tool" => "running",
      _ => "",
    };
  }
  return "";
}

String _toolCallDetail(Map<String, dynamic> payload) {
  final currentAction = _payloadText(payload, "current_action");
  if (currentAction.isNotEmpty) {
    return _truncateText(currentAction, 120);
  }
  final arguments = payload["arguments"];
  if (arguments is Map && arguments.isNotEmpty) {
    final keys =
        arguments.keys.map((key) => key.toString()).take(3).join(" / ");
    return keys.isEmpty ? "" : "参数：$keys";
  }
  return "";
}

String _toolResultDetail(Map<String, dynamic> payload) {
  final detail = _payloadText(payload, "current_action");
  if (detail.isNotEmpty) {
    return _truncateText(detail, 120);
  }
  final summary = _payloadText(payload, "summary");
  if (summary.isNotEmpty) {
    return _truncateText(summary, 120);
  }
  final error = _payloadText(payload, "error");
  if (error.isNotEmpty) {
    return _truncateText(error, 120);
  }
  return "";
}

String _toolActionName(String name) {
  return switch (name) {
    "delegate_agents" => "委派协作 Agent",
    "agent_task_status" => "检查协作任务状态",
    "session_list_artifacts" => "查看会话文件",
    "session_plan_artifact_access" => "规划文件读取",
    "session_read_artifact" => "读取文件内容",
    "session_search_artifact" => "搜索文件内容",
    "session_create_text_artifact" => "创建文本资料",
    "publish_artifact" => "发布用户可见文件",
    "workspace_read_file" => "读取工作区文件",
    "workspace_write_file" => "写入工作区文件",
    "career_resume_profile_save" => "保存简历画像",
    "career_resume_profile_get" => "读取简历画像",
    "career_resume_profile_list" => "查看简历画像",
    "career_profile_get" => "读取职业画像",
    "career_profile_merge" => "更新职业画像",
    "career_jd_analysis_save" => "保存 JD 分析",
    "career_jd_analysis_get" => "读取 JD 分析",
    "career_jd_analysis_list" => "查看 JD 分析",
    "career_job_fit_report_save" => "保存岗位匹配报告",
    "career_job_fit_report_get" => "读取岗位匹配报告",
    "career_job_fit_report_list" => "查看岗位匹配报告",
    "career_resume_version_create" => "生成简历版本",
    "career_resume_version_get" => "读取简历版本",
    "career_resume_version_list" => "查看简历版本",
    "memory_search" => "检索记忆",
    "memory_write" => "写入记忆",
    "memory_update" => "更新记忆",
    "memory_forget" => "删除记忆",
    "memory_inspect" => "查看记忆详情",
    "memory_explain" => "解释记忆命中",
    "state_set" => "记录临时状态",
    "state_publish" => "发布状态",
    "state_list" => "查看状态",
    _ => _fallbackToolActionName(name),
  };
}

String _fallbackToolActionName(String name) {
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

Color _executionTraceColor(String kind) {
  return switch (kind) {
    "tool_failed" => AppTheme.danger,
    "tool_success" || "finished" => AppTheme.accentHover,
    "tool" => const Color(0xFF2563EB),
    "thinking" => const Color(0xFF7C3AED),
    _ => AppTheme.textTertiary,
  };
}

String _compactProgressText({
  required String title,
  required String detail,
  required String fallback,
  required int maxLength,
}) {
  final normalizedTitle = _normalizeProgressText(title);
  final normalizedDetail = _normalizeProgressText(detail);
  if (normalizedTitle.isEmpty && normalizedDetail.isEmpty) {
    return fallback;
  }
  if (normalizedDetail.isEmpty) {
    return _truncateText(normalizedTitle, maxLength);
  }
  if (normalizedTitle.isEmpty) {
    return _truncateText(normalizedDetail, maxLength);
  }
  final detailLooksVerbose =
      normalizedDetail.length > maxLength || detail.contains("\n");
  if (detailLooksVerbose || normalizedDetail.contains(normalizedTitle)) {
    return _truncateText(normalizedTitle, maxLength);
  }
  return _truncateText("$normalizedTitle：$normalizedDetail", maxLength);
}

String _normalizeProgressText(String value) {
  return value.trim().replaceAll(RegExp(r"\s+"), " ");
}

String _truncateText(String value, int maxLength) {
  if (value.length <= maxLength) {
    return value;
  }
  if (maxLength <= 1) {
    return value.substring(0, maxLength);
  }
  return "${value.substring(0, maxLength - 1)}…";
}

String _titleForStatus(String status) {
  return switch (status) {
    "completed" => "多 Agent 协作已完成",
    "failed" => "多 Agent 协作失败",
    "partial_failed" => "多 Agent 协作部分失败",
    _ => "多 Agent 协作执行中",
  };
}

String _statusLabel(String status) {
  return switch (status) {
    "queued" || "pending" => "等待中",
    "running" => "运行中",
    "completed" => "已完成",
    "failed" => "失败",
    "partial_failed" => "部分失败",
    "cancelled" => "已取消",
    "archived" => "已归档",
    _ => status,
  };
}

Color _statusColor(String status) {
  return switch (status) {
    "running" => AppTheme.accent,
    "completed" => AppTheme.accentHover,
    "failed" || "partial_failed" => AppTheme.danger,
    _ => AppTheme.textTertiary,
  };
}

IconData _statusIcon(String status) {
  return switch (status) {
    "completed" => Icons.check_rounded,
    "failed" || "partial_failed" => Icons.warning_amber_rounded,
    "queued" || "pending" => Icons.schedule_rounded,
    "cancelled" => Icons.block_rounded,
    _ => Icons.account_tree_rounded,
  };
}

bool _isTerminalTaskStatus(String status) {
  return status == "completed" || status == "failed" || status == "cancelled";
}

IconData _agentIcon(String agentId) {
  if (agentId == "resume_agent") {
    return Icons.badge_outlined;
  }
  if (agentId == "job_agent") {
    return Icons.article_outlined;
  }
  return Icons.smart_toy_outlined;
}

String _agentDisplayName(String agentId) {
  return switch (agentId) {
    "resume_agent" => "简历分析 Agent",
    "job_agent" => "岗位匹配 Agent",
    "agent_main" => "主控 Agent",
    _ => agentId,
  };
}

String _agentRoleLabel(String agentId) {
  return switch (agentId) {
    "resume_agent" => "简历解析 · 画像沉淀 · 诊断报告",
    "job_agent" => "JD 分析 · 匹配评估 · 报告生成",
    "agent_main" => "任务编排 · 结果汇总 · 产品记录",
    _ => "执行子任务",
  };
}

String _referenceLabel(String value) {
  if (value.startsWith("artifact_")) {
    return "文件 ${_refSuffix(value)}";
  }
  if (value.startsWith("resume_profile_")) {
    return "简历画像 ${_refSuffix(value)}";
  }
  if (value.startsWith("career_profile_")) {
    return "职业画像";
  }
  if (value.startsWith("jd_")) {
    return "JD 分析 ${_refSuffix(value)}";
  }
  if (value.startsWith("fit_")) {
    return "匹配报告 ${_refSuffix(value)}";
  }
  if (value.startsWith("resume_version_")) {
    return "简历版本 ${_refSuffix(value)}";
  }
  return _truncateText(value, 24);
}

String _refSuffix(String value) {
  final parts = value.split("_").where((part) => part.isNotEmpty).toList();
  final suffix = parts.isEmpty ? value : parts.last;
  if (suffix.length <= 8) return suffix;
  return suffix.substring(suffix.length - 8);
}

String _payloadText(
  Map<String, dynamic> payload,
  String key, {
  String fallback = "",
}) {
  final raw = payload[key];
  if (raw == null) return fallback;
  final text = raw.toString().trim();
  return text.isEmpty ? fallback : text;
}

List<String> _payloadStringList(Object? raw, List<String>? fallback) {
  if (raw is! List) {
    return fallback == null ? const [] : List.unmodifiable(fallback);
  }
  final output = <String>[];
  for (final item in raw) {
    final value = item.toString().trim();
    if (value.isNotEmpty && !output.contains(value)) {
      output.add(value);
    }
  }
  return output;
}

int _payloadInt(Object? raw, int fallback) {
  if (raw is int) return raw;
  if (raw is num) return raw.toInt();
  if (raw is String) return int.tryParse(raw.trim()) ?? fallback;
  return fallback;
}

List<String> _mergePayloadStringLists(List<String>? previous, Object? raw) {
  final output = <String>[...?previous];
  if (raw is! List) {
    return output;
  }
  for (final item in raw) {
    final value = item.toString().trim();
    if (value.isNotEmpty && !output.contains(value)) {
      output.add(value);
    }
  }
  return output;
}

String _stageLabel(String stage) {
  return switch (stage) {
    "started" => "启动中",
    "context" => "读取上下文",
    "planning" => "规划中",
    "tool_call" => "调用工具",
    "tool_result" => "处理工具结果",
    "summary" => "汇总结果",
    "finished" => "等待主流程汇总",
    _ => stage,
  };
}
