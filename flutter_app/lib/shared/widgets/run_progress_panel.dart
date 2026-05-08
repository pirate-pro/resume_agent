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

class RunProgressPanel extends StatefulWidget {
  final List<EventView> events;

  const RunProgressPanel({super.key, required this.events});

  static bool hasProgress(List<EventView> events) {
    return events.any((event) => _agentTaskEventTypes.contains(event.type));
  }

  @override
  State<RunProgressPanel> createState() => _RunProgressPanelState();
}

class _RunProgressPanelState extends State<RunProgressPanel> {
  bool _expanded = true;

  @override
  Widget build(BuildContext context) {
    final snapshot = _RunProgressSnapshot.fromEvents(widget.events);
    if (snapshot.tasks.isEmpty) {
      return const SizedBox.shrink();
    }

    final runningCount =
        snapshot.tasks.where((task) => task.status == "running").length;
    final waitingCount = snapshot.tasks
        .where((task) => task.status == "queued" || task.status == "pending")
        .length;
    final completedCount =
        snapshot.tasks.where((task) => task.status == "completed").length;
    final failedCount =
        snapshot.tasks.where((task) => task.status == "failed").length;
    final summaryParts = [
      "${snapshot.tasks.length} 个 agent",
      if (runningCount > 0) "$runningCount 运行中",
      if (waitingCount > 0) "$waitingCount 等待中",
      if (completedCount > 0) "$completedCount 已完成",
      if (failedCount > 0) "$failedCount 失败",
    ];

    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: AppTheme.surface.withValues(alpha: AppTheme.isDark ? 0.62 : 0.7),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.86)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InkWell(
            borderRadius: BorderRadius.circular(10),
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
              child: Row(
                children: [
                  Container(
                    width: 24,
                    height: 24,
                    decoration: BoxDecoration(
                      color: AppTheme.accent.withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(
                      _expanded
                          ? Icons.expand_more_rounded
                          : Icons.chevron_right_rounded,
                      size: 16,
                      color: AppTheme.accent,
                    ),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _titleForStatus(snapshot.status),
                          style: AppTheme.ts(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w700,
                            color: AppTheme.textPrimary,
                          ),
                        ),
                        const SizedBox(height: 2),
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
                  _StatusBadge(status: snapshot.status),
                ],
              ),
            ),
          ),
          if (_expanded) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: Column(
                children: [
                  for (final task in snapshot.tasks) ...[
                    _AgentTaskCard(task: task),
                    if (task != snapshot.tasks.last) const SizedBox(height: 8),
                  ],
                  const SizedBox(height: 10),
                  _RunProgressFooter(snapshot: snapshot),
                ],
              ),
            ),
          ],
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
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppTheme.bg.withValues(alpha: AppTheme.isDark ? 0.24 : 0.4),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: AppTheme.border.withValues(alpha: 0.82)),
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
                  color: _statusColor(task.status).withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  _agentIcon(task.targetAgentId),
                  size: 15,
                  color: _statusColor(task.status),
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            task.targetAgentId,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        _StatusBadge(status: task.status),
                      ],
                    ),
                    const SizedBox(height: 4),
                    if (taskDescription.isNotEmpty)
                      Text(
                        taskDescription,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11,
                          height: 1.35,
                          color: AppTheme.textTertiary,
                        ),
                      ),
                    if (task.currentStage.isNotEmpty) ...[
                      const SizedBox(height: 7),
                      _StageChip(label: task.currentStage),
                    ],
                  ],
                ),
              ),
            ],
          ),
          if (task.status == "running") ...[
            const SizedBox(height: 9),
            ClipRRect(
              borderRadius: BorderRadius.circular(999),
              child: LinearProgressIndicator(
                minHeight: 2,
                color: AppTheme.accent,
                backgroundColor: AppTheme.accent.withValues(alpha: 0.12),
              ),
            ),
          ],
          if (task.timeline.isNotEmpty) ...[
            const SizedBox(height: 10),
            _AgentTaskTimeline(items: task.timeline),
          ],
          if (task.artifactRefs.isNotEmpty) ...[
            const SizedBox(height: 8),
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
    return Column(
      children: [
        for (final item in visibleItems)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Container(
                    width: 7,
                    height: 7,
                    decoration: BoxDecoration(
                      color: _statusColor(item.status),
                      shape: BoxShape.circle,
                      boxShadow: item.status == "running"
                          ? [
                              BoxShadow(
                                color: AppTheme.accent.withValues(alpha: 0.28),
                                blurRadius: 8,
                                spreadRadius: 1,
                              ),
                            ]
                          : const [],
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Text(
                  DateFormat("HH:mm:ss").format(item.createdAt),
                  style:
                      AppTheme.ts(fontSize: 10.5, color: AppTheme.textTertiary),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    item.detail,
                    style: AppTheme.ts(
                      fontSize: 11,
                      height: 1.35,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _RunProgressFooter extends StatelessWidget {
  final _RunProgressSnapshot snapshot;

  const _RunProgressFooter({required this.snapshot});

  @override
  Widget build(BuildContext context) {
    final text = switch (snapshot.status) {
      "completed" => "已完成，可在右侧求职资产中查看结果",
      "failed" => "任务失败，请查看失败 agent 的错误信息",
      "partial_failed" => "部分任务失败，已保留成功产物",
      _ => "完成后将刷新右侧求职资产",
    };
    return Row(
      children: [
        Icon(Icons.sync_rounded, size: 13, color: AppTheme.textTertiary),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            text,
            style: AppTheme.ts(fontSize: 11, color: AppTheme.textTertiary),
          ),
        ),
      ],
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final String status;

  const _StatusBadge({required this.status});

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        _statusLabel(status),
        style: AppTheme.ts(
          fontSize: 10.5,
          fontWeight: FontWeight.w700,
          color: color,
        ),
      ),
    );
  }
}

class _StageChip extends StatelessWidget {
  final String label;

  const _StageChip({required this.label});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
      decoration: BoxDecoration(
        color: AppTheme.accent.withValues(alpha: 0.09),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: AppTheme.accent.withValues(alpha: 0.16)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 7,
            height: 7,
            child: CircularProgressIndicator(
              strokeWidth: 1.4,
              color: AppTheme.accent,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            label,
            style: AppTheme.ts(
              fontSize: 10.5,
              fontWeight: FontWeight.w700,
              color: AppTheme.accent,
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
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        for (final value in values.take(4))
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
            decoration: BoxDecoration(
              color: AppTheme.surface.withValues(alpha: 0.62),
              borderRadius: BorderRadius.circular(7),
              border: Border.all(color: AppTheme.border),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 11, color: AppTheme.textTertiary),
                const SizedBox(width: 4),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 160),
                  child: Text(
                    value,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 10.5,
                      color: AppTheme.textSecondary,
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _RunProgressSnapshot {
  final String status;
  final List<_AgentTaskProgress> tasks;

  const _RunProgressSnapshot({required this.status, required this.tasks});

  factory _RunProgressSnapshot.fromEvents(List<EventView> events) {
    final filtered = events
        .where((event) => _agentTaskEventTypes.contains(event.type))
        .toList()
      ..sort((left, right) => left.createdAt.compareTo(right.createdAt));
    String status = "running";
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
    );
  }
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
    required this.artifactRefs,
    required this.productRefs,
    required this.timeline,
  });

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
  return _compactProgressText(
    title: task.title,
    detail: task.detail,
    fallback: task.status == "running" ? "正在处理任务" : "等待执行",
    maxLength: 92,
  );
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
    "completed" => "求职任务已完成",
    "failed" => "求职任务失败",
    "partial_failed" => "求职任务部分失败",
    _ => "求职任务执行中",
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
