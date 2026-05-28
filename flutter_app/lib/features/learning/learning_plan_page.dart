import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import '../../shared/widgets/product_components.dart';
import '../career_ui/career_ui_helpers.dart';
import '../career_workbench/career_workbench_provider.dart';
import 'widgets/learning_checkin_sheet.dart';

class LearningPlanPage extends ConsumerStatefulWidget {
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenNotes;
  final CareerPromptSender? onSendPrompt;

  const LearningPlanPage({
    super.key,
    required this.onOpenProjects,
    required this.onOpenNotes,
    this.onSendPrompt,
  });

  @override
  ConsumerState<LearningPlanPage> createState() => _LearningPlanPageState();
}

class _LearningPlanPageState extends ConsumerState<LearningPlanPage> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() => ref.read(careerWorkbenchProvider).ensureLoaded());
  }

  @override
  Widget build(BuildContext context) {
    final provider = ref.watch(careerWorkbenchProvider);
    if (provider.isLoading && !provider.hasLoaded) {
      return const Center(
        child: CircularProgressIndicator(color: ProductColors.primary),
      );
    }
    if (provider.error != null && !provider.hasLoaded) {
      return _LearningError(
        error: provider.error!,
        onRetry: () => unawaited(provider.refresh()),
      );
    }

    final summary = provider.selectedApplicationSummary;
    final detail = provider.selectedApplicationDetail;
    final app = detail?.application ?? summary?.application;
    final learning = detail?.learning ?? _emptyLearning();
    final tasks = _sortedTasks(learning.tasks);
    final openTasks = tasks.where(_isOpenTask).toList();
    final doneTasks = tasks.where(_isDoneTask).toList();
    final progress = _progressPercent(openTasks.length, doneTasks.length);
    final loadingSelected = app != null && detail == null;

    return LayoutBuilder(
      builder: (context, constraints) {
        final desktop = constraints.maxWidth >= ProductBreakpoints.contentRail;
        final header = _LearningHeader(
          provider: provider,
          onRefresh: () => unawaited(provider.refresh()),
          onCreateTask: () => _sendCreateTask(app),
          onRecommend: () => _sendRecommend(learning, app),
        );
        final hero = _LearningHero(
          app: app,
          learning: learning,
          progress: progress,
          loading: loadingSelected,
          onPrimary: () => _sendRecommend(learning, app),
        );
        final projects = _LearningProjectStrip(
          provider: provider,
          selectedId: app?.applicationId,
        );
        final metrics = _LearningMetricStrip(
          learning: learning,
          openTaskCount: openTasks.length,
          doneTaskCount: doneTasks.length,
          progress: progress,
        );
        final main = ListView(
          padding: EdgeInsets.zero,
          children: [
            header,
            const SizedBox(height: 14),
            hero,
            const SizedBox(height: 14),
            projects,
            const SizedBox(height: 14),
            metrics,
            const SizedBox(height: 14),
            _LearningPlanSection(plans: learning.plans),
            const SizedBox(height: 14),
            _LearningTaskBoard(
              tasks: tasks,
              onCheckIn: (task) => _showCheckInSheet(app, task),
              onCreateTask: () => _sendCreateTask(app),
            ),
            const SizedBox(height: 14),
            _LearningWeaknessSection(
              weaknesses: learning.weaknesses,
              tasks: tasks,
              onCreateTask: () => _sendCreateTask(app),
            ),
            const SizedBox(height: 14),
            _LearningReviewSection(reviews: learning.reviews),
          ],
        );
        final rail = _LearningRightRail(
          provider: provider,
          app: app,
          learning: learning,
          openTasks: openTasks,
          onOpenProjects: widget.onOpenProjects,
          onOpenNotes: widget.onOpenNotes,
          onCreateTask: () => _sendCreateTask(app),
          onRecommend: () => _sendRecommend(learning, app),
        );

        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              header,
              const SizedBox(height: 14),
              hero,
              const SizedBox(height: 14),
              projects,
              const SizedBox(height: 14),
              rail,
              const SizedBox(height: 14),
              metrics,
              const SizedBox(height: 14),
              _LearningPlanSection(plans: learning.plans),
              const SizedBox(height: 14),
              _LearningTaskBoard(
                tasks: tasks,
                onCheckIn: (task) => _showCheckInSheet(app, task),
                onCreateTask: () => _sendCreateTask(app),
              ),
              const SizedBox(height: 14),
              _LearningWeaknessSection(
                weaknesses: learning.weaknesses,
                tasks: tasks,
                onCreateTask: () => _sendCreateTask(app),
              ),
              const SizedBox(height: 14),
              _LearningReviewSection(reviews: learning.reviews),
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: main),
            const SizedBox(width: 18),
            SizedBox(width: 350, child: ListView(children: [rail])),
          ],
        );
      },
    );
  }

  void _sendRecommend(
    CareerLearningSummaryView learning,
    CareerApplicationView? app,
  ) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '生成学习任务建议',
      actionType: 'learning_recommend',
      origin: 'learning_plan',
      detail:
          '请复用当前匹配报告、短板、复盘和已有任务，推荐 1 到 3 个最值得推进的学习任务。当前已有计划 ${learning.plans.length} 个、任务 ${learning.tasks.length} 个、短板 ${learning.weaknesses.length} 个。',
    );
  }

  void _sendCreateTask(CareerApplicationView? app) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '创建学习任务',
      actionType: 'learning_task',
      origin: 'learning_plan',
      detail: '请基于当前岗位要求和最高优先级短板创建一个可执行的学习任务，不要重复创建已有相似任务。',
    );
  }

  Future<void> _showCheckInSheet(
    CareerApplicationView? app,
    CareerWorkbenchLearningTaskView task,
  ) async {
    if (app == null) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        const SnackBar(
          content: Text('请先选择一个求职项目'),
          duration: Duration(seconds: 1),
        ),
      );
      return;
    }
    final detail = await showLearningCheckinSheet(context, task: task);
    if (!mounted || detail == null) return;
    _sendCheckInIntent(app, detail);
  }

  void _sendCheckInIntent(CareerApplicationView app, String detail) {
    sendCareerPromptAction(
      sender: widget.onSendPrompt,
      application: app,
      label: '记录学习进度',
      actionType: 'learning_checkin',
      origin: 'learning_plan',
      detail: detail,
    );
  }
}

