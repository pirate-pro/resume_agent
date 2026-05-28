import 'package:flutter/material.dart';

import '../../../core/models/api_models.dart';
import '../../../shared/theme/app_theme.dart';
import '../../../shared/theme/product_tokens.dart';
import '../../../shared/widgets/product_components.dart';

Future<String?> showLearningCheckinSheet(
  BuildContext context, {
  required CareerWorkbenchLearningTaskView task,
}) {
  final summaryController = TextEditingController();
  final blockersController = TextEditingController();
  final nextActionController = TextEditingController();
  final minutesController = TextEditingController();
  var nextState = '';
  var error = '';
  String? detail;

  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    builder: (sheetContext) {
      return StatefulBuilder(
        builder: (context, setSheetState) {
          void submit() {
            final summary = summaryController.text.trim();
            final blockers = blockersController.text.trim();
            final nextAction = nextActionController.text.trim();
            if (summary.isEmpty && blockers.isEmpty && nextAction.isEmpty) {
              setSheetState(() => error = '至少填写一项进展、卡点或下一步');
              return;
            }
            final rawMinutes = minutesController.text.trim();
            final minutes = rawMinutes.isEmpty
                ? 0
                : int.tryParse(
                      rawMinutes.replaceAll(RegExp(r'[^0-9]'), ''),
                    ) ??
                    0;
            detail = _learningCheckinDetail(
              task: task,
              summary: summary,
              blockers: blockers,
              nextAction: nextAction,
              minutes: minutes,
              nextState: nextState,
            );
            Navigator.of(sheetContext).pop();
          }

          final bottom = MediaQuery.viewInsetsOf(context).bottom;
          return SafeArea(
            top: false,
            child: Padding(
              padding: EdgeInsets.fromLTRB(12, 0, 12, 12 + bottom),
              child: Align(
                alignment: Alignment.bottomCenter,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 760),
                  child: Container(
                    decoration: AppTheme.floatingPanelDecoration(
                      radius: 24,
                      alpha: 0.98,
                    ),
                    clipBehavior: Clip.antiAlias,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const ProductIconTile(
                                icon: Icons.fact_check_outlined,
                                tone: ProductTone.info,
                                size: 36,
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '记录学习进度',
                                      style: AppTheme.ts(
                                        fontSize: 15,
                                        fontWeight: FontWeight.w900,
                                        color: ProductColors.text,
                                      ),
                                    ),
                                    const SizedBox(height: 3),
                                    Text(
                                      '先填写本次 check-in；Agent 只负责按内容写入，不会凭空判断进度。',
                                      style: AppTheme.ts(
                                        fontSize: 11.2,
                                        color: ProductColors.textMuted,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              IconButton(
                                tooltip: '关闭',
                                onPressed: () =>
                                    Navigator.of(sheetContext).pop(),
                                icon: const Icon(Icons.close_rounded),
                                color: ProductColors.textSecondary,
                              ),
                            ],
                          ),
                          const SizedBox(height: 14),
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                            decoration: BoxDecoration(
                              color: ProductColors.primarySoft
                                  .withValues(alpha: 0.7),
                              borderRadius: BorderRadius.circular(14),
                              border: Border.all(
                                color: ProductColors.primary
                                    .withValues(alpha: 0.14),
                              ),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  task.title.trim().isEmpty
                                      ? '未命名学习任务'
                                      : task.title.trim(),
                                  maxLines: 2,
                                  overflow: TextOverflow.ellipsis,
                                  style: AppTheme.ts(
                                    fontSize: 12.6,
                                    fontWeight: FontWeight.w900,
                                    color: ProductColors.text,
                                  ),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  '当前状态：${_taskStateLabel(task.state)} · ${task.learningTaskId}',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: AppTheme.ts(
                                    fontSize: 11,
                                    color: ProductColors.textMuted,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 12),
                          TextField(
                            key: const Key('learning_checkin_summary_field'),
                            controller: summaryController,
                            minLines: 2,
                            maxLines: 4,
                            textInputAction: TextInputAction.newline,
                            decoration: _inputDecoration('今天完成了什么'),
                            style: AppTheme.ts(
                              fontSize: 12.6,
                              height: 1.48,
                              color: ProductColors.text,
                            ),
                          ),
                          const SizedBox(height: 10),
                          LayoutBuilder(
                            builder: (context, constraints) {
                              final blockersField = TextField(
                                key: const Key(
                                  'learning_checkin_blockers_field',
                                ),
                                controller: blockersController,
                                minLines: 2,
                                maxLines: 3,
                                textInputAction: TextInputAction.newline,
                                decoration: _inputDecoration('当前卡点（可选）'),
                                style: AppTheme.ts(
                                  fontSize: 12.6,
                                  height: 1.48,
                                  color: ProductColors.text,
                                ),
                              );
                              final nextField = TextField(
                                key: const Key(
                                  'learning_checkin_next_action_field',
                                ),
                                controller: nextActionController,
                                minLines: 2,
                                maxLines: 3,
                                textInputAction: TextInputAction.newline,
                                decoration: _inputDecoration('下一步（可选）'),
                                style: AppTheme.ts(
                                  fontSize: 12.6,
                                  height: 1.48,
                                  color: ProductColors.text,
                                ),
                              );
                              if (constraints.maxWidth < 620) {
                                return Column(
                                  children: [
                                    blockersField,
                                    const SizedBox(height: 10),
                                    nextField,
                                  ],
                                );
                              }
                              return Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Expanded(child: blockersField),
                                  const SizedBox(width: 10),
                                  Expanded(child: nextField),
                                ],
                              );
                            },
                          ),
                          const SizedBox(height: 10),
                          LayoutBuilder(
                            builder: (context, constraints) {
                              final stateSelector = _CheckinChoiceGroup(
                                label: '状态变化',
                                value: nextState,
                                options: const [
                                  _CheckinChoice('', '不变'),
                                  _CheckinChoice('doing', '进行中'),
                                  _CheckinChoice('blocked', '受阻'),
                                  _CheckinChoice('done', '完成'),
                                ],
                                onChanged: (value) =>
                                    setSheetState(() => nextState = value),
                              );
                              final minutesField = TextField(
                                key: const Key(
                                  'learning_checkin_minutes_field',
                                ),
                                controller: minutesController,
                                keyboardType: TextInputType.number,
                                decoration: _inputDecoration('投入分钟数'),
                                style: AppTheme.ts(
                                  fontSize: 12.6,
                                  color: ProductColors.text,
                                ),
                              );
                              if (constraints.maxWidth < 560) {
                                return Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    stateSelector,
                                    const SizedBox(height: 10),
                                    minutesField,
                                  ],
                                );
                              }
                              return Row(
                                crossAxisAlignment: CrossAxisAlignment.end,
                                children: [
                                  Expanded(child: stateSelector),
                                  const SizedBox(width: 10),
                                  SizedBox(width: 180, child: minutesField),
                                ],
                              );
                            },
                          ),
                          if (error.isNotEmpty) ...[
                            const SizedBox(height: 10),
                            Text(
                              error,
                              style: AppTheme.ts(
                                fontSize: 11.5,
                                fontWeight: FontWeight.w900,
                                color: ProductColors.danger,
                              ),
                            ),
                          ],
                          const SizedBox(height: 16),
                          Row(
                            mainAxisAlignment: MainAxisAlignment.end,
                            children: [
                              TextButton(
                                onPressed: () =>
                                    Navigator.of(sheetContext).pop(),
                                child: const Text('取消'),
                              ),
                              const SizedBox(width: 8),
                              FilledButton.icon(
                                onPressed: submit,
                                icon: const Icon(
                                  Icons.arrow_forward_rounded,
                                  size: 16,
                                ),
                                label: const Text('交给 Agent 写入'),
                                style: FilledButton.styleFrom(
                                  backgroundColor: ProductColors.primary,
                                  foregroundColor: Colors.white,
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                ),
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
        },
      );
    },
  ).whenComplete(() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      summaryController.dispose();
      blockersController.dispose();
      nextActionController.dispose();
      minutesController.dispose();
    });
  }).then((_) => detail);
}