class _LearningHeader extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final VoidCallback onRefresh;
  final VoidCallback onCreateTask;
  final VoidCallback onRecommend;

  const _LearningHeader({
    required this.provider,
    required this.onRefresh,
    required this.onCreateTask,
    required this.onRecommend,
  });

  @override
  Widget build(BuildContext context) {
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final title = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 8,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  Text(
                    '学习计划',
                    style: AppTheme.ts(
                      fontSize: 22,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  const ProductTag(
                    label: '补短板',
                    tone: ProductTone.purple,
                    icon: Icons.school_outlined,
                  ),
                  if (provider.isRefreshing)
                    const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: ProductColors.primary,
                      ),
                    ),
                ],
              ),
              const SizedBox(height: 5),
              Text(
                '把岗位差距拆成今天能推进的学习任务，持续提升面试准备度。',
                maxLines: compact ? 2 : 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 12.5,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          );
          final controls = Wrap(
            spacing: 8,
            runSpacing: 8,
            alignment: WrapAlignment.end,
            children: [
              SizedBox(
                height: 38,
                child: OutlinedButton.icon(
                  onPressed: onRefresh,
                  icon: const Icon(Icons.refresh_rounded, size: 16),
                  label: const Text('刷新'),
                  style: _outlineButtonStyle(),
                ),
              ),
              SizedBox(
                height: 38,
                child: OutlinedButton.icon(
                  onPressed: onRecommend,
                  icon: const Icon(Icons.auto_awesome_rounded, size: 16),
                  label: const Text('生成建议'),
                  style: _outlineButtonStyle(),
                ),
              ),
              SizedBox(
                height: 38,
                child: ElevatedButton.icon(
                  onPressed: onCreateTask,
                  icon: const Icon(Icons.add_task_rounded, size: 17),
                  label: const Text('新建任务'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(horizontal: 14),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                    textStyle: AppTheme.ts(
                      fontSize: 12,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ),
              ),
            ],
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                title,
                const SizedBox(height: 12),
                controls,
              ],
            );
          }
          return Row(
            children: [
              Expanded(child: title),
              const SizedBox(width: 14),
              controls,
            ],
          );
        },
      ),
    );
  }
}

class _LearningHero extends StatelessWidget {
  final CareerApplicationView? app;
  final CareerLearningSummaryView learning;
  final int progress;
  final bool loading;
  final VoidCallback onPrimary;

  const _LearningHero({
    required this.app,
    required this.learning,
    required this.progress,
    required this.loading,
    required this.onPrimary,
  });

  @override
  Widget build(BuildContext context) {
    final topWeaknesses = learning.weaknesses
        .where((item) => item.state != 'resolved')
        .take(3)
        .toList();
    final position = app?.position.trim() ?? '';
    final title = app == null ? '学习路线待建立' : '当前学习状态';
    final subtitle = app == null
        ? '选择或创建求职项目后，这里会展示面向岗位的短板和任务推进。'
        : '围绕 ${position.isEmpty ? '目标岗位' : position} 持续补齐关键技能与面试证据。';
    return Container(
      padding: const EdgeInsets.fromLTRB(26, 24, 26, 24),
      decoration: ProductSurface.hero(),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 760;
          final content = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    title,
                    style: AppTheme.ts(
                      fontSize: compact ? 22 : 25,
                      fontWeight: FontWeight.w900,
                      color: ProductColors.text,
                    ),
                  ),
                  const SizedBox(width: 8),
                  const Icon(
                    Icons.auto_awesome_rounded,
                    size: 20,
                    color: ProductColors.primary,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                subtitle,
                maxLines: compact ? 4 : 2,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 14,
                  height: 1.55,
                  fontWeight: FontWeight.w700,
                  color: ProductColors.textSecondary,
                ),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  ProductTag(
                    label:
                        '目标岗位：${careerShortLabel(app?.position, fallback: '待选择')}',
                    tone: ProductTone.primary,
                  ),
                  ProductTag(
                    label: '待推进：${learning.openTaskCount} 个',
                    tone: ProductTone.info,
                  ),
                  ProductTag(
                    label: '高优先短板：${learning.highWeaknessCount} 个',
                    tone: learning.highWeaknessCount > 0
                        ? ProductTone.warning
                        : ProductTone.neutral,
                  ),
                ],
              ),
              const SizedBox(height: 18),
              SizedBox(
                height: 44,
                child: ElevatedButton.icon(
                  onPressed: onPrimary,
                  icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                  label: Text(
                    app == null ? '选择项目生成计划' : '生成下一步建议',
                    style: AppTheme.ts(
                      fontSize: 13,
                      fontWeight: FontWeight.w900,
                      color: Colors.white,
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: ProductColors.primary,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(horizontal: 18),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
              ),
            ],
          );
          final insight = ProductCard(
            soft: true,
            tone: ProductTone.primary,
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.psychology_alt_outlined,
                      size: 17,
                      color: ProductColors.primary,
                    ),
                    const SizedBox(width: 7),
                    Expanded(
                      child: Text(
                        '学习判断',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 13,
                          fontWeight: FontWeight.w900,
                          color: ProductColors.text,
                        ),
                      ),
                    ),
                    if (loading)
                      const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: ProductColors.primary,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  _learningJudgement(learning),
                  maxLines: 4,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12,
                    height: 1.48,
                    color: ProductColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                if (topWeaknesses.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  for (final weakness in topWeaknesses) ...[
                    _WeaknessMiniRow(weakness: weakness),
                    const SizedBox(height: 8),
                  ],
                ],
              ],
            ),
          );
          final ring = ProductScoreRing(
            score: progress,
            label: '学习进度',
            size: compact ? 92 : 106,
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                content,
                const SizedBox(height: 18),
                Center(child: ring),
                const SizedBox(height: 18),
                insight,
              ],
            );
          }
          return Row(
            children: [
              Expanded(child: content),
              const SizedBox(width: 20),
              ring,
              const SizedBox(width: 20),
              SizedBox(width: 330, child: insight),
            ],
          );
        },
      ),
    );
  }
}

class _LearningProjectStrip extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final String? selectedId;

  const _LearningProjectStrip({
    required this.provider,
    required this.selectedId,
  });

  @override
  Widget build(BuildContext context) {
    final apps = provider.applications;
    if (apps.isEmpty) {
      return const ProductCard(
        child: _EmptyLearningMessage(
          message: '还没有求职项目。先建立目标岗位后，学习计划会自动围绕岗位差距组织。',
        ),
      );
    }
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '关联求职项目',
            style: AppTheme.ts(
              fontSize: 13,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(height: 10),
          SizedBox(
            height: 42,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: apps.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                final item = apps[index];
                final selected =
                    item.application.applicationId == selectedId?.trim();
                return _ProjectChip(
                  summary: item,
                  selected: selected,
                  loading: provider
                      .isApplicationLoading(item.application.applicationId),
                  onTap: () => unawaited(
                    provider.selectApplication(item.application.applicationId),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _LearningMetricStrip extends StatelessWidget {
  final CareerLearningSummaryView learning;
  final int openTaskCount;
  final int doneTaskCount;
  final int progress;

  const _LearningMetricStrip({
    required this.learning,
    required this.openTaskCount,
    required this.doneTaskCount,
    required this.progress,
  });

  @override
  Widget build(BuildContext context) {
    final metrics = [
      ProductMetricCard(
        label: '学习路线',
        value: learning.plans.length.toString(),
        trend: learning.plans.isEmpty ? '待生成' : '持续更新',
        icon: Icons.route_outlined,
        tone: ProductTone.purple,
      ),
      ProductMetricCard(
        label: '待推进任务',
        value: openTaskCount.toString(),
        trend: learning.highWeaknessCount > 0
            ? '高优先 ${learning.highWeaknessCount} 个'
            : '按计划推进',
        icon: Icons.checklist_rounded,
        tone: openTaskCount > 0 ? ProductTone.info : ProductTone.neutral,
      ),
      ProductMetricCard(
        label: '已完成任务',
        value: doneTaskCount.toString(),
        trend: '进度 $progress%',
        icon: Icons.verified_outlined,
        tone: ProductTone.primary,
      ),
      ProductMetricCard(
        label: '复盘安排',
        value: learning.reviews.length.toString(),
        trend: learning.reviews.isEmpty ? '暂无复盘' : '按时回顾',
        icon: Icons.event_repeat_outlined,
        tone: ProductTone.warning,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns =
            (constraints.maxWidth / 230).floor().clamp(1, 4).toInt();
        final width =
            (constraints.maxWidth - (columns - 1) * 12) / math.max(columns, 1);
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final metric in metrics) SizedBox(width: width, child: metric),
          ],
        );
      },
    );
  }
}

class _LearningPlanSection extends StatelessWidget {
  final List<CareerWorkbenchLearningPlanView> plans;

  const _LearningPlanSection({required this.plans});

  @override
  Widget build(BuildContext context) {
    final visible = [...plans]
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return ProductSection(
      title: '学习路线',
      subtitle: visible.isEmpty ? '暂无路线' : '${visible.length} 条路线',
      icon: Icons.route_outlined,
      tone: ProductTone.purple,
      child: visible.isEmpty
          ? const _EmptyLearningMessage(
              message: '还没有学习路线。可以先让 Agent 根据岗位匹配差距生成一版。',
            )
          : Column(
              children: [
                for (final plan in visible.take(3)) ...[
                  _LearningPlanCard(plan: plan),
                  if (plan != visible.take(3).last) const SizedBox(height: 10),
                ],
              ],
            ),
    );
  }
}

class _LearningPlanCard extends StatelessWidget {
  final CareerWorkbenchLearningPlanView plan;

  const _LearningPlanCard({required this.plan});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: ProductSurface.softCard(tone: ProductTone.purple),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  plan.title.trim().isEmpty ? '未命名学习路线' : plan.title.trim(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              ProductTag(
                label: careerPriorityLabel(plan.priority),
                tone: careerPriorityTone(plan.priority),
              ),
            ],
          ),
          const SizedBox(height: 7),
          Text(
            careerFirstNonEmpty(
              [plan.progressSummary, plan.description],
              fallback: '围绕目标岗位拆解学习目标和任务。',
            ),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11.5,
              height: 1.45,
              color: ProductColors.textSecondary,
            ),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final tag in plan.focusSkillTags.take(5))
                ProductTag(label: tag, tone: ProductTone.purple),
              if (plan.targetRole.trim().isNotEmpty)
                ProductTag(
                    label: plan.targetRole.trim(), tone: ProductTone.info),
              ProductTag(
                label: '更新 ${careerFormatDateTime(plan.updatedAt)}',
                tone: ProductTone.neutral,
              ),
            ],
          ),
          if (plan.goals.isNotEmpty) ...[
            const SizedBox(height: 10),
            for (final goal in plan.goals.take(3))
              _CheckLine(text: goal, tone: ProductTone.purple),
          ],
        ],
      ),
    );
  }
}