class _CheckinChoice {
  final String value;
  final String label;

  const _CheckinChoice(this.value, this.label);
}

class _CheckinChoiceGroup extends StatelessWidget {
  final String label;
  final String value;
  final List<_CheckinChoice> options;
  final ValueChanged<String> onChanged;

  const _CheckinChoiceGroup({
    required this.label,
    required this.value,
    required this.options,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: AppTheme.ts(
            fontSize: 11,
            fontWeight: FontWeight.w900,
            color: ProductColors.textMuted,
          ),
        ),
        const SizedBox(height: 7),
        Wrap(
          spacing: 7,
          runSpacing: 7,
          children: [
            for (final option in options)
              _CheckinChoicePill(
                label: option.label,
                selected: option.value == value,
                onTap: () => onChanged(option.value),
              ),
          ],
        ),
      ],
    );
  }
}

class _CheckinChoicePill extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _CheckinChoicePill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final tone = selected ? ProductTone.primary : ProductTone.neutral;
    final style = productToneStyle(tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: style.soft.withValues(alpha: selected ? 0.9 : 0.56),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: style.color.withValues(alpha: selected ? 0.24 : 0.12),
            ),
          ),
          child: Text(
            label,
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w900,
              color: style.color,
            ),
          ),
        ),
      ),
    );
  }
}

InputDecoration _inputDecoration(String label) {
  return InputDecoration(
    labelText: label,
    filled: true,
    fillColor: ProductColors.surface,
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: ProductColors.border),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: ProductColors.border),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: ProductColors.primary, width: 1.2),
    ),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
    labelStyle: AppTheme.ts(fontSize: 12, color: ProductColors.textMuted),
  );
}

String _learningCheckinDetail({
  required CareerWorkbenchLearningTaskView task,
  required String summary,
  required String blockers,
  required String nextAction,
  required int minutes,
  required String nextState,
}) {
  return '''
请记录学习任务今日进度。

任务信息：
- learning_task_id: ${task.learningTaskId}
- title: ${task.title}
- current_state: ${task.state}

进度内容：
${summary.trim().isEmpty ? "" : "- summary: ${summary.trim()}\n"}${blockers.trim().isEmpty ? "" : "- blockers: ${blockers.trim()}\n"}${nextAction.trim().isEmpty ? "" : "- next_action: ${nextAction.trim()}\n"}${minutes <= 0 ? "" : "- minutes_spent: $minutes\n"}${nextState.trim().isEmpty ? "- state_change: 不变\n" : "- state_change: $nextState\n"}
执行要求：
1. 先读取并定位该 LearningTask。
2. 调用 learning_checkin_create 记录本次进度。
3. 只有 state_change 不是“不变”时，才调用 learning_task_update_state。
4. 不要自动写 Note、CareerApplication、WeaknessTracker 或 memory。
''';
}

String _taskStateLabel(String state) {
  return switch (state.trim()) {
    'todo' => '待办',
    'doing' || 'in_progress' => '进行中',
    'done' || 'completed' => '已完成',
    'blocked' => '受阻',
    'cancelled' => '已取消',
    _ => '待推进',
  };
}