class _LearningTaskBoard extends StatelessWidget {
  final List<CareerWorkbenchLearningTaskView> tasks;
  final ValueChanged<CareerWorkbenchLearningTaskView> onCheckIn;
  final VoidCallback onCreateTask;

  const _LearningTaskBoard({
    required this.tasks,
    required this.onCheckIn,
    required this.onCreateTask,
  });

  @override
  Widget build(BuildContext context) {
    final doing = tasks.where((task) => task.state == 'doing').toList();
    final todo = tasks
        .where((task) => task.state != 'doing' && _isOpenTask(task))
        .toList();
    final done = tasks.where(_isDoneTask).toList();
    return ProductSection(
      title: '学习任务',
      subtitle: tasks.isEmpty ? '暂无任务' : '${tasks.length} 个任务',
      icon: Icons.fact_check_outlined,
      tone: ProductTone.info,
      trailing: TextButton.icon(
        onPressed: onCreateTask,
        icon: const Icon(Icons.add_rounded, size: 15),
        label: const Text('新建'),
        style: TextButton.styleFrom(
          foregroundColor: ProductColors.primary,
          textStyle: AppTheme.ts(fontSize: 11, fontWeight: FontWeight.w900),
        ),
      ),
      child: tasks.isEmpty
          ? const _EmptyLearningMessage(
              message: '还没有学习任务。可以从岗位差距、面试复盘或手动输入创建。',
            )
          : LayoutBuilder(
              builder: (context, constraints) {
                final columns = constraints.maxWidth >= 920
                    ? 3
                    : constraints.maxWidth >= 620
                        ? 2
                        : 1;
                final width =
                    (constraints.maxWidth - (columns - 1) * 10) / columns;
                final lanes = [
                  _TaskLaneData('进行中', doing, ProductTone.primary),
                  _TaskLaneData('待推进', todo, ProductTone.info),
                  _TaskLaneData('已完成', done, ProductTone.neutral),
                ];
                return Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (final lane in lanes)
                      SizedBox(
                        width: width,
                        child: _TaskLane(
                          lane: lane,
                          onCheckIn: onCheckIn,
                        ),
                      ),
                  ],
                );
              },
            ),
    );
  }
}

class _TaskLane extends StatelessWidget {
  final _TaskLaneData lane;
  final ValueChanged<CareerWorkbenchLearningTaskView> onCheckIn;

  const _TaskLane({
    required this.lane,
    required this.onCheckIn,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(lane.tone);
    return Container(
      constraints: const BoxConstraints(minHeight: 220),
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
      decoration: BoxDecoration(
        color: style.soft.withValues(alpha: 0.46),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: style.color.withValues(alpha: 0.12)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  lane.title,
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
              ProductTag(label: '${lane.tasks.length}', tone: lane.tone),
            ],
          ),
          const SizedBox(height: 10),
          if (lane.tasks.isEmpty)
            Text(
              '暂无',
              style: AppTheme.ts(
                fontSize: 11,
                color: ProductColors.textMuted,
              ),
            )
          else
            for (final task in lane.tasks.take(4)) ...[
              _LearningTaskCard(task: task, onCheckIn: () => onCheckIn(task)),
              if (task != lane.tasks.take(4).last) const SizedBox(height: 8),
            ],
        ],
      ),
    );
  }
}

class _LearningTaskCard extends StatelessWidget {
  final CareerWorkbenchLearningTaskView task;
  final VoidCallback onCheckIn;

  const _LearningTaskCard({
    required this.task,
    required this.onCheckIn,
  });

  @override
  Widget build(BuildContext context) {
    final tone = _taskStateTone(task.state);
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
      decoration: ProductSurface.card(radius: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ProductIconTile(
                icon: _taskTypeIcon(task.taskType),
                tone: tone,
                size: 34,
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      task.title.trim().isEmpty ? '未命名任务' : task.title.trim(),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12.2,
                        height: 1.25,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      _taskSubtitle(task),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.8,
                        height: 1.35,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          Wrap(
            spacing: 5,
            runSpacing: 5,
            children: [
              ProductTag(label: _taskStateLabel(task.state), tone: tone),
              ProductTag(
                label: careerPriorityLabel(task.priority),
                tone: careerPriorityTone(task.priority),
              ),
              if (task.estimatedMinutes > 0)
                ProductTag(
                  label: '${task.estimatedMinutes} 分钟',
                  tone: ProductTone.neutral,
                ),
            ],
          ),
          if (task.skillTags.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 5,
              runSpacing: 5,
              children: [
                for (final tag in task.skillTags.take(3))
                  ProductTag(label: tag, tone: ProductTone.purple),
              ],
            ),
          ],
          if (!_isDoneTask(task)) ...[
            const SizedBox(height: 10),
            SizedBox(
              height: 32,
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: onCheckIn,
                icon: const Icon(Icons.edit_note_outlined, size: 15),
                label: const Text('记录进度'),
                style: _outlineButtonStyle(),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _LearningWeaknessSection extends StatelessWidget {
  final List<CareerWorkbenchWeaknessView> weaknesses;
  final List<CareerWorkbenchLearningTaskView> tasks;
  final VoidCallback onCreateTask;

  const _LearningWeaknessSection({
    required this.weaknesses,
    required this.tasks,
    required this.onCreateTask,
  });

  @override
  Widget build(BuildContext context) {
    final openWeaknesses = weaknesses
        .where((item) => item.state != 'resolved' && item.status == 'active')
        .toList()
      ..sort((a, b) =>
          _severityRank(a.severity).compareTo(_severityRank(b.severity)));
    return ProductSection(
      title: '短板与证据缺口',
      subtitle:
          openWeaknesses.isEmpty ? '暂无高优先短板' : '${openWeaknesses.length} 个待补齐',
      icon: Icons.report_problem_outlined,
      tone: openWeaknesses.isEmpty ? ProductTone.neutral : ProductTone.warning,
      trailing: TextButton.icon(
        onPressed: onCreateTask,
        icon: const Icon(Icons.add_task_rounded, size: 15),
        label: const Text('转任务'),
        style: TextButton.styleFrom(
          foregroundColor: ProductColors.primary,
          textStyle: AppTheme.ts(fontSize: 11, fontWeight: FontWeight.w900),
        ),
      ),
      child: openWeaknesses.isEmpty
          ? const _EmptyLearningMessage(
              message: '暂时没有未解决短板。后续 JD 匹配、面试复盘会把差距沉淀到这里。',
            )
          : LayoutBuilder(
              builder: (context, constraints) {
                final columns = constraints.maxWidth >= 760 ? 2 : 1;
                final width =
                    (constraints.maxWidth - (columns - 1) * 10) / columns;
                return Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    for (final weakness in openWeaknesses.take(4))
                      SizedBox(
                        width: width,
                        child: _WeaknessCard(
                          weakness: weakness,
                          taskCount: tasks
                              .where((task) => weakness.relatedTaskIds
                                  .contains(task.learningTaskId))
                              .length,
                        ),
                      ),
                  ],
                );
              },
            ),
    );
  }
}

class _WeaknessCard extends StatelessWidget {
  final CareerWorkbenchWeaknessView weakness;
  final int taskCount;

  const _WeaknessCard({
    required this.weakness,
    required this.taskCount,
  });

  @override
  Widget build(BuildContext context) {
    final tone = _severityTone(weakness.severity);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 12, 12, 12),
      decoration: ProductSurface.softCard(tone: tone),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ProductIconTile(
                icon: Icons.priority_high_rounded,
                tone: tone,
                size: 34,
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Text(
                  weakness.title.trim().isEmpty
                      ? '未命名短板'
                      : weakness.title.trim(),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.4,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
              ProductTag(label: _severityLabel(weakness.severity), tone: tone),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            weakness.description.trim().isEmpty
                ? '需要补充可验证的学习或项目证据。'
                : weakness.description.trim(),
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11,
              height: 1.42,
              color: ProductColors.textSecondary,
            ),
          ),
          const SizedBox(height: 9),
          Wrap(
            spacing: 5,
            runSpacing: 5,
            children: [
              for (final tag in weakness.skillTags.take(4))
                ProductTag(label: tag, tone: ProductTone.purple),
              ProductTag(
                label: taskCount == 0 ? '未关联任务' : '$taskCount 个任务',
                tone:
                    taskCount == 0 ? ProductTone.warning : ProductTone.primary,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LearningReviewSection extends StatelessWidget {
  final List<CareerWorkbenchReviewView> reviews;

  const _LearningReviewSection({required this.reviews});

  @override
  Widget build(BuildContext context) {
    final visible = [...reviews]..sort((a, b) => (a.nextReviewAt ?? a.updatedAt)
        .compareTo(b.nextReviewAt ?? b.updatedAt));
    return ProductSection(
      title: '复盘安排',
      subtitle: visible.isEmpty ? '暂无复盘' : '${visible.length} 条安排',
      icon: Icons.event_note_outlined,
      tone: ProductTone.neutral,
      child: visible.isEmpty
          ? const _EmptyLearningMessage(
              message: '暂无复盘安排。完成任务或面试复盘后，可以在这里追踪回顾节奏。',
            )
          : Column(
              children: [
                for (final review in visible.take(4)) ...[
                  _ReviewRow(review: review),
                  if (review != visible.take(4).last)
                    const Divider(height: 16, color: ProductColors.border),
                ],
              ],
            ),
    );
  }
}

class _LearningRightRail extends StatelessWidget {
  final CareerWorkbenchProvider provider;
  final CareerApplicationView? app;
  final CareerLearningSummaryView learning;
  final List<CareerWorkbenchLearningTaskView> openTasks;
  final VoidCallback onOpenProjects;
  final VoidCallback onOpenNotes;
  final VoidCallback onCreateTask;
  final VoidCallback onRecommend;

  const _LearningRightRail({
    required this.provider,
    required this.app,
    required this.learning,
    required this.openTasks,
    required this.onOpenProjects,
    required this.onOpenNotes,
    required this.onCreateTask,
    required this.onRecommend,
  });

  @override
  Widget build(BuildContext context) {
    final detail = provider.selectedApplicationDetail;
    final notes = detail?.notes ?? const <CareerNoteSummaryView>[];
    return Column(
      children: [
        ProductSection(
          title: '今日推进',
          subtitle: openTasks.isEmpty ? '暂无待办' : '${openTasks.length} 个待办',
          icon: Icons.today_outlined,
          tone: ProductTone.primary,
          trailing: TextButton(
            onPressed: onRecommend,
            style: TextButton.styleFrom(
              foregroundColor: ProductColors.primary,
              textStyle: AppTheme.ts(fontSize: 11, fontWeight: FontWeight.w900),
            ),
            child: const Text('生成建议'),
          ),
          child: openTasks.isEmpty
              ? const _EmptyLearningMessage(message: '今天没有待推进任务。')
              : Column(
                  children: [
                    for (final task in openTasks.take(4)) ...[
                      ProductActionTile(
                        title: task.title,
                        subtitle: _taskSubtitle(task),
                        icon: _taskTypeIcon(task.taskType),
                        tone: _taskStateTone(task.state),
                        badge: careerPriorityLabel(task.priority),
                        actionLabel: '推进',
                        onTap: onCreateTask,
                      ),
                      if (task != openTasks.take(4).last)
                        const SizedBox(height: 8),
                    ],
                  ],
                ),
        ),
        const SizedBox(height: 14),
        ProductSection(
          title: '关联项目',
          subtitle: app == null ? '未选择项目' : careerStageLabel(app!.stage),
          icon: Icons.work_outline_rounded,
          tone: ProductTone.info,
          child: ProductActionTile(
            title: app?.displayTitle ?? '选择求职项目',
            subtitle: app == null
                ? '打开求职项目后，学习任务会关联到目标岗位。'
                : careerFirstNonEmpty(
                    [app!.summary, '${app!.company} · ${app!.location}'],
                    fallback: '查看岗位状态和材料准备情况。',
                  ),
            icon: Icons.business_center_outlined,
            tone: ProductTone.info,
            actionLabel: '查看',
            onTap: onOpenProjects,
          ),
        ),
        const SizedBox(height: 14),
        ProductSection(
          title: '关联笔记',
          subtitle: notes.isEmpty ? '暂无笔记' : '${notes.length} 条笔记',
          icon: Icons.sticky_note_2_outlined,
          tone: ProductTone.warning,
          trailing: TextButton(
            onPressed: onOpenNotes,
            style: TextButton.styleFrom(
              foregroundColor: ProductColors.primary,
              textStyle: AppTheme.ts(fontSize: 11, fontWeight: FontWeight.w900),
            ),
            child: const Text('查看全部'),
          ),
          child: notes.isEmpty
              ? const _EmptyLearningMessage(
                  message: '面试复盘和学习笔记会出现在这里。',
                )
              : Column(
                  children: [
                    for (final note in notes.take(3)) ...[
                      _NoteMiniRow(note: note),
                      if (note != notes.take(3).last)
                        const Divider(height: 16, color: ProductColors.border),
                    ],
                  ],
                ),
        ),
        const SizedBox(height: 14),
        ProductSection(
          title: '学习资产',
          subtitle:
              '${learning.plans.length + learning.tasks.length + learning.weaknesses.length} 条记录',
          icon: Icons.folder_copy_outlined,
          tone: ProductTone.purple,
          child: Column(
            children: [
              _AssetCountRow(
                label: '路线',
                value: learning.plans.length,
                icon: Icons.route_outlined,
              ),
              const SizedBox(height: 8),
              _AssetCountRow(
                label: '任务',
                value: learning.tasks.length,
                icon: Icons.fact_check_outlined,
              ),
              const SizedBox(height: 8),
              _AssetCountRow(
                label: '短板',
                value: learning.weaknesses.length,
                icon: Icons.report_problem_outlined,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ProjectChip extends StatelessWidget {
  final CareerApplicationSummaryView summary;
  final bool selected;
  final bool loading;
  final VoidCallback onTap;

  const _ProjectChip({
    required this.summary,
    required this.selected,
    required this.loading,
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
          constraints: const BoxConstraints(maxWidth: 300),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: style.soft.withValues(alpha: selected ? 0.82 : 0.52),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: style.color.withValues(alpha: 0.16)),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (loading)
                SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: style.color,
                  ),
                )
              else
                Icon(Icons.work_outline_rounded, size: 14, color: style.color),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  summary.application.displayTitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w900,
                    color: style.color,
                  ),
                ),
              ),
              const SizedBox(width: 7),
              Text(
                '${summary.learningTaskCount}',
                style: AppTheme.ts(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w900,
                  color: style.color.withValues(alpha: 0.8),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WeaknessMiniRow extends StatelessWidget {
  final CareerWorkbenchWeaknessView weakness;

  const _WeaknessMiniRow({required this.weakness});

  @override
  Widget build(BuildContext context) {
    final tone = _severityTone(weakness.severity);
    final style = productToneStyle(tone);
    return Row(
      children: [
        Icon(Icons.circle_rounded, size: 8, color: style.color),
        const SizedBox(width: 7),
        Expanded(
          child: Text(
            weakness.title,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 11,
              fontWeight: FontWeight.w800,
              color: ProductColors.textSecondary,
            ),
          ),
        ),
        const SizedBox(width: 6),
        ProductTag(label: _severityLabel(weakness.severity), tone: tone),
      ],
    );
  }
}

class _ReviewRow extends StatelessWidget {
  final CareerWorkbenchReviewView review;

  const _ReviewRow({required this.review});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ProductIconTile(
          icon: Icons.event_repeat_outlined,
          tone: _reviewTone(review.state),
          size: 34,
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                review.title.trim().isEmpty ? '学习复盘' : review.title.trim(),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 12.2,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                careerFirstNonEmpty(
                  [
                    review.summary,
                    review.nextReviewAt == null
                        ? null
                        : '下次复盘 ${careerFormatDateTime(review.nextReviewAt)}',
                  ],
                  fallback: '按学习节奏回顾吸收情况。',
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 11,
                  height: 1.35,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 8),
        ProductTag(
          label: _reviewStateLabel(review.state),
          tone: _reviewTone(review.state),
        ),
      ],
    );
  }
}

class _NoteMiniRow extends StatelessWidget {
  final CareerNoteSummaryView note;

  const _NoteMiniRow({required this.note});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ProductIconTile(
          icon: Icons.sticky_note_2_outlined,
          tone: ProductTone.warning,
          size: 32,
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                note.title.trim().isEmpty ? '未命名笔记' : note.title.trim(),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 12,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                careerFirstNonEmpty([note.summary, note.tags.join(' · ')]),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 10.8,
                  height: 1.35,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _AssetCountRow extends StatelessWidget {
  final String label;
  final int value;
  final IconData icon;

  const _AssetCountRow({
    required this.label,
    required this.value,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        ProductIconTile(icon: icon, tone: ProductTone.purple, size: 32),
        const SizedBox(width: 9),
        Expanded(
          child: Text(
            label,
            style: AppTheme.ts(
              fontSize: 11.5,
              fontWeight: FontWeight.w800,
              color: ProductColors.textSecondary,
            ),
          ),
        ),
        Text(
          '$value',
          style: AppTheme.ts(
            fontSize: 14,
            fontWeight: FontWeight.w900,
            color: ProductColors.text,
          ),
        ),
      ],
    );
  }
}

class _CheckLine extends StatelessWidget {
  final String text;
  final ProductTone tone;

  const _CheckLine({
    required this.text,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.check_circle_outline_rounded,
              size: 14, color: style.color),
          const SizedBox(width: 7),
          Expanded(
            child: Text(
              text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: AppTheme.ts(
                fontSize: 11.2,
                height: 1.38,
                color: ProductColors.textSecondary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyLearningMessage extends StatelessWidget {
  final String message;

  const _EmptyLearningMessage({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: ProductSurface.softCard(tone: ProductTone.neutral),
      child: Text(
        message,
        style: AppTheme.ts(
          fontSize: 12,
          height: 1.45,
          color: ProductColors.textSecondary,
        ),
      ),
    );
  }
}

class _LearningError extends StatelessWidget {
  final String error;
  final VoidCallback onRetry;

  const _LearningError({
    required this.error,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: ProductCard(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.error_outline_rounded,
              color: ProductColors.danger,
              size: 30,
            ),
            const SizedBox(height: 10),
            Text(
              '学习计划加载失败',
              style: AppTheme.ts(
                fontSize: 14,
                fontWeight: FontWeight.w900,
                color: ProductColors.text,
              ),
            ),
            const SizedBox(height: 6),
            Text(
              error,
              textAlign: TextAlign.center,
              style: AppTheme.ts(
                fontSize: 12,
                color: ProductColors.textSecondary,
              ),
            ),
            const SizedBox(height: 12),
            ElevatedButton(
              onPressed: onRetry,
              style: ElevatedButton.styleFrom(
                backgroundColor: ProductColors.primary,
                foregroundColor: Colors.white,
                elevation: 0,
              ),
              child: const Text('重试'),
            ),
          ],
        ),
      ),
    );
  }
}

class _TaskLaneData {
  final String title;
  final List<CareerWorkbenchLearningTaskView> tasks;
  final ProductTone tone;

  const _TaskLaneData(this.title, this.tasks, this.tone);
}

CareerLearningSummaryView _emptyLearning() {
  return CareerLearningSummaryView(
    plans: const [],
    tasks: const [],
    weaknesses: const [],
    reviews: const [],
    openTaskCount: 0,
    doneTaskCount: 0,
    highWeaknessCount: 0,
  );
}

List<CareerWorkbenchLearningTaskView> _sortedTasks(
  List<CareerWorkbenchLearningTaskView> tasks,
) {
  final records = [...tasks];
  records.sort((a, b) {
    final state = _taskStateRank(a.state).compareTo(_taskStateRank(b.state));
    if (state != 0) return state;
    final priority =
        _priorityRank(a.priority).compareTo(_priorityRank(b.priority));
    if (priority != 0) return priority;
    final dueA = a.dueDate ?? DateTime(9999);
    final dueB = b.dueDate ?? DateTime(9999);
    final due = dueA.compareTo(dueB);
    if (due != 0) return due;
    return b.updatedAt.compareTo(a.updatedAt);
  });
  return records;
}

bool _isOpenTask(CareerWorkbenchLearningTaskView task) {
  return task.state != 'done' &&
      task.state != 'completed' &&
      task.state != 'cancelled';
}

bool _isDoneTask(CareerWorkbenchLearningTaskView task) {
  return task.state == 'done' || task.state == 'completed';
}

int _progressPercent(int open, int done) {
  final total = open + done;
  if (total <= 0) return 0;
  return ((done / total) * 100).round().clamp(0, 100);
}

String _learningJudgement(CareerLearningSummaryView learning) {
  if (learning.tasks.isEmpty && learning.weaknesses.isEmpty) {
    return '还没有形成学习闭环。建议先基于目标岗位匹配报告生成学习任务。';
  }
  if (learning.highWeaknessCount > 0) {
    return '仍有高优先短板需要处理，建议优先把短板转成可验证的项目表达、练习题或面试复盘任务。';
  }
  if (learning.openTaskCount > 0) {
    return '学习路线已经建立，当前重点是稳定推进待办任务，并把阶段成果沉淀为面试证据。';
  }
  return '当前学习任务完成度较好，可以安排复盘或继续针对新岗位生成下一批任务。';
}

String _taskSubtitle(CareerWorkbenchLearningTaskView task) {
  return careerFirstNonEmpty(
    [
      task.description,
      task.successCriteria.take(2).join('；'),
      task.progressNotes,
    ],
    fallback: '围绕岗位差距推进一项具体练习。',
  );
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

ProductTone _taskStateTone(String state) {
  return switch (state.trim()) {
    'doing' || 'in_progress' => ProductTone.primary,
    'done' || 'completed' => ProductTone.neutral,
    'blocked' => ProductTone.warning,
    'cancelled' => ProductTone.neutral,
    _ => ProductTone.info,
  };
}

IconData _taskTypeIcon(String type) {
  return switch (type.trim()) {
    'interview' || 'interview_prep' => Icons.chat_bubble_outline_rounded,
    'project' || 'portfolio' => Icons.folder_special_outlined,
    'course' || 'learning' => Icons.menu_book_outlined,
    'practice' || 'coding' => Icons.code_rounded,
    'review' => Icons.event_repeat_outlined,
    _ => Icons.school_outlined,
  };
}

int _taskStateRank(String state) {
  return switch (state.trim()) {
    'doing' || 'in_progress' => 0,
    'todo' || 'blocked' => 1,
    'done' || 'completed' => 2,
    'cancelled' => 3,
    _ => 1,
  };
}

int _priorityRank(String priority) {
  return switch (priority.trim()) {
    'urgent' => 0,
    'high' => 1,
    'medium' => 2,
    'low' => 3,
    _ => 2,
  };
}

int _severityRank(String severity) {
  return switch (severity.trim()) {
    'critical' => 0,
    'high' => 1,
    'medium' => 2,
    'low' => 3,
    _ => 2,
  };
}

String _severityLabel(String severity) {
  return switch (severity.trim()) {
    'critical' => '严重',
    'high' => '高优先',
    'medium' => '中优先',
    'low' => '低优先',
    _ => '中优先',
  };
}

ProductTone _severityTone(String severity) {
  return switch (severity.trim()) {
    'critical' || 'high' => ProductTone.warning,
    'low' => ProductTone.info,
    _ => ProductTone.neutral,
  };
}

String _reviewStateLabel(String state) {
  return switch (state.trim()) {
    'scheduled' => '已安排',
    'done' || 'completed' => '已完成',
    'overdue' => '待补',
    _ => '待复盘',
  };
}

ProductTone _reviewTone(String state) {
  return switch (state.trim()) {
    'done' || 'completed' => ProductTone.primary,
    'overdue' => ProductTone.warning,
    _ => ProductTone.neutral,
  };
}

ButtonStyle _outlineButtonStyle() {
  return OutlinedButton.styleFrom(
    foregroundColor: ProductColors.primary,
    side: const BorderSide(color: ProductColors.borderStrong),
    padding: const EdgeInsets.symmetric(horizontal: 12),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    textStyle: AppTheme.ts(fontSize: 12, fontWeight: FontWeight.w900),
  );
}
