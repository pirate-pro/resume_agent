import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models/api_models.dart';
import '../../core/providers/chat_provider.dart';
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
  String? _runningInlineAction;
  String? _completedInlineAction;
  String? _failedInlineAction;
  String _inlineActionMessage = '';
  final GlobalKey _taskBoardKey = GlobalKey();
  final GlobalKey _roadmapKey = GlobalKey();

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
        final hero = _LearningHero(
          app: app,
          learning: learning,
          progress: progress,
          loading: loadingSelected,
          onPrimary: () => _handleHeroPrimaryAction(
            app: app,
            learning: learning,
            openTaskCount: openTasks.length,
          ),
          onRoadmap: _scrollToRoadmap,
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
          padding: const EdgeInsets.only(bottom: 28),
          children: [
            hero,
            const SizedBox(height: 8),
            projects,
            const SizedBox(height: 12),
            metrics,
            const SizedBox(height: 12),
            KeyedSubtree(
              key: _roadmapKey,
              child: _LearningPlanSection(
                learning: learning,
                overallProgress: progress,
              ),
            ),
            const SizedBox(height: 12),
            KeyedSubtree(
              key: _taskBoardKey,
              child: _LearningTaskBoard(
                tasks: tasks,
                action: _inlineActionState('tasks'),
                onOpenDetails: (task) => _showTaskDetailSheet(
                  app: app,
                  learning: learning,
                  task: task,
                ),
                onCheckIn: (task) => _showCheckInSheet(app, task),
                onCreateTask: () => unawaited(_sendCreateTask(app)),
                onGenerateTaskDrafts: () =>
                    unawaited(_openTaskDrafts(learning, app)),
                onMoveTask: _moveLearningTaskState,
              ),
            ),
            const SizedBox(height: 14),
            _LearningBottomInsightGrid(
              weaknesses: learning.weaknesses,
              tasks: tasks,
              reviews: learning.reviews,
              onCreateTask: () => unawaited(_sendCreateTask(app)),
              onOpenNotes: widget.onOpenNotes,
              onWeaknessRecommend: () => unawaited(
                _sendRecommend(learning, app, surface: 'weakness'),
              ),
              onReviewRecommend: () => unawaited(
                _sendRecommend(learning, app, surface: 'review'),
              ),
              onStartReview: (review) => unawaited(_completeReview(review)),
              weaknessAction: _inlineActionState('weakness'),
              reviewAction: _inlineActionState('review'),
            ),
          ],
        );
        final rail = _LearningRightRail(
          provider: provider,
          app: app,
          learning: learning,
          openTasks: openTasks,
          onOpenProjects: widget.onOpenProjects,
          onOpenNotes: widget.onOpenNotes,
          onCheckIn: (task) => _showCheckInSheet(app, task),
        );

        if (!desktop) {
          return ListView(
            padding: EdgeInsets.zero,
            children: [
              hero,
              const SizedBox(height: 8),
              projects,
              const SizedBox(height: 12),
              rail,
              const SizedBox(height: 14),
              metrics,
              const SizedBox(height: 12),
              KeyedSubtree(
                key: _roadmapKey,
                child: _LearningPlanSection(
                  learning: learning,
                  overallProgress: progress,
                ),
              ),
              const SizedBox(height: 12),
              KeyedSubtree(
                key: _taskBoardKey,
                child: _LearningTaskBoard(
                  tasks: tasks,
                  action: _inlineActionState('tasks'),
                  onOpenDetails: (task) => _showTaskDetailSheet(
                    app: app,
                    learning: learning,
                    task: task,
                  ),
                  onCheckIn: (task) => _showCheckInSheet(app, task),
                  onCreateTask: () => unawaited(_sendCreateTask(app)),
                  onGenerateTaskDrafts: () => unawaited(
                    _openTaskDrafts(learning, app),
                  ),
                  onMoveTask: _moveLearningTaskState,
                ),
              ),
              const SizedBox(height: 14),
              _LearningBottomInsightGrid(
                weaknesses: learning.weaknesses,
                tasks: tasks,
                reviews: learning.reviews,
                onCreateTask: () => unawaited(_sendCreateTask(app)),
                onOpenNotes: widget.onOpenNotes,
                onWeaknessRecommend: () => unawaited(
                  _sendRecommend(learning, app, surface: 'weakness'),
                ),
                onReviewRecommend: () => unawaited(
                  _sendRecommend(learning, app, surface: 'review'),
                ),
                onStartReview: (review) => unawaited(_completeReview(review)),
                weaknessAction: _inlineActionState('weakness'),
                reviewAction: _inlineActionState('review'),
              ),
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(child: main),
            const SizedBox(width: 16),
            SizedBox(width: 340, child: ListView(children: [rail])),
          ],
        );
      },
    );
  }

  Future<void> _sendRecommend(
    CareerLearningSummaryView learning,
    CareerApplicationView? app, {
    required String surface,
  }) async {
    final sender = widget.onSendPrompt;
    final messenger = ScaffoldMessenger.maybeOf(context);
    if (sender == null || app == null) {
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('请先选择一个求职项目'),
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }
    if (_runningInlineAction != null) return;
    setState(() {
      _runningInlineAction = surface;
      _completedInlineAction = null;
      _failedInlineAction = null;
      _inlineActionMessage = _inlineActionRunningMessage(surface);
    });
    final beforeTasks = learning.tasks.length;
    final beforeWeaknesses = learning.weaknesses.length;
    final beforeReviews = learning.reviews.length;
    final prompt = _learningRecommendPrompt(
      learning: learning,
      app: app,
      surface: surface,
    );
    try {
      // 这里故意不传 CareerWorkbenchActionRequest，避免触发全局顶部动作横幅。
      await sender(prompt);
      final error = ref.read(chatProvider).error;
      if (error != null && error.trim().isNotEmpty) {
        throw Exception(error);
      }
      await ref.read(careerWorkbenchProvider).refresh();
      if (!mounted) return;
      final updatedLearning =
          ref.read(careerWorkbenchProvider).selectedApplicationDetail?.learning;
      setState(() {
        _runningInlineAction = null;
        _completedInlineAction = surface;
        _failedInlineAction = null;
        _inlineActionMessage = _inlineActionCompletedMessage(
          updatedLearning,
          beforeTasks: beforeTasks,
          beforeWeaknesses: beforeWeaknesses,
          beforeReviews: beforeReviews,
        );
      });
      _clearInlineActionLater(surface);
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _runningInlineAction = null;
        _completedInlineAction = null;
        _failedInlineAction = surface;
        _inlineActionMessage = '生成失败：$error';
      });
      _clearInlineActionLater(surface);
    }
  }

  void _handleHeroPrimaryAction({
    required CareerApplicationView? app,
    required CareerLearningSummaryView learning,
    required int openTaskCount,
  }) {
    if (app == null) {
      widget.onOpenProjects();
      return;
    }
    if (openTaskCount > 0) {
      _scrollToTaskBoard();
      return;
    }
    unawaited(_openTaskDrafts(learning, app));
  }

  void _scrollToTaskBoard() {
    final context = _taskBoardKey.currentContext;
    if (context == null) return;
    Scrollable.ensureVisible(
      context,
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
      alignment: 0.04,
    );
  }

  void _scrollToRoadmap() {
    final context = _roadmapKey.currentContext;
    if (context == null) return;
    Scrollable.ensureVisible(
      context,
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
      alignment: 0.04,
    );
  }

  Future<void> _openTaskDrafts(
    CareerLearningSummaryView learning,
    CareerApplicationView? app,
  ) async {
    final messenger = ScaffoldMessenger.maybeOf(context);
    if (app == null) {
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('请先选择一个求职项目'),
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }
    if (_runningInlineAction != null) return;
    setState(() {
      _runningInlineAction = 'tasks';
      _completedInlineAction = null;
      _failedInlineAction = null;
      _inlineActionMessage = 'AI 正在分析当前岗位、匹配差距、短板和已有任务，生成可采纳的任务草案。';
    });
    late final List<_LearningTaskDraft> drafts;
    try {
      final generated =
          await ref.read(apiServiceProvider).generateLearningTaskDrafts(
                applicationId: app.applicationId,
                maxDrafts: 3,
              );
      drafts = generated.map(_LearningTaskDraft.fromApi).toList();
      if (!mounted) return;
      setState(() {
        _runningInlineAction = null;
        _failedInlineAction = null;
        _completedInlineAction = 'tasks';
        _inlineActionMessage = drafts.isEmpty
            ? 'AI 没有生成新的任务草案，可能是现有任务已经覆盖当前短板。'
            : 'AI 已生成 ${drafts.length} 个任务草案，请确认是否采纳。';
      });
      _clearInlineActionLater('tasks');
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _runningInlineAction = null;
        _completedInlineAction = null;
        _failedInlineAction = 'tasks';
        _inlineActionMessage = '生成任务草案失败：$error';
      });
      _clearInlineActionLater('tasks');
      messenger?.showSnackBar(
        SnackBar(
          content: Text('生成任务草案失败：$error'),
          duration: const Duration(seconds: 2),
        ),
      );
      return;
    }
    if (drafts.isEmpty) {
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('暂时没有新的学习任务草案'),
          duration: Duration(seconds: 2),
        ),
      );
      return;
    }
    final accepted = await _showLearningTaskDraftDialog(context, drafts);
    if (!mounted || accepted == null || accepted.isEmpty) return;
    try {
      for (final draft in accepted) {
        await ref.read(apiServiceProvider).createLearningTask(
              sourceSessionId: _learningSourceSessionId(),
              title: draft.title,
              description: draft.description,
              taskType: draft.taskType,
              priority: draft.priority,
              estimatedMinutes: draft.estimatedMinutes,
              evidenceRefs: draft.sourceRefs.isEmpty
                  ? _learningEvidenceRefs(app)
                  : draft.sourceRefs,
              skillTags: draft.skillTags,
              successCriteria: draft.successCriteria,
              progressNotes: '来源：AI 任务草案；${draft.reason}',
            );
      }
      await ref.read(careerWorkbenchProvider).refresh();
      messenger?.showSnackBar(
        SnackBar(
          content: Text('已采纳 ${accepted.length} 个学习任务草案'),
          duration: const Duration(seconds: 1),
        ),
      );
    } catch (error) {
      messenger?.showSnackBar(
        SnackBar(
          content: Text('采纳任务草案失败：$error'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  String _inlineActionRunningMessage(String surface) {
    return switch (surface) {
      'review' => '正在安排复盘，完成后会刷新复盘安排和学习资产。',
      'weakness' => '正在从匹配报告生成短板，完成后会刷新短板和任务。',
      _ => '正在生成学习任务草案，完成后会刷新学习任务和相关资产。',
    };
  }

  String _inlineActionCompletedMessage(
    CareerLearningSummaryView? updated, {
    required int beforeTasks,
    required int beforeWeaknesses,
    required int beforeReviews,
  }) {
    if (updated == null) {
      return '已完成，但暂时没有读取到刷新后的学习资产。可以稍后刷新本页确认。';
    }
    final taskDelta = math.max(0, updated.tasks.length - beforeTasks);
    final weaknessDelta =
        math.max(0, updated.weaknesses.length - beforeWeaknesses);
    final reviewDelta = math.max(0, updated.reviews.length - beforeReviews);
    final changes = <String>[
      if (taskDelta > 0) '$taskDelta 个学习任务',
      if (weaknessDelta > 0) '$weaknessDelta 个短板',
      if (reviewDelta > 0) '$reviewDelta 条复盘',
    ];
    if (changes.isEmpty) {
      return '已完成，本页已刷新，但没有检测到新增学习资产。可以查看会话结果，或用“新建任务”手动保存。';
    }
    return '已完成，已同步新增 ${changes.join('、')}。';
  }

  String _learningRecommendPrompt({
    required CareerLearningSummaryView learning,
    required CareerApplicationView app,
    required String surface,
  }) {
    final base =
        '求职项目 ${app.applicationId}；当前已有计划 ${learning.plans.length} 个、任务 ${learning.tasks.length} 个、短板 ${learning.weaknesses.length} 个、复盘 ${learning.reviews.length} 个。';
    if (surface == 'review') {
      return '请基于$base 为已完成或接近完成的学习任务安排一次复盘。优先创建可在学习计划页展示的复盘安排；如果缺少依据，请给出需要用户补充的信息。';
    }
    if (surface == 'weakness') {
      return '请基于$base 从当前 JD 匹配、简历诊断、面试复盘和已有任务中识别待处理短板。优先创建可在学习计划页展示的短板记录；如果短板已经明确，再给出可转成学习任务的依据。';
    }
    return '请基于$base 生成学习任务草案。请复用当前匹配报告、短板、复盘和已有任务，推荐 1 到 3 个最值得推进的学习任务，并尽量落到可展示的学习任务。';
  }

  _InlineLearningActionState _inlineActionState(String surface) {
    if (_runningInlineAction == surface) {
      return _InlineLearningActionState.running(_inlineActionMessage);
    }
    if (_failedInlineAction == surface) {
      return _InlineLearningActionState.failed(_inlineActionMessage);
    }
    if (_completedInlineAction == surface) {
      return _InlineLearningActionState.completed(_inlineActionMessage);
    }
    return const _InlineLearningActionState.idle();
  }

  void _clearInlineActionLater(String surface) {
    Future<void>.delayed(const Duration(seconds: 4), () {
      if (!mounted) return;
      if (_runningInlineAction == surface) return;
      if (_completedInlineAction != surface && _failedInlineAction != surface) {
        return;
      }
      setState(() {
        if (_completedInlineAction == surface) _completedInlineAction = null;
        if (_failedInlineAction == surface) _failedInlineAction = null;
        if (_completedInlineAction == null && _failedInlineAction == null) {
          _inlineActionMessage = '';
        }
      });
    });
  }

  Future<void> _sendCreateTask(CareerApplicationView? app) async {
    final draft = await _showLearningTaskCreateSheet(context);
    if (!mounted || draft == null) return;
    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      await ref.read(apiServiceProvider).createLearningTask(
            sourceSessionId: _learningSourceSessionId(),
            title: draft.title,
            description: draft.description,
            taskType: draft.taskType,
            priority: draft.priority,
            estimatedMinutes: draft.estimatedMinutes,
            evidenceRefs: draft.sourceRefs.isEmpty
                ? _learningEvidenceRefs(app)
                : draft.sourceRefs,
            skillTags: draft.skillTags,
            successCriteria: draft.successCriteria,
            progressNotes: '来源：用户主动添加',
          );
      await ref.read(careerWorkbenchProvider).refresh();
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('学习任务已创建'),
          duration: Duration(seconds: 1),
        ),
      );
    } catch (error) {
      messenger?.showSnackBar(
        SnackBar(
          content: Text('创建学习任务失败：$error'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
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
    final draft = await showLearningCheckinSheet(context, task: task);
    if (!mounted || draft == null) return;
    await _saveCheckIn(app, task, draft);
  }

  Future<void> _completeReview(CareerWorkbenchReviewView review) async {
    final summary = await showDialog<String>(
      context: context,
      builder: (context) => _CompleteReviewDialog(review: review),
    );
    if (!mounted || summary == null) return;

    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      await ref.read(careerWorkbenchProvider).completeLearningReview(
            reviewScheduleId: review.reviewScheduleId,
            summary: summary,
          );
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('复盘已完成，学习状态已刷新。'),
          duration: Duration(seconds: 1),
        ),
      );
    } catch (error) {
      messenger?.showSnackBar(
        SnackBar(
          content: Text('完成复盘失败：$error'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  Future<void> _saveCheckIn(
    CareerApplicationView app,
    CareerWorkbenchLearningTaskView task,
    LearningCheckinDraft draft,
  ) async {
    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      await ref.read(apiServiceProvider).createLearningCheckin(
            sourceSessionId: _learningSourceSessionId(),
            learningTaskId: task.learningTaskId,
            learningPlanId: task.learningPlanId,
            minutesSpent: draft.minutes,
            progressState: _checkinProgressState(draft.nextState),
            summary: draft.summary,
            blockers: _splitBlockers(draft.blockers),
            nextAction: draft.nextAction,
            evidenceRefs: _learningEvidenceRefs(app, extra: [
              task.learningTaskId,
            ]),
          );
      final nextState = draft.nextState.trim();
      if (nextState.isNotEmpty) {
        await ref.read(apiServiceProvider).updateLearningTaskState(
              learningTaskId: task.learningTaskId,
              state: nextState,
              completedAt: nextState == 'done' ? DateTime.now() : null,
            );
      }
      await ref.read(careerWorkbenchProvider).refresh();
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('学习进度已保存'),
          duration: Duration(seconds: 1),
        ),
      );
    } catch (error) {
      messenger?.showSnackBar(
        SnackBar(
          content: Text('保存学习进度失败：$error'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  Future<void> _moveLearningTaskState(
    CareerWorkbenchLearningTaskView task,
    String targetState,
  ) async {
    if (_taskLaneState(task.state) == targetState) return;
    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      await ref.read(apiServiceProvider).updateLearningTaskState(
            learningTaskId: task.learningTaskId,
            state: targetState,
            completedAt: targetState == 'done' ? DateTime.now() : null,
          );
      await ref.read(careerWorkbenchProvider).refresh();
      messenger?.showSnackBar(
        SnackBar(
          content: Text('已移动到${_taskLaneTitle(targetState)}'),
          duration: const Duration(seconds: 1),
        ),
      );
    } catch (error) {
      messenger?.showSnackBar(
        SnackBar(
          content: Text('更新任务状态失败：$error'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  Future<void> _showTaskDetailSheet({
    required CareerApplicationView? app,
    required CareerLearningSummaryView learning,
    required CareerWorkbenchLearningTaskView task,
  }) async {
    final action = await _showLearningTaskDetailSheet(
      context,
      task,
      onAiDecompose: () => _sendTaskAgentAdvice(learning, app, task),
    );
    if (!mounted || action == null) return;
    switch (action) {
      case _LearningTaskDetailAction.checkIn:
        await _showCheckInSheet(app, task);
      case _LearningTaskDetailAction.archive:
        await _archiveLearningTask(task);
    }
  }

  Future<void> _archiveLearningTask(
    CareerWorkbenchLearningTaskView task,
  ) async {
    final confirmed = await _confirmArchiveLearningTask(context, task);
    if (!mounted || confirmed != true) return;
    final messenger = ScaffoldMessenger.maybeOf(context);
    try {
      await ref
          .read(apiServiceProvider)
          .archiveLearningTask(learningTaskId: task.learningTaskId);
      await ref.read(careerWorkbenchProvider).refresh();
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('学习任务已移除'),
          duration: Duration(seconds: 1),
        ),
      );
    } catch (error) {
      messenger?.showSnackBar(
        SnackBar(
          content: Text('移除学习任务失败：$error'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  Future<String?> _sendTaskAgentAdvice(
    CareerLearningSummaryView learning,
    CareerApplicationView? app,
    CareerWorkbenchLearningTaskView task,
  ) async {
    final sender = widget.onSendPrompt;
    final messenger = ScaffoldMessenger.maybeOf(context);
    if (sender == null || app == null) {
      messenger?.showSnackBar(
        const SnackBar(
          content: Text('请先选择一个求职项目'),
          duration: Duration(seconds: 2),
        ),
      );
      return null;
    }
    if (_runningInlineAction != null) return null;
    final messageCountBefore = ref.read(chatProvider).messages.length;
    final prompt =
        '请基于求职项目 ${app.applicationId}，只针对学习任务 ${task.learningTaskId} 做任务拆解。'
        '任务标题：${task.title}。任务说明：${task.description}。成功标准：${task.successCriteria.join('；')}。'
        '当前状态：${_taskStateLabel(task.state)}。当前学习路线 ${learning.plans.length} 条、任务 ${learning.tasks.length} 个。'
        '请输出下一步行动、子步骤、练习方式、预计耗时和验收标准；如果需要保存，请尽量更新或创建可在学习计划页展示的学习资产。';
    try {
      await sender(prompt);
      final error = ref.read(chatProvider).error;
      if (error != null && error.trim().isNotEmpty) {
        throw Exception(error);
      }
      await ref.read(careerWorkbenchProvider).refresh();
      if (!mounted) return null;
      final answer = _latestAssistantAnswerAfter(messageCountBefore);
      return answer?.trim().isNotEmpty == true
          ? answer!.trim()
          : '任务拆解已完成，本页已刷新。';
    } catch (error) {
      if (!mounted) return null;
      rethrow;
    }
  }

  String? _latestAssistantAnswerAfter(int messageCountBefore) {
    final messages = ref.read(chatProvider).messages;
    final start = messageCountBefore.clamp(0, messages.length);
    for (final message in messages.skip(start).toList().reversed) {
      if (!message.isUser && message.content.trim().isNotEmpty) {
        return message.content;
      }
    }
    for (final message in messages.reversed) {
      if (!message.isUser && message.content.trim().isNotEmpty) {
        return message.content;
      }
    }
    return null;
  }

  String _learningSourceSessionId() {
    final current = ref.read(chatProvider).sessionId?.trim();
    if (current != null && current.isNotEmpty) return current;
    return 'sess_ui_learning_${DateTime.now().millisecondsSinceEpoch}';
  }

  List<String> _learningEvidenceRefs(
    CareerApplicationView? app, {
    List<String> extra = const [],
  }) {
    return [
      if (app?.applicationId.trim().isNotEmpty == true)
        app!.applicationId.trim(),
      ...extra
          .where((item) => item.trim().isNotEmpty)
          .map((item) => item.trim()),
    ];
  }
}

class _LearningTaskDraft {
  final String title;
  final String description;
  final String taskType;
  final String priority;
  final int estimatedMinutes;
  final List<String> skillTags;
  final List<String> successCriteria;
  final String reason;
  final List<String> sourceRefs;

  const _LearningTaskDraft({
    required this.title,
    required this.description,
    this.taskType = 'custom',
    required this.priority,
    required this.estimatedMinutes,
    this.skillTags = const [],
    this.successCriteria = const [],
    this.reason = '',
    this.sourceRefs = const [],
  });

  factory _LearningTaskDraft.fromApi(LearningTaskDraftView view) {
    return _LearningTaskDraft(
      title: view.title,
      description: view.description,
      taskType: view.taskType,
      priority: view.priority,
      estimatedMinutes: view.estimatedMinutes,
      skillTags: view.skillTags,
      successCriteria: view.successCriteria,
      reason: view.reason,
      sourceRefs: view.sourceRefs,
    );
  }

  _LearningTaskDraft copyWith({
    String? title,
    String? description,
    String? taskType,
    String? priority,
    int? estimatedMinutes,
    List<String>? skillTags,
    List<String>? successCriteria,
    String? reason,
    List<String>? sourceRefs,
  }) {
    return _LearningTaskDraft(
      title: title ?? this.title,
      description: description ?? this.description,
      taskType: taskType ?? this.taskType,
      priority: priority ?? this.priority,
      estimatedMinutes: estimatedMinutes ?? this.estimatedMinutes,
      skillTags: skillTags ?? this.skillTags,
      successCriteria: successCriteria ?? this.successCriteria,
      reason: reason ?? this.reason,
      sourceRefs: sourceRefs ?? this.sourceRefs,
    );
  }
}

Future<List<_LearningTaskDraft>?> _showLearningTaskDraftDialog(
  BuildContext context,
  List<_LearningTaskDraft> initialDrafts,
) {
  var drafts = [...initialDrafts];
  var accepted = List<bool>.filled(drafts.length, false);
  var ignored = List<bool>.filled(drafts.length, false);
  return showDialog<List<_LearningTaskDraft>>(
    context: context,
    barrierDismissible: false,
    builder: (dialogContext) {
      return StatefulBuilder(
        builder: (dialogContext, setDialogState) {
          final selectable = [
            for (var i = 0; i < drafts.length; i++)
              if (!ignored[i]) i,
          ];
          final selected = [
            for (final i in selectable)
              if (accepted[i]) drafts[i],
          ];
          final canSubmit = selectable.isNotEmpty;
          Future<void> editDraft(int index) async {
            final edited = await _showLearningTaskCreateSheet(
              dialogContext,
              initialDraft: drafts[index],
              title: '编辑任务草案',
              subtitle: '调整标题、说明、优先级和预计耗时后，回到草案列表继续采纳。',
              submitLabel: '保存草案',
            );
            if (edited == null || !dialogContext.mounted) return;
            setDialogState(() {
              drafts[index] = edited;
              ignored[index] = false;
              accepted[index] = true;
            });
          }

          return Dialog(
            insetPadding:
                const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
            backgroundColor: Colors.transparent,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 900, maxHeight: 760),
              child: ProductCard(
                padding: const EdgeInsets.fromLTRB(24, 22, 24, 24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.auto_awesome_rounded,
                          size: 20,
                          color: ProductColors.purple,
                        ),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'AI 生成任务草案',
                                style: AppTheme.ts(
                                  fontSize: 18,
                                  fontWeight: FontWeight.w900,
                                  color: ProductColors.text,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Text(
                                '基于你的目标岗位、当前学习路线、能力短板与已有任务，AI 为你生成以下优先建议任务草案，你可以采纳、编辑或忽略这些任务。',
                                style: AppTheme.ts(
                                  fontSize: 12.8,
                                  height: 1.55,
                                  color: ProductColors.textSecondary,
                                  fontWeight: FontWeight.w700,
                                ),
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: '关闭',
                          onPressed: () => Navigator.of(dialogContext).pop(),
                          icon: const Icon(Icons.close_rounded),
                          color: ProductColors.textSecondary,
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    Flexible(
                      child: ListView.separated(
                        shrinkWrap: true,
                        itemCount: drafts.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 12),
                        itemBuilder: (context, index) {
                          return _LearningTaskDraftCard(
                            index: index + 1,
                            draft: drafts[index],
                            accepted: accepted[index],
                            ignored: ignored[index],
                            onAccept: () => setDialogState(() {
                              accepted[index] = !accepted[index];
                              ignored[index] = false;
                            }),
                            onEdit: () => unawaited(editDraft(index)),
                            onIgnore: () => setDialogState(() {
                              ignored[index] = !ignored[index];
                              if (ignored[index]) accepted[index] = false;
                            }),
                          );
                        },
                      ),
                    ),
                    const SizedBox(height: 20),
                    Row(
                      children: [
                        const Spacer(),
                        SizedBox(
                          width: 220,
                          height: 44,
                          child: ElevatedButton.icon(
                            onPressed: canSubmit
                                ? () => Navigator.of(dialogContext).pop(
                                      selected.isNotEmpty
                                          ? selected
                                          : selectable
                                              .map((index) => drafts[index])
                                              .toList(),
                                    )
                                : null,
                            icon: const Icon(
                              Icons.check_circle_outline_rounded,
                              size: 17,
                            ),
                            label: Text(
                              selected.isNotEmpty ? '采纳选中' : '采纳全部',
                            ),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: ProductColors.primary,
                              foregroundColor: Colors.white,
                              elevation: 0,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                              textStyle: AppTheme.ts(
                                fontSize: 13,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        SizedBox(
                          width: 220,
                          height: 44,
                          child: OutlinedButton(
                            onPressed: () => Navigator.of(dialogContext).pop(),
                            style: _outlineButtonStyle(),
                            child: const Text('关闭'),
                          ),
                        ),
                        const Spacer(),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      );
    },
  );
}

class _LearningTaskDraftCard extends StatelessWidget {
  final int index;
  final _LearningTaskDraft draft;
  final bool accepted;
  final bool ignored;
  final VoidCallback onAccept;
  final VoidCallback onEdit;
  final VoidCallback onIgnore;

  const _LearningTaskDraftCard({
    required this.index,
    required this.draft,
    required this.accepted,
    required this.ignored,
    required this.onAccept,
    required this.onEdit,
    required this.onIgnore,
  });

  @override
  Widget build(BuildContext context) {
    final priorityTone = careerPriorityTone(draft.priority);
    return AnimatedOpacity(
      duration: const Duration(milliseconds: 140),
      opacity: ignored ? 0.48 : 1,
      child: Container(
        padding: const EdgeInsets.fromLTRB(18, 16, 16, 16),
        decoration: BoxDecoration(
          color: ProductColors.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: accepted
                ? ProductColors.primary.withValues(alpha: 0.32)
                : ProductColors.border,
          ),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.025),
              blurRadius: 14,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < 640;
            final body = Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    ProductTag(
                      label: index.toString().padLeft(2, '0'),
                      tone: ProductTone.purple,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        draft.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 15.5,
                          height: 1.28,
                          fontWeight: FontWeight.w900,
                          color: ProductColors.text,
                        ),
                      ),
                    ),
                    ProductTag(
                      label: '${careerPriorityLabel(draft.priority)}优先级',
                      tone: priorityTone,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  '为什么推荐',
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  draft.reason.isEmpty ? draft.description : draft.reason,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12.2,
                    height: 1.48,
                    color: ProductColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 14),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    ProductTag(
                      label: '预计 ${draft.estimatedMinutes} 分钟',
                      tone: ProductTone.neutral,
                    ),
                    const ProductTag(label: '相关技能', tone: ProductTone.neutral),
                    for (final tag in draft.skillTags.take(5))
                      ProductTag(label: tag, tone: ProductTone.neutral),
                  ],
                ),
              ],
            );
            final actions = SizedBox(
              width: compact ? double.infinity : 148,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SizedBox(
                    height: 38,
                    child: ElevatedButton.icon(
                      onPressed: ignored ? null : onAccept,
                      icon: Icon(
                        accepted
                            ? Icons.check_circle_rounded
                            : Icons.check_circle_outline_rounded,
                        size: 16,
                      ),
                      label: Text(accepted ? '已采纳' : '采纳'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: ProductColors.primary,
                        foregroundColor: Colors.white,
                        disabledBackgroundColor:
                            ProductColors.textMuted.withValues(alpha: 0.18),
                        disabledForegroundColor: ProductColors.textMuted,
                        elevation: 0,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                        textStyle: AppTheme.ts(
                          fontSize: 12.2,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 9),
                  SizedBox(
                    height: 36,
                    child: OutlinedButton.icon(
                      onPressed: ignored ? null : onEdit,
                      icon: const Icon(Icons.edit_outlined, size: 15),
                      label: const Text('编辑'),
                      style: _outlineButtonStyle(),
                    ),
                  ),
                  const SizedBox(height: 9),
                  SizedBox(
                    height: 36,
                    child: OutlinedButton.icon(
                      onPressed: onIgnore,
                      icon: Icon(
                        ignored ? Icons.undo_rounded : Icons.close_rounded,
                        size: 15,
                      ),
                      label: Text(ignored ? '恢复' : '忽略'),
                      style: _outlineButtonStyle(
                        foregroundColor: ignored
                            ? ProductColors.primary
                            : ProductColors.text,
                      ),
                    ),
                  ),
                ],
              ),
            );
            if (compact) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  body,
                  const SizedBox(height: 14),
                  actions,
                ],
              );
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: body),
                const SizedBox(width: 18),
                Container(
                  width: 1,
                  height: 116,
                  color: ProductColors.border,
                ),
                const SizedBox(width: 18),
                actions,
              ],
            );
          },
        ),
      ),
    );
  }
}

Future<_LearningTaskDraft?> _showLearningTaskCreateSheet(
  BuildContext context, {
  _LearningTaskDraft? initialDraft,
  String title = '新建学习任务',
  String subtitle = '直接保存为学习任务；需要系统推导时再使用“AI 生成任务草案”。',
  String submitLabel = '保存任务',
}) {
  final titleController =
      TextEditingController(text: initialDraft?.title ?? '');
  final descriptionController =
      TextEditingController(text: initialDraft?.description ?? '');
  final minutesController = TextEditingController(
    text: (initialDraft?.estimatedMinutes ?? 0) > 0
        ? initialDraft!.estimatedMinutes.toString()
        : '',
  );
  var priority = initialDraft?.priority ?? 'medium';
  var error = '';
  _LearningTaskDraft? draft;

  return showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (sheetContext) {
      return StatefulBuilder(
        builder: (context, setSheetState) {
          void submit() {
            final title = titleController.text.trim();
            if (title.isEmpty) {
              setSheetState(() => error = '先写一个任务标题');
              return;
            }
            final rawMinutes = minutesController.text.trim();
            final minutes = rawMinutes.isEmpty
                ? 0
                : int.tryParse(rawMinutes.replaceAll(RegExp(r'[^0-9]'), '')) ??
                    0;
            draft = _LearningTaskDraft(
              title: title.trim(),
              description: descriptionController.text.trim(),
              taskType: initialDraft?.taskType ?? 'custom',
              priority: priority,
              estimatedMinutes: minutes,
              skillTags: initialDraft?.skillTags ?? const [],
              successCriteria: initialDraft?.successCriteria ?? const [],
              reason: initialDraft?.reason ?? '',
              sourceRefs: initialDraft?.sourceRefs ?? const [],
            );
            Navigator.of(sheetContext).pop();
          }

          final bottom = MediaQuery.viewInsetsOf(context).bottom;
          return Dialog(
            insetPadding:
                const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
            backgroundColor: Colors.transparent,
            child: Padding(
              padding: EdgeInsets.only(bottom: bottom),
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: 640,
                  maxHeight: MediaQuery.sizeOf(sheetContext).height * 0.88,
                ),
                child: SingleChildScrollView(
                  child: ProductCard(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const ProductIconTile(
                              icon: Icons.add_task_rounded,
                              tone: ProductTone.primary,
                              size: 36,
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    title,
                                    style: AppTheme.ts(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w900,
                                      color: ProductColors.text,
                                    ),
                                  ),
                                  const SizedBox(height: 3),
                                  Text(
                                    subtitle,
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
                              onPressed: () => Navigator.of(sheetContext).pop(),
                              icon: const Icon(Icons.close_rounded),
                              color: ProductColors.textSecondary,
                            ),
                          ],
                        ),
                        const SizedBox(height: 14),
                        TextField(
                          key: const Key('learning_task_title_field'),
                          controller: titleController,
                          decoration: _learningInputDecoration('任务标题'),
                          style: AppTheme.ts(
                            fontSize: 12.8,
                            fontWeight: FontWeight.w800,
                            color: ProductColors.text,
                          ),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          key: const Key('learning_task_description_field'),
                          controller: descriptionController,
                          minLines: 3,
                          maxLines: 5,
                          decoration: _learningInputDecoration('任务说明（可选）'),
                          style: AppTheme.ts(
                            fontSize: 12.6,
                            height: 1.48,
                            color: ProductColors.text,
                          ),
                        ),
                        const SizedBox(height: 10),
                        LayoutBuilder(
                          builder: (context, constraints) {
                            final priorityField =
                                DropdownButtonFormField<String>(
                              initialValue: priority,
                              decoration: _learningInputDecoration('优先级'),
                              items: const [
                                DropdownMenuItem(
                                    value: 'high', child: Text('高')),
                                DropdownMenuItem(
                                  value: 'medium',
                                  child: Text('中'),
                                ),
                                DropdownMenuItem(
                                    value: 'low', child: Text('低')),
                              ],
                              onChanged: (value) => setSheetState(() {
                                priority = value ?? priority;
                              }),
                            );
                            final minutesField = TextField(
                              key: const Key('learning_task_minutes_field'),
                              controller: minutesController,
                              keyboardType: TextInputType.number,
                              decoration: _learningInputDecoration('预计分钟数'),
                              style: AppTheme.ts(
                                fontSize: 12.6,
                                color: ProductColors.text,
                              ),
                            );
                            if (constraints.maxWidth < 560) {
                              return Column(
                                children: [
                                  priorityField,
                                  const SizedBox(height: 10),
                                  minutesField,
                                ],
                              );
                            }
                            return Row(
                              children: [
                                Expanded(child: priorityField),
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
                              fontWeight: FontWeight.w800,
                              color: ProductColors.danger,
                            ),
                          ),
                        ],
                        const SizedBox(height: 16),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            TextButton(
                              onPressed: () => Navigator.of(sheetContext).pop(),
                              child: const Text('取消'),
                            ),
                            const SizedBox(width: 8),
                            FilledButton.icon(
                              onPressed: submit,
                              icon: const Icon(Icons.check_rounded, size: 16),
                              label: Text(submitLabel),
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
          );
        },
      );
    },
  ).whenComplete(() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      titleController.dispose();
      descriptionController.dispose();
      minutesController.dispose();
    });
  }).then((_) => draft);
}

InputDecoration _learningInputDecoration(String label) {
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

List<String> _splitBlockers(String value) {
  return value
      .split(RegExp(r'[\n；;]+'))
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList(growable: false);
}

String _checkinProgressState(String nextState) {
  return switch (nextState.trim()) {
    'done' => 'completed',
    'blocked' => 'blocked',
    'skipped' => 'skipped',
    _ => 'in_progress',
  };
}

class _LearningHero extends StatelessWidget {
  final CareerApplicationView? app;
  final CareerLearningSummaryView learning;
  final int progress;
  final bool loading;
  final VoidCallback onPrimary;
  final VoidCallback onRoadmap;

  const _LearningHero({
    required this.app,
    required this.learning,
    required this.progress,
    required this.loading,
    required this.onPrimary,
    required this.onRoadmap,
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
      padding: const EdgeInsets.fromLTRB(24, 14, 24, 14),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            ProductColors.primarySoft.withValues(alpha: 0.86),
            ProductColors.surface,
            ProductColors.infoSoft.withValues(alpha: 0.38),
          ],
        ),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(
          color: ProductColors.primary.withValues(alpha: 0.18),
        ),
        boxShadow: [
          BoxShadow(
            color: ProductColors.primary.withValues(alpha: 0.08),
            blurRadius: 24,
            offset: const Offset(0, 12),
          ),
        ],
      ),
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
                      fontSize: compact ? 21 : 22,
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
              const SizedBox(height: 7),
              Text(
                subtitle,
                maxLines: compact ? 4 : 1,
                overflow: TextOverflow.ellipsis,
                style: AppTheme.ts(
                  fontSize: 13.5,
                  height: 1.45,
                  fontWeight: FontWeight.w700,
                  color: ProductColors.textSecondary,
                ),
              ),
              const SizedBox(height: 9),
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
              const SizedBox(height: 10),
              Wrap(
                spacing: 9,
                runSpacing: 8,
                children: [
                  SizedBox(
                    height: 36,
                    child: ElevatedButton.icon(
                      onPressed: onPrimary,
                      icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                      label: Text(
                        app == null
                            ? '选择求职项目'
                            : learning.openTaskCount > 0
                                ? '继续今日任务'
                                : 'AI 生成任务草案',
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
                  SizedBox(
                    height: 36,
                    child: OutlinedButton.icon(
                      onPressed: onRoadmap,
                      icon: const Icon(Icons.route_outlined, size: 16),
                      label: const Text('查看学习路线'),
                      style: _outlineButtonStyle(),
                    ),
                  ),
                ],
              ),
            ],
          );
          final insight = Container(
            padding: const EdgeInsets.fromLTRB(15, 13, 15, 13),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.72),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: ProductColors.borderStrong),
            ),
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
            label: '整体进度',
            suffix: '%',
            size: compact ? 96 : 112,
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
              const SizedBox(width: 26),
              ring,
              const SizedBox(width: 26),
              SizedBox(width: 320, child: insight),
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
    return Container(
      height: 50,
      padding: const EdgeInsets.symmetric(horizontal: 14),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          Text(
            '关联求职项目',
            style: AppTheme.ts(
              fontSize: 12.5,
              fontWeight: FontWeight.w900,
              color: ProductColors.text,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: apps.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, index) {
                final item = apps[index];
                final selected =
                    item.application.applicationId == selectedId?.trim();
                return Align(
                  alignment: Alignment.centerLeft,
                  child: _ProjectChip(
                    summary: item,
                    selected: selected,
                    loading: provider
                        .isApplicationLoading(item.application.applicationId),
                    onTap: () => unawaited(
                      provider
                          .selectApplication(item.application.applicationId),
                    ),
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
  final CareerLearningSummaryView learning;
  final int overallProgress;

  const _LearningPlanSection({
    required this.learning,
    required this.overallProgress,
  });

  @override
  Widget build(BuildContext context) {
    final visible = [...learning.plans]
      ..sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    final roadmap = _buildRoadmapSteps(learning, overallProgress);
    final trailing = visible.isEmpty
        ? const ProductTag(label: '待生成', tone: ProductTone.neutral)
        : ProductTag(label: '${visible.length} 条路线', tone: ProductTone.purple);
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const ProductIconTile(
                icon: Icons.route_outlined,
                tone: ProductTone.purple,
                size: 30,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '学习路线',
                      style: AppTheme.ts(
                        fontSize: 13.8,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '你的学习阶段与当前进度。',
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
              trailing,
            ],
          ),
          const SizedBox(height: 8),
          LayoutBuilder(
            builder: (context, constraints) {
              final compact = constraints.maxWidth < 780;
              if (compact) {
                return Column(
                  children: [
                    for (final step in roadmap) ...[
                      _RoadmapStepCard(step: step, compact: true),
                      if (step != roadmap.last) const SizedBox(height: 9),
                    ],
                  ],
                );
              }
              return Row(
                children: [
                  for (var index = 0; index < roadmap.length; index++) ...[
                    Expanded(
                      child: _RoadmapStepCard(step: roadmap[index]),
                    ),
                    if (index < roadmap.length - 1) ...[
                      const SizedBox(width: 7),
                      Icon(
                        Icons.arrow_forward_rounded,
                        size: 16,
                        color: ProductColors.textMuted.withValues(alpha: 0.72),
                      ),
                      const SizedBox(width: 7),
                    ],
                  ],
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

class _RoadmapStepData {
  final int index;
  final String title;
  final String subtitle;
  final int progress;
  final ProductTone tone;

  const _RoadmapStepData({
    required this.index,
    required this.title,
    required this.subtitle,
    required this.progress,
    required this.tone,
  });
}

class _RoadmapStepCard extends StatelessWidget {
  final _RoadmapStepData step;
  final bool compact;

  const _RoadmapStepCard({
    required this.step,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(step.tone);
    final done = step.progress >= 100;
    final active = step.progress > 0 && step.progress < 100;
    return Container(
      constraints: BoxConstraints(minHeight: compact ? 68 : 70),
      padding: const EdgeInsets.fromLTRB(9, 8, 9, 8),
      decoration: BoxDecoration(
        color: active
            ? style.soft.withValues(alpha: 0.58)
            : done
                ? ProductColors.primarySoft.withValues(alpha: 0.48)
                : ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(
          color: active || done
              ? style.color.withValues(alpha: 0.18)
              : ProductColors.border,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 25,
                height: 24,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: done ? ProductColors.primary : style.soft,
                  borderRadius: BorderRadius.circular(999),
                  border: Border.all(color: style.color.withValues(alpha: 0.2)),
                ),
                child: done
                    ? const Icon(
                        Icons.check_rounded,
                        size: 15,
                        color: Colors.white,
                      )
                    : Text(
                        step.index.toString().padLeft(2, '0'),
                        style: AppTheme.ts(
                          fontSize: 10.5,
                          fontWeight: FontWeight.w900,
                          color: style.color,
                        ),
                      ),
              ),
              const SizedBox(width: 7),
              Expanded(
                child: Text(
                  step.title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            step.subtitle,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 10.6,
              height: 1.25,
              color: ProductColors.textSecondary,
            ),
          ),
          const SizedBox(height: 5),
          ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: step.progress.clamp(0, 100).toDouble() / 100,
              minHeight: 4.5,
              color: style.color,
              backgroundColor: ProductColors.border.withValues(alpha: 0.66),
            ),
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              Text(
                done
                    ? '已完成'
                    : active
                        ? '进行中'
                        : '未开始',
                style: AppTheme.ts(
                  fontSize: 10.2,
                  fontWeight: FontWeight.w900,
                  color: style.color,
                ),
              ),
              const Spacer(),
              Text(
                '${step.progress}%',
                style: AppTheme.ts(
                  fontSize: 10.2,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.textSecondary,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _LearningTaskBoard extends StatelessWidget {
  final List<CareerWorkbenchLearningTaskView> tasks;
  final _InlineLearningActionState action;
  final ValueChanged<CareerWorkbenchLearningTaskView> onOpenDetails;
  final ValueChanged<CareerWorkbenchLearningTaskView> onCheckIn;
  final VoidCallback onCreateTask;
  final VoidCallback onGenerateTaskDrafts;
  final Future<void> Function(
      CareerWorkbenchLearningTaskView task, String state) onMoveTask;

  const _LearningTaskBoard({
    required this.tasks,
    required this.action,
    required this.onOpenDetails,
    required this.onCheckIn,
    required this.onCreateTask,
    required this.onGenerateTaskDrafts,
    required this.onMoveTask,
  });

  @override
  Widget build(BuildContext context) {
    final doing = tasks.where((task) => task.state == 'doing').toList();
    final todo = tasks
        .where((task) => task.state != 'doing' && _isOpenTask(task))
        .toList();
    final done = tasks.where(_isDoneTask).toList();
    final lanes = [
      _TaskLaneData('进行中', doing, ProductTone.primary, 'doing'),
      _TaskLaneData('待推进', todo, ProductTone.info, 'todo'),
      _TaskLaneData('已完成', done, ProductTone.neutral, 'done'),
    ];
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const ProductIconTile(
                icon: Icons.fact_check_outlined,
                tone: ProductTone.info,
                size: 32,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '学习任务',
                      style: AppTheme.ts(
                        fontSize: 15,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      tasks.isEmpty ? '暂无任务' : '任务看板，聚焦当前优先级，持续推进。',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                alignment: WrapAlignment.end,
                children: [
                  SizedBox(
                    height: 34,
                    child: OutlinedButton.icon(
                      onPressed: action.isRunning ? null : onGenerateTaskDrafts,
                      icon: const Icon(Icons.auto_awesome_rounded, size: 15),
                      label: const Text('AI 生成任务草案'),
                      style: _outlineButtonStyle(),
                    ),
                  ),
                  SizedBox(
                    height: 34,
                    child: ElevatedButton.icon(
                      onPressed: onCreateTask,
                      icon: const Icon(Icons.add_rounded, size: 15),
                      label: const Text('新建'),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: ProductColors.primary,
                        foregroundColor: Colors.white,
                        elevation: 0,
                        padding: const EdgeInsets.symmetric(horizontal: 12),
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
              ),
            ],
          ),
          if (action.isVisible) ...[
            const SizedBox(height: 12),
            _InlineLearningActionNotice(action: action),
          ],
          const SizedBox(height: 8),
          if (tasks.isEmpty)
            const _EmptyLearningMessage(
              message: '还没有学习任务。可以从岗位差距、面试复盘或手动输入创建。',
            )
          else
            LayoutBuilder(
              builder: (context, constraints) {
                if (constraints.maxWidth >= 920) {
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        flex: 10,
                        child: _TaskLane(
                          lane: lanes[0],
                          onOpenDetails: onOpenDetails,
                          onCheckIn: onCheckIn,
                          onMoveTask: onMoveTask,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        flex: 13,
                        child: _TaskLane(
                          lane: lanes[1],
                          onOpenDetails: onOpenDetails,
                          onCheckIn: onCheckIn,
                          onMoveTask: onMoveTask,
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        flex: 10,
                        child: _TaskLane(
                          lane: lanes[2],
                          onOpenDetails: onOpenDetails,
                          onCheckIn: onCheckIn,
                          onMoveTask: onMoveTask,
                        ),
                      ),
                    ],
                  );
                }
                final twoColumns = constraints.maxWidth >= 640;
                final width = twoColumns
                    ? (constraints.maxWidth - 12) / 2
                    : constraints.maxWidth;
                return Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: [
                    for (final lane in lanes)
                      SizedBox(
                        width: width,
                        child: _TaskLane(
                          lane: lane,
                          onOpenDetails: onOpenDetails,
                          onCheckIn: onCheckIn,
                          onMoveTask: onMoveTask,
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

class _TaskLane extends StatelessWidget {
  final _TaskLaneData lane;
  final ValueChanged<CareerWorkbenchLearningTaskView> onOpenDetails;
  final ValueChanged<CareerWorkbenchLearningTaskView> onCheckIn;
  final Future<void> Function(
      CareerWorkbenchLearningTaskView task, String state) onMoveTask;

  const _TaskLane({
    required this.lane,
    required this.onOpenDetails,
    required this.onCheckIn,
    required this.onMoveTask,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(lane.tone);
    final doneLane = lane.title == '已完成';
    final maxVisibleTasks = doneLane ? 5 : 2;
    final visibleTasks = lane.tasks.take(maxVisibleTasks).toList();
    final hiddenTaskCount =
        math.max(0, lane.tasks.length - visibleTasks.length);
    return DragTarget<CareerWorkbenchLearningTaskView>(
      onWillAcceptWithDetails: (details) =>
          _taskLaneState(details.data.state) != lane.targetState,
      onAcceptWithDetails: (details) =>
          unawaited(onMoveTask(details.data, lane.targetState)),
      builder: (context, candidateData, rejectedData) {
        final accepting = candidateData.isNotEmpty;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          constraints: const BoxConstraints(minHeight: 136),
          padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                style.soft.withValues(alpha: doneLane ? 0.38 : 0.56),
                ProductColors.surface,
              ],
              stops: const [0, 0.42],
            ),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: accepting
                  ? style.color.withValues(alpha: 0.58)
                  : style.color.withValues(alpha: 0.12),
              width: accepting ? 1.4 : 1,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      accepting ? '松开移动到${lane.title}' : lane.title,
                      style: AppTheme.ts(
                        fontSize: 13.2,
                        fontWeight: FontWeight.w900,
                        color: doneLane ? ProductColors.primary : style.color,
                      ),
                    ),
                  ),
                  ProductTag(label: '${lane.tasks.length}', tone: lane.tone),
                ],
              ),
              const SizedBox(height: 7),
              if (lane.tasks.isEmpty)
                Container(
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                  decoration: BoxDecoration(
                    color: accepting
                        ? style.soft.withValues(alpha: 0.72)
                        : ProductColors.surfaceSoft,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: ProductColors.border),
                  ),
                  child: Text(
                    accepting ? '拖到这里更新状态' : '暂无',
                    style: AppTheme.ts(
                      fontSize: 12,
                      color: accepting ? style.color : ProductColors.textMuted,
                      fontWeight: accepting ? FontWeight.w800 : FontWeight.w400,
                    ),
                  ),
                )
              else ...[
                for (var index = 0; index < visibleTasks.length; index++) ...[
                  _DraggableTaskCard(
                    task: visibleTasks[index],
                    doneLane: doneLane,
                    onOpenDetails: () => onOpenDetails(visibleTasks[index]),
                    onCheckIn: () => onCheckIn(visibleTasks[index]),
                    onStart: () =>
                        unawaited(onMoveTask(visibleTasks[index], 'doing')),
                  ),
                  if (index < visibleTasks.length - 1)
                    const SizedBox(height: 6),
                ],
                if (hiddenTaskCount > 0) ...[
                  const SizedBox(height: 7),
                  Center(
                    child: TextButton.icon(
                      onPressed: () => unawaited(
                        _showTaskLaneTaskListSheet(
                          context,
                          lane: lane,
                          onOpenDetails: onOpenDetails,
                          onCheckIn: onCheckIn,
                          onMoveTask: onMoveTask,
                        ),
                      ),
                      icon: const Icon(Icons.view_list_rounded, size: 14),
                      label: Text('查看全部 ${lane.tasks.length} 个${lane.title}任务'),
                      style: TextButton.styleFrom(
                        foregroundColor: style.color,
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 4,
                        ),
                        minimumSize: const Size(0, 30),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        textStyle: AppTheme.ts(
                          fontSize: 11.2,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                  ),
                ],
              ],
            ],
          ),
        );
      },
    );
  }
}

Future<void> _showTaskLaneTaskListSheet(
  BuildContext context, {
  required _TaskLaneData lane,
  required ValueChanged<CareerWorkbenchLearningTaskView> onOpenDetails,
  required ValueChanged<CareerWorkbenchLearningTaskView> onCheckIn,
  required Future<void> Function(
    CareerWorkbenchLearningTaskView task,
    String state,
  ) onMoveTask,
}) {
  final doneLane = lane.title == '已完成';
  return showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (sheetContext) {
      void closeThen(VoidCallback action) {
        Navigator.of(sheetContext).pop();
        action();
      }

      return Dialog(
        insetPadding: const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
        backgroundColor: Colors.transparent,
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxWidth: 760,
            maxHeight: MediaQuery.sizeOf(sheetContext).height * 0.82,
          ),
          child: ProductCard(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    ProductIconTile(
                      icon: doneLane
                          ? Icons.verified_outlined
                          : Icons.fact_check_outlined,
                      tone: lane.tone,
                      size: 34,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${lane.title}任务',
                            style: AppTheme.ts(
                              fontSize: 16,
                              fontWeight: FontWeight.w900,
                              color: ProductColors.text,
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            '共 ${lane.tasks.length} 个，点击任务可查看详情。',
                            style: AppTheme.ts(
                              fontSize: 11.5,
                              color: ProductColors.textMuted,
                            ),
                          ),
                        ],
                      ),
                    ),
                    ProductTag(
                      label: '${lane.tasks.length}',
                      tone: lane.tone,
                    ),
                    const SizedBox(width: 4),
                    IconButton(
                      tooltip: '关闭',
                      onPressed: () => Navigator.of(sheetContext).pop(),
                      icon: const Icon(Icons.close_rounded),
                      color: ProductColors.textSecondary,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Flexible(
                  child: ListView.separated(
                    shrinkWrap: true,
                    itemCount: lane.tasks.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, index) {
                      final task = lane.tasks[index];
                      if (doneLane) {
                        return _CompletedLearningTaskMoveRow(
                          task: task,
                          onOpenDetails: () => closeThen(
                            () => onOpenDetails(task),
                          ),
                          onMoveToTodo: () => closeThen(
                            () => unawaited(onMoveTask(task, 'todo')),
                          ),
                          onMoveToDoing: () => closeThen(
                            () => unawaited(onMoveTask(task, 'doing')),
                          ),
                        );
                      }
                      return _LearningTaskCard(
                        task: task,
                        onOpenDetails: () => closeThen(
                          () => onOpenDetails(task),
                        ),
                        onCheckIn: () => closeThen(
                          () => onCheckIn(task),
                        ),
                        onStart: () => closeThen(
                          () => unawaited(onMoveTask(task, 'doing')),
                        ),
                      );
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    },
  );
}

class _DraggableTaskCard extends StatelessWidget {
  final CareerWorkbenchLearningTaskView task;
  final bool doneLane;
  final VoidCallback onOpenDetails;
  final VoidCallback onCheckIn;
  final VoidCallback onStart;

  const _DraggableTaskCard({
    required this.task,
    required this.doneLane,
    required this.onOpenDetails,
    required this.onCheckIn,
    required this.onStart,
  });

  @override
  Widget build(BuildContext context) {
    final card = doneLane
        ? _CompletedLearningTaskRow(task: task, onOpenDetails: onOpenDetails)
        : _LearningTaskCard(
            task: task,
            onOpenDetails: onOpenDetails,
            onCheckIn: onCheckIn,
            onStart: onStart,
          );
    return Draggable<CareerWorkbenchLearningTaskView>(
      data: task,
      feedback: Material(
        color: Colors.transparent,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 330),
          child: Opacity(
            opacity: 0.94,
            child: doneLane
                ? _CompletedLearningTaskRow(
                    task: task,
                    onOpenDetails: onOpenDetails,
                  )
                : _LearningTaskCard(
                    task: task,
                    onOpenDetails: onOpenDetails,
                    onCheckIn: onCheckIn,
                    onStart: onStart,
                  ),
          ),
        ),
      ),
      childWhenDragging: Opacity(opacity: 0.36, child: card),
      child: MouseRegion(
        cursor: SystemMouseCursors.grab,
        child: card,
      ),
    );
  }
}

class _LearningTaskCard extends StatelessWidget {
  final CareerWorkbenchLearningTaskView task;
  final VoidCallback onOpenDetails;
  final VoidCallback onCheckIn;
  final VoidCallback onStart;

  const _LearningTaskCard({
    required this.task,
    required this.onOpenDetails,
    required this.onCheckIn,
    required this.onStart,
  });

  @override
  Widget build(BuildContext context) {
    final tone = _taskStateTone(task.state);
    final progress = _taskVisualProgress(task);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onOpenDetails,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          constraints: const BoxConstraints(minHeight: 78),
          padding: const EdgeInsets.fromLTRB(8, 7, 8, 7),
          decoration: BoxDecoration(
            color: ProductColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: ProductColors.border),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.025),
                blurRadius: 10,
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
                  ProductIconTile(
                    icon: _taskTypeIcon(task.taskType),
                    tone: tone,
                    size: 28,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          task.title.trim().isEmpty
                              ? '未命名任务'
                              : task.title.trim(),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 12,
                            height: 1.25,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _taskSubtitle(task),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: AppTheme.ts(
                            fontSize: 10.8,
                            height: 1.32,
                            color: ProductColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 6),
                  Icon(
                    Icons.drag_indicator_rounded,
                    size: 16,
                    color: ProductColors.textMuted.withValues(alpha: 0.72),
                  ),
                ],
              ),
              const SizedBox(height: 5),
              Wrap(
                spacing: 5,
                runSpacing: 4,
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
                const SizedBox(height: 4),
                Wrap(
                  spacing: 5,
                  runSpacing: 5,
                  children: [
                    for (final tag in task.skillTags.take(2))
                      ProductTag(label: tag, tone: ProductTone.purple),
                  ],
                ),
              ],
              if (!_isDoneTask(task)) ...[
                const SizedBox(height: 6),
                LayoutBuilder(
                  builder: (context, constraints) {
                    final compact = constraints.maxWidth < 380;
                    final progressView = _TaskProgressInline(
                      progress: progress,
                      tone: tone,
                    );
                    Widget buttons({required bool expanded}) {
                      final started = _taskLaneState(task.state) == 'doing' ||
                          task.state.trim() == 'blocked';
                      final recordButton = SizedBox(
                        width: expanded ? null : 90,
                        height: 28,
                        child: ElevatedButton.icon(
                          onPressed: started ? onCheckIn : onStart,
                          icon: Icon(
                            started
                                ? Icons.edit_note_outlined
                                : Icons.play_arrow_rounded,
                            size: 15,
                          ),
                          label: Text(started ? '记录进度' : '开始任务'),
                          style: _primaryCompactButtonStyle(),
                        ),
                      );
                      final detailButton = SizedBox(
                        width: expanded ? null : 70,
                        height: 28,
                        child: OutlinedButton.icon(
                          onPressed: onOpenDetails,
                          icon: const Icon(Icons.article_outlined, size: 14),
                          label: const Text('详情'),
                          style: _outlineButtonStyle(),
                        ),
                      );
                      if (expanded) {
                        return Row(
                          children: [
                            Expanded(child: recordButton),
                            const SizedBox(width: 7),
                            Expanded(child: detailButton),
                          ],
                        );
                      }
                      return Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          recordButton,
                          const SizedBox(width: 8),
                          detailButton,
                        ],
                      );
                    }

                    if (compact) {
                      return Column(
                        children: [
                          progressView,
                          const SizedBox(height: 6),
                          buttons(expanded: true),
                        ],
                      );
                    }
                    return Row(
                      children: [
                        SizedBox(
                          width: math.min(126, constraints.maxWidth * 0.36),
                          child: progressView,
                        ),
                        const Spacer(),
                        buttons(expanded: false),
                      ],
                    );
                  },
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _TaskProgressInline extends StatelessWidget {
  final int progress;
  final ProductTone tone;

  const _TaskProgressInline({
    required this.progress,
    required this.tone,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Row(
      children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(999),
            child: LinearProgressIndicator(
              value: progress.clamp(0, 100).toDouble() / 100,
              minHeight: 6,
              color: style.color,
              backgroundColor: ProductColors.border,
            ),
          ),
        ),
        const SizedBox(width: 8),
        Text(
          '$progress%',
          style: AppTheme.ts(
            fontSize: 11.2,
            fontWeight: FontWeight.w900,
            color: style.color,
          ),
        ),
      ],
    );
  }
}

class _CompletedLearningTaskRow extends StatelessWidget {
  final CareerWorkbenchLearningTaskView task;
  final VoidCallback onOpenDetails;

  const _CompletedLearningTaskRow({
    required this.task,
    required this.onOpenDetails,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onOpenDetails,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.fromLTRB(9, 7, 9, 7),
          decoration: BoxDecoration(
            color: ProductColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: ProductColors.border),
          ),
          child: Row(
            children: [
              Container(
                width: 22,
                height: 22,
                decoration: BoxDecoration(
                  color: ProductColors.primary,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: const Icon(
                  Icons.check_rounded,
                  color: Colors.white,
                  size: 14,
                ),
              ),
              const SizedBox(width: 9),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      task.title.trim().isEmpty ? '未命名任务' : task.title.trim(),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      task.completedAt == null
                          ? '已完成'
                          : '完成于 ${careerFormatDateTime(task.completedAt!)}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.5,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 6),
              Icon(
                Icons.drag_indicator_rounded,
                size: 16,
                color: ProductColors.textMuted.withValues(alpha: 0.72),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CompletedLearningTaskMoveRow extends StatelessWidget {
  final CareerWorkbenchLearningTaskView task;
  final VoidCallback onOpenDetails;
  final VoidCallback onMoveToTodo;
  final VoidCallback onMoveToDoing;

  const _CompletedLearningTaskMoveRow({
    required this.task,
    required this.onOpenDetails,
    required this.onMoveToTodo,
    required this.onMoveToDoing,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          InkWell(
            onTap: onOpenDetails,
            borderRadius: BorderRadius.circular(999),
            child: Container(
              width: 24,
              height: 24,
              decoration: BoxDecoration(
                color: ProductColors.primary,
                borderRadius: BorderRadius.circular(999),
              ),
              child: const Icon(
                Icons.check_rounded,
                color: Colors.white,
                size: 15,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: InkWell(
              onTap: onOpenDetails,
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      task.title.trim().isEmpty ? '未命名任务' : task.title.trim(),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 12.4,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      task.completedAt == null
                          ? '已完成'
                          : '完成于 ${careerFormatDateTime(task.completedAt!)}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 10.8,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          SizedBox(
            height: 34,
            child: OutlinedButton.icon(
              onPressed: onMoveToTodo,
              icon: const Icon(Icons.low_priority_rounded, size: 14),
              label: const Text('移到待推进'),
              style: _outlineButtonStyle(),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            height: 34,
            child: ElevatedButton.icon(
              onPressed: onMoveToDoing,
              icon: const Icon(Icons.play_arrow_rounded, size: 15),
              label: const Text('移到进行中'),
              style: _primaryCompactButtonStyle(),
            ),
          ),
        ],
      ),
    );
  }
}

enum _LearningTaskDetailAction { checkIn, archive }

Future<_LearningTaskDetailAction?> _showLearningTaskDetailSheet(
  BuildContext context,
  CareerWorkbenchLearningTaskView task, {
  required Future<String?> Function() onAiDecompose,
}) {
  return showDialog<_LearningTaskDetailAction>(
    context: context,
    barrierDismissible: false,
    builder: (sheetContext) {
      var decomposing = false;
      String? decomposeResult;
      String? decomposeError;

      Future<void> runAiDecompose(StateSetter setSheetState) async {
        if (decomposing) return;
        setSheetState(() {
          decomposing = true;
          decomposeError = null;
          decomposeResult = null;
        });
        try {
          final result = await onAiDecompose();
          if (!sheetContext.mounted) return;
          setSheetState(() {
            decomposing = false;
            decomposeResult = result?.trim().isNotEmpty == true
                ? result!.trim()
                : 'AI 拆解已完成，但没有返回可展示内容。本页已刷新。';
          });
        } catch (error) {
          if (!sheetContext.mounted) return;
          setSheetState(() {
            decomposing = false;
            decomposeError = error.toString();
          });
        }
      }

      return StatefulBuilder(
        builder: (sheetContext, setSheetState) {
          return Dialog(
            insetPadding:
                const EdgeInsets.symmetric(horizontal: 24, vertical: 24),
            backgroundColor: Colors.transparent,
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: 720,
                maxHeight: MediaQuery.sizeOf(sheetContext).height * 0.88,
              ),
              child: ProductCard(
                padding: const EdgeInsets.fromLTRB(22, 20, 22, 20),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                task.title.trim().isEmpty
                                    ? '未命名学习任务'
                                    : task.title.trim(),
                                style: AppTheme.ts(
                                  fontSize: 21,
                                  height: 1.28,
                                  fontWeight: FontWeight.w900,
                                  color: ProductColors.text,
                                ),
                              ),
                              const SizedBox(height: 12),
                              Wrap(
                                spacing: 10,
                                runSpacing: 8,
                                children: [
                                  ProductTag(
                                    label: _taskStateLabel(task.state),
                                    tone: _taskStateTone(task.state),
                                  ),
                                  ProductTag(
                                    label: careerPriorityLabel(
                                      task.priority,
                                    ),
                                    tone: careerPriorityTone(
                                      task.priority,
                                    ),
                                  ),
                                  if (task.estimatedMinutes > 0)
                                    ProductTag(
                                      label: '${task.estimatedMinutes} 分钟',
                                      tone: ProductTone.neutral,
                                    ),
                                ],
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: '关闭',
                          onPressed: decomposing
                              ? null
                              : () => Navigator.of(sheetContext).pop(),
                          icon: const Icon(Icons.close_rounded),
                          color: ProductColors.textSecondary,
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Flexible(
                      child: SingleChildScrollView(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            _TaskDetailBlock(
                              title: '任务要求',
                              body: _taskSubtitle(task),
                              icon: Icons.radio_button_checked_rounded,
                            ),
                            if (task.description.trim().isNotEmpty) ...[
                              const SizedBox(height: 12),
                              _TaskDetailBlock(
                                title: '完成说明',
                                body: task.description.trim(),
                                icon: Icons.assignment_turned_in_outlined,
                              ),
                            ],
                            if (task.successCriteria.isNotEmpty) ...[
                              const SizedBox(height: 12),
                              _TaskDetailListBlock(
                                title: '完成标准',
                                items: task.successCriteria,
                                icon: Icons.checklist_rounded,
                              ),
                            ],
                            if (task.progressNotes.trim().isNotEmpty) ...[
                              const SizedBox(height: 12),
                              _TaskProgressRecordBlock(
                                notes: task.progressNotes.trim(),
                              ),
                            ],
                            if (task.skillTags.isNotEmpty) ...[
                              const SizedBox(height: 12),
                              Text(
                                '技能标签',
                                style: AppTheme.ts(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w900,
                                  color: ProductColors.text,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Wrap(
                                spacing: 6,
                                runSpacing: 6,
                                children: [
                                  for (final tag in task.skillTags)
                                    ProductTag(
                                      label: tag,
                                      tone: ProductTone.purple,
                                    ),
                                ],
                              ),
                            ],
                            if (decomposing ||
                                decomposeResult != null ||
                                decomposeError != null) ...[
                              const SizedBox(height: 12),
                              _TaskAiDecomposeBlock(
                                loading: decomposing,
                                result: decomposeResult,
                                error: decomposeError,
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        TextButton.icon(
                          onPressed: decomposing
                              ? null
                              : () => Navigator.of(sheetContext)
                                  .pop(_LearningTaskDetailAction.archive),
                          icon: const Icon(Icons.delete_outline_rounded,
                              size: 15),
                          label: const Text('删除任务'),
                          style: TextButton.styleFrom(
                            foregroundColor: ProductColors.danger,
                            textStyle: AppTheme.ts(
                              fontSize: 12,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ),
                        const Spacer(),
                        OutlinedButton.icon(
                          onPressed: decomposing
                              ? null
                              : () => unawaited(
                                    runAiDecompose(setSheetState),
                                  ),
                          icon: decomposing
                              ? const SizedBox(
                                  width: 15,
                                  height: 15,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.auto_awesome_rounded,
                                  size: 15),
                          label: Text(decomposing ? '拆解中' : 'AI 拆解'),
                          style: _outlineButtonStyle(),
                        ),
                        const SizedBox(width: 8),
                        FilledButton.icon(
                          onPressed: decomposing
                              ? null
                              : () => Navigator.of(sheetContext)
                                  .pop(_LearningTaskDetailAction.checkIn),
                          icon: const Icon(Icons.edit_note_outlined, size: 15),
                          label: const Text('记录进度'),
                          style: FilledButton.styleFrom(
                            backgroundColor: ProductColors.primary,
                            foregroundColor: Colors.white,
                            disabledBackgroundColor:
                                ProductColors.primary.withValues(
                              alpha: 0.42,
                            ),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                            ),
                            textStyle: AppTheme.ts(
                              fontSize: 12,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      );
    },
  );
}

Future<bool?> _confirmArchiveLearningTask(
  BuildContext context,
  CareerWorkbenchLearningTaskView task,
) {
  return showDialog<bool>(
    context: context,
    builder: (dialogContext) {
      return AlertDialog(
        title: const Text('删除学习任务？'),
        content: Text(
          '任务「${task.title.trim().isEmpty ? '未命名任务' : task.title.trim()}」会从学习看板中移除，历史记录仍会保留。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            style: FilledButton.styleFrom(
              backgroundColor: ProductColors.danger,
              foregroundColor: Colors.white,
            ),
            child: const Text('删除'),
          ),
        ],
      );
    },
  );
}

class _TaskDetailBlock extends StatelessWidget {
  final String title;
  final String body;
  final IconData icon;

  const _TaskDetailBlock({
    required this.title,
    required this.body,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      decoration: ProductSurface.softCard(tone: ProductTone.neutral),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: ProductColors.textSecondary),
              const SizedBox(width: 8),
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 14,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SelectableText(
            body.trim().isEmpty ? '暂无说明' : body.trim(),
            style: AppTheme.ts(
              fontSize: 13.2,
              height: 1.65,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _TaskDetailListBlock extends StatelessWidget {
  final String title;
  final List<String> items;
  final IconData icon;

  const _TaskDetailListBlock({
    required this.title,
    required this.items,
    required this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final visible = items
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList(growable: false);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      decoration: ProductSurface.softCard(tone: ProductTone.primary),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: ProductColors.textSecondary),
              const SizedBox(width: 8),
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 14,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          if (visible.isEmpty)
            Text(
              '暂无',
              style: AppTheme.ts(
                fontSize: 12,
                color: ProductColors.textSecondary,
              ),
            )
          else
            for (final item in visible)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(
                      Icons.check_circle_outline_rounded,
                      size: 15,
                      color: ProductColors.primary,
                    ),
                    const SizedBox(width: 7),
                    Expanded(
                      child: SelectableText(
                        item,
                        style: AppTheme.ts(
                          fontSize: 13,
                          height: 1.48,
                          color: ProductColors.textSecondary,
                        ),
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

class _TaskProgressRecordBlock extends StatelessWidget {
  final String notes;

  const _TaskProgressRecordBlock({required this.notes});

  @override
  Widget build(BuildContext context) {
    final rows = notes
        .split(RegExp(r'[\n\r]+'))
        .map((line) => line.trim())
        .where((line) => line.isNotEmpty)
        .toList(growable: false);
    final visibleRows = rows.isEmpty ? ['暂无进展记录'] : rows.take(3).toList();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
      decoration: ProductSurface.softCard(tone: ProductTone.neutral),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.event_note_outlined,
                size: 18,
                color: ProductColors.textSecondary,
              ),
              const SizedBox(width: 8),
              Text(
                '进展记录',
                style: AppTheme.ts(
                  fontSize: 14,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          for (var index = 0; index < visibleRows.length; index++) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Column(
                  children: [
                    const SizedBox(height: 2),
                    const Icon(
                      Icons.check_circle_rounded,
                      size: 18,
                      color: ProductColors.primary,
                    ),
                    if (index < visibleRows.length - 1)
                      Container(
                        width: 1,
                        height: 34,
                        margin: const EdgeInsets.symmetric(vertical: 3),
                        color: ProductColors.primary.withValues(alpha: 0.24),
                      ),
                  ],
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Container(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.86),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: ProductColors.border),
                    ),
                    child: Text(
                      visibleRows[index],
                      style: AppTheme.ts(
                        fontSize: 12.6,
                        height: 1.48,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ),
                ),
              ],
            ),
            if (index < visibleRows.length - 1) const SizedBox(height: 4),
          ],
        ],
      ),
    );
  }
}

class _TaskAiDecomposeBlock extends StatelessWidget {
  final bool loading;
  final String? result;
  final String? error;

  const _TaskAiDecomposeBlock({
    required this.loading,
    this.result,
    this.error,
  });

  @override
  Widget build(BuildContext context) {
    final hasError = error?.trim().isNotEmpty == true;
    final tone = hasError
        ? ProductTone.danger
        : loading
            ? ProductTone.purple
            : ProductTone.primary;
    final style = productToneStyle(tone);
    final title = hasError
        ? 'AI 拆解失败'
        : loading
            ? 'AI 正在拆解任务'
            : 'AI 拆解结果';
    final body = hasError
        ? error!.trim()
        : loading
            ? '正在分析任务要求、完成标准和当前状态，完成后会在这里展示下一步行动、子步骤和验收标准。'
            : (result?.trim().isNotEmpty == true ? result!.trim() : '暂无可展示结果。');
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 12),
      decoration: ProductSurface.softCard(tone: tone),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              if (loading)
                SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: style.color,
                  ),
                )
              else
                Icon(
                  hasError
                      ? Icons.error_outline_rounded
                      : Icons.auto_awesome_rounded,
                  size: 18,
                  color: style.color,
                ),
              const SizedBox(width: 8),
              Text(
                title,
                style: AppTheme.ts(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w900,
                  color: ProductColors.text,
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          SelectableText(
            body,
            style: AppTheme.ts(
              fontSize: 12.2,
              height: 1.5,
              color: ProductColors.textSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _LearningWeaknessSection extends StatelessWidget {
  final List<CareerWorkbenchWeaknessView> weaknesses;
  final List<CareerWorkbenchLearningTaskView> tasks;
  final VoidCallback onCreateTask;
  final VoidCallback onOpenNotes;
  final VoidCallback onRecommend;
  final _InlineLearningActionState action;

  const _LearningWeaknessSection({
    required this.weaknesses,
    required this.tasks,
    required this.onCreateTask,
    required this.onOpenNotes,
    required this.onRecommend,
    required this.action,
  });

  @override
  Widget build(BuildContext context) {
    final openWeaknesses = weaknesses
        .where((item) =>
            item.status == 'active' &&
            item.state != 'resolved' &&
            item.state != 'ignored')
        .toList()
      ..sort((a, b) =>
          _severityRank(a.severity).compareTo(_severityRank(b.severity)));
    final hasTrackedWeaknesses =
        weaknesses.any((item) => item.status == 'active');
    final content = openWeaknesses.isEmpty
        ? _LearningInsightEmptyState(
            icon: Icons.track_changes_rounded,
            tone: hasTrackedWeaknesses
                ? ProductTone.primary
                : ProductTone.neutral,
            title: hasTrackedWeaknesses ? '当前短板已处理' : '还没有待处理短板',
            message: hasTrackedWeaknesses
                ? '已解决或暂不处理的短板不会占用主页面。后续新的 JD 匹配、简历诊断或面试复盘会继续沉淀新的差距。'
                : '完成 JD 匹配、简历诊断或面试复盘后，这里会显示影响岗位匹配的能力缺口，帮助你判断哪些学习任务最值得优先做。',
            primaryLabel: '从匹配报告生成短板',
            onPrimary: action.isRunning ? null : onRecommend,
            secondaryLabel: '查看复盘笔记',
            onSecondary: onOpenNotes,
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
                        onCreateTask: onCreateTask,
                      ),
                    ),
                ],
              );
            },
          );
    return ProductSection(
      title: '短板与证据缺口',
      subtitle: openWeaknesses.isEmpty
          ? '说明学习任务为什么重要'
          : '${openWeaknesses.length} 个影响岗位匹配的差距',
      icon: Icons.report_problem_outlined,
      tone: openWeaknesses.isEmpty ? ProductTone.neutral : ProductTone.warning,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (action.isVisible) ...[
            _InlineLearningActionNotice(action: action),
            const SizedBox(height: 10),
          ],
          content,
        ],
      ),
    );
  }
}

class _WeaknessCard extends StatelessWidget {
  final CareerWorkbenchWeaknessView weakness;
  final int taskCount;
  final VoidCallback onCreateTask;

  const _WeaknessCard({
    required this.weakness,
    required this.taskCount,
    required this.onCreateTask,
  });

  @override
  Widget build(BuildContext context) {
    final tone = _severityTone(weakness.severity);
    final style = productToneStyle(tone);
    final hasTask = taskCount > 0;
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
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              ProductTag(
                label: _weaknessSourceLabel(weakness),
                tone: ProductTone.neutral,
              ),
              ProductTag(
                label: _weaknessStateLabel(weakness.state),
                tone: weakness.state == 'improving'
                    ? ProductTone.primary
                    : ProductTone.warning,
              ),
              ProductTag(
                label: hasTask ? '$taskCount 个关联任务' : '未转任务',
                tone: hasTask ? ProductTone.primary : ProductTone.warning,
              ),
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
          Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: 5,
                  runSpacing: 5,
                  children: [
                    for (final tag in weakness.skillTags.take(3))
                      ProductTag(label: tag, tone: ProductTone.purple),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              OutlinedButton.icon(
                onPressed: hasTask ? null : onCreateTask,
                icon: Icon(
                  hasTask ? Icons.link_rounded : Icons.add_task_rounded,
                  size: 14,
                ),
                label: Text(hasTask ? '已转任务' : '转成任务'),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(0, 30),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  foregroundColor:
                      hasTask ? ProductColors.textMuted : style.color,
                  disabledForegroundColor: ProductColors.textMuted,
                  side: BorderSide(
                    color: hasTask
                        ? ProductColors.border
                        : style.color.withValues(alpha: 0.3),
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                  textStyle: AppTheme.ts(
                    fontSize: 11,
                    fontWeight: FontWeight.w900,
                  ),
                ),
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
  final List<CareerWorkbenchLearningTaskView> tasks;
  final VoidCallback onRecommend;
  final ValueChanged<CareerWorkbenchReviewView> onStartReview;
  final _InlineLearningActionState action;

  const _LearningReviewSection({
    required this.reviews,
    required this.tasks,
    required this.onRecommend,
    required this.onStartReview,
    required this.action,
  });

  @override
  Widget build(BuildContext context) {
    final visible = reviews
        .where((review) =>
            review.status == 'active' &&
            review.state != 'done' &&
            review.state != 'completed' &&
            review.state != 'cancelled')
        .toList()
      ..sort((a, b) => _reviewSortTime(a).compareTo(_reviewSortTime(b)));
    final doneTasks = tasks.where(_isDoneTask).length;
    final dueCount = visible.where(_isReviewDue).length;
    final content = visible.isEmpty
        ? _LearningInsightEmptyState(
            icon: Icons.event_repeat_outlined,
            tone: doneTasks > 0 ? ProductTone.primary : ProductTone.neutral,
            title: doneTasks > 0 ? '可以安排一次复盘' : '完成任务后可安排复盘',
            message: doneTasks > 0
                ? '你已经有完成的学习任务。复盘用于确认是否真的掌握，并把成果沉淀成面试表达或简历证据。'
                : '这里会在学习任务完成后提醒你回顾重点，避免任务只是打卡完成，却没有真正转化成求职竞争力。',
            primaryLabel: doneTasks > 0 ? '安排复盘' : null,
            onPrimary: doneTasks > 0 && !action.isRunning ? onRecommend : null,
          )
        : Column(
            children: [
              for (final review in visible.take(4)) ...[
                _ReviewRow(review: review, onStart: onStartReview),
                if (review != visible.take(4).last)
                  const Divider(height: 16, color: ProductColors.border),
              ],
            ],
          );
    return ProductSection(
      title: '复盘安排',
      subtitle: visible.isEmpty
          ? '确认学完后是否真的掌握'
          : dueCount > 0
              ? '$dueCount 个今天需要复盘'
              : '${visible.length} 条待复盘',
      icon: Icons.event_note_outlined,
      tone: dueCount > 0 ? ProductTone.primary : ProductTone.neutral,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (action.isVisible) ...[
            _InlineLearningActionNotice(action: action),
            const SizedBox(height: 10),
          ],
          content,
        ],
      ),
    );
  }
}

class _LearningBottomInsightGrid extends StatelessWidget {
  final List<CareerWorkbenchWeaknessView> weaknesses;
  final List<CareerWorkbenchLearningTaskView> tasks;
  final List<CareerWorkbenchReviewView> reviews;
  final VoidCallback onCreateTask;
  final VoidCallback onOpenNotes;
  final VoidCallback onWeaknessRecommend;
  final VoidCallback onReviewRecommend;
  final ValueChanged<CareerWorkbenchReviewView> onStartReview;
  final _InlineLearningActionState weaknessAction;
  final _InlineLearningActionState reviewAction;

  const _LearningBottomInsightGrid({
    required this.weaknesses,
    required this.tasks,
    required this.reviews,
    required this.onCreateTask,
    required this.onOpenNotes,
    required this.onWeaknessRecommend,
    required this.onReviewRecommend,
    required this.onStartReview,
    required this.weaknessAction,
    required this.reviewAction,
  });

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 780;
        final weakness = _LearningWeaknessSection(
          weaknesses: weaknesses,
          tasks: tasks,
          onCreateTask: onCreateTask,
          onOpenNotes: onOpenNotes,
          onRecommend: onWeaknessRecommend,
          action: weaknessAction,
        );
        final review = _LearningReviewSection(
          reviews: reviews,
          tasks: tasks,
          onRecommend: onReviewRecommend,
          onStartReview: onStartReview,
          action: reviewAction,
        );
        if (!wide) {
          return Column(
            children: [
              weakness,
              const SizedBox(height: 14),
              review,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: weakness),
            const SizedBox(width: 14),
            Expanded(child: review),
          ],
        );
      },
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
  final ValueChanged<CareerWorkbenchLearningTaskView> onCheckIn;

  const _LearningRightRail({
    required this.provider,
    required this.app,
    required this.learning,
    required this.openTasks,
    required this.onOpenProjects,
    required this.onOpenNotes,
    required this.onCheckIn,
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
                        actionLabel: '记录',
                        onTap: () => onCheckIn(task),
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
          child: GridView.count(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            crossAxisCount: 2,
            mainAxisSpacing: 10,
            crossAxisSpacing: 10,
            childAspectRatio: 1.9,
            children: [
              _AssetCountRow(
                label: '路线',
                value: learning.plans.length,
                icon: Icons.route_outlined,
              ),
              _AssetCountRow(
                label: '任务',
                value: learning.tasks.length,
                icon: Icons.fact_check_outlined,
              ),
              _AssetCountRow(
                label: '短板',
                value: learning.weaknesses.length,
                icon: Icons.report_problem_outlined,
              ),
              _AssetCountRow(
                label: '复盘',
                value: learning.reviews.length,
                icon: Icons.event_repeat_outlined,
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
  final ValueChanged<CareerWorkbenchReviewView> onStart;

  const _ReviewRow({required this.review, required this.onStart});

  @override
  Widget build(BuildContext context) {
    final tone = _reviewDisplayTone(review);
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ProductIconTile(
          icon: Icons.event_repeat_outlined,
          tone: tone,
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
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  ProductTag(label: _reviewDueLabel(review), tone: tone),
                  ProductTag(
                    label: _reviewTypeLabel(review.reviewType),
                    tone: ProductTone.neutral,
                  ),
                ],
              ),
              const SizedBox(height: 6),
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
        OutlinedButton(
          onPressed: () => onStart(review),
          style: OutlinedButton.styleFrom(
            foregroundColor: ProductColors.primary,
            side: const BorderSide(color: ProductColors.border),
            minimumSize: const Size(0, 30),
            padding: const EdgeInsets.symmetric(horizontal: 10),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
            textStyle: AppTheme.ts(fontSize: 11, fontWeight: FontWeight.w900),
          ),
          child: const Text('开始复盘'),
        ),
      ],
    );
  }
}

class _CompleteReviewDialog extends StatefulWidget {
  final CareerWorkbenchReviewView review;

  const _CompleteReviewDialog({required this.review});

  @override
  State<_CompleteReviewDialog> createState() => _CompleteReviewDialogState();
}

class _CompleteReviewDialogState extends State<_CompleteReviewDialog> {
  late final TextEditingController _summaryController;

  @override
  void initState() {
    super.initState();
    _summaryController = TextEditingController(text: widget.review.summary);
  }

  @override
  void dispose() {
    _summaryController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final review = widget.review;
    return Dialog(
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Padding(
          padding: const EdgeInsets.all(22),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const ProductIconTile(
                    icon: Icons.event_repeat_outlined,
                    tone: ProductTone.primary,
                    size: 38,
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '完成复盘',
                          style: AppTheme.ts(
                            fontSize: 18,
                            fontWeight: FontWeight.w900,
                            color: ProductColors.text,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '确认后会把当前复盘安排标记完成，并刷新学习计划状态。',
                          style: AppTheme.ts(
                            fontSize: 12.5,
                            height: 1.45,
                            color: ProductColors.textSecondary,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: '关闭',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: ProductColors.surfaceSoft,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: ProductColors.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      review.title.trim().isEmpty
                          ? '学习复盘'
                          : review.title.trim(),
                      style: AppTheme.ts(
                        fontSize: 13.5,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        ProductTag(
                          label: _reviewDueLabel(review),
                          tone: _reviewDisplayTone(review),
                        ),
                        ProductTag(
                          label: _reviewTypeLabel(review.reviewType),
                          tone: ProductTone.neutral,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              TextField(
                key: const Key('learning_review_summary_field'),
                controller: _summaryController,
                maxLines: 4,
                minLines: 3,
                decoration: InputDecoration(
                  labelText: '复盘总结（可选）',
                  hintText: '记录这次复盘确认了什么、还需要继续补什么...',
                  alignLabelWithHint: true,
                  filled: true,
                  fillColor: ProductColors.surfaceSoft,
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
                    borderSide: const BorderSide(color: ProductColors.primary),
                  ),
                ),
              ),
              const SizedBox(height: 18),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  OutlinedButton(
                    onPressed: () => Navigator.of(context).pop(),
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size(96, 38),
                      foregroundColor: ProductColors.textSecondary,
                      side: const BorderSide(color: ProductColors.border),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    child: const Text('取消'),
                  ),
                  const SizedBox(width: 10),
                  ElevatedButton(
                    key: const Key('learning_review_complete_button'),
                    onPressed: () {
                      Navigator.of(context).pop(_summaryController.text);
                    },
                    style: ElevatedButton.styleFrom(
                      minimumSize: const Size(112, 38),
                      backgroundColor: ProductColors.primary,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    child: const Text('标记完成'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
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
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: ProductColors.surfaceSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: ProductColors.border),
      ),
      child: Row(
        children: [
          ProductIconTile(icon: icon, tone: ProductTone.purple, size: 30),
          const SizedBox(width: 8),
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
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: ProductColors.textSecondary,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '$value',
                  style: AppTheme.ts(
                    fontSize: 17,
                    height: 1,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
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

enum _InlineLearningActionStatus { idle, running, completed, failed }

class _InlineLearningActionState {
  final _InlineLearningActionStatus status;
  final String message;

  const _InlineLearningActionState._(this.status, this.message);

  const _InlineLearningActionState.idle()
      : this._(_InlineLearningActionStatus.idle, '');

  const _InlineLearningActionState.running(String message)
      : this._(_InlineLearningActionStatus.running, message);

  const _InlineLearningActionState.completed(String message)
      : this._(_InlineLearningActionStatus.completed, message);

  const _InlineLearningActionState.failed(String message)
      : this._(_InlineLearningActionStatus.failed, message);

  bool get isVisible => status != _InlineLearningActionStatus.idle;
  bool get isRunning => status == _InlineLearningActionStatus.running;

  ProductTone get tone {
    return switch (status) {
      _InlineLearningActionStatus.failed => ProductTone.danger,
      _InlineLearningActionStatus.idle => ProductTone.neutral,
      _ => ProductTone.primary,
    };
  }

  IconData get icon {
    return switch (status) {
      _InlineLearningActionStatus.completed =>
        Icons.check_circle_outline_rounded,
      _InlineLearningActionStatus.failed => Icons.error_outline_rounded,
      _ => Icons.auto_awesome_rounded,
    };
  }

  String get title {
    return switch (status) {
      _InlineLearningActionStatus.running => '正在生成',
      _InlineLearningActionStatus.completed => '生成完成',
      _InlineLearningActionStatus.failed => '生成失败',
      _InlineLearningActionStatus.idle => '',
    };
  }
}

class _InlineLearningActionNotice extends StatelessWidget {
  final _InlineLearningActionState action;

  const _InlineLearningActionNotice({required this.action});

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(action.tone);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
      decoration: ProductSurface.softCard(tone: action.tone),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              color: style.soft,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: style.color.withValues(alpha: 0.22)),
            ),
            child: action.isRunning
                ? Padding(
                    padding: const EdgeInsets.all(7),
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: style.color,
                    ),
                  )
                : Icon(action.icon, size: 16, color: style.color),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  action.title,
                  style: AppTheme.ts(
                    fontSize: 12.5,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  action.message,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    height: 1.45,
                    color: ProductColors.textSecondary,
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

class _LearningInsightEmptyState extends StatelessWidget {
  final IconData icon;
  final ProductTone tone;
  final String title;
  final String message;
  final String? primaryLabel;
  final VoidCallback? onPrimary;
  final String? secondaryLabel;
  final VoidCallback? onSecondary;

  const _LearningInsightEmptyState({
    required this.icon,
    required this.tone,
    required this.title,
    required this.message,
    this.primaryLabel,
    this.onPrimary,
    this.secondaryLabel,
    this.onSecondary,
  });

  @override
  Widget build(BuildContext context) {
    final hasPrimary =
        primaryLabel?.trim().isNotEmpty == true && onPrimary != null;
    final hasSecondary =
        secondaryLabel?.trim().isNotEmpty == true && onSecondary != null;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 14, 14, 14),
      decoration: ProductSurface.softCard(tone: tone),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ProductIconTile(icon: icon, tone: tone, size: 34),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: AppTheme.ts(
                        fontSize: 13,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      message,
                      style: AppTheme.ts(
                        fontSize: 12,
                        height: 1.45,
                        color: ProductColors.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (hasPrimary || hasSecondary) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (hasPrimary)
                  ElevatedButton.icon(
                    onPressed: onPrimary,
                    icon: const Icon(Icons.auto_awesome_rounded, size: 15),
                    label: Text(primaryLabel!.trim()),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: ProductColors.primary,
                      foregroundColor: Colors.white,
                      elevation: 0,
                      minimumSize: const Size(0, 34),
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                      textStyle: AppTheme.ts(
                          fontSize: 12, fontWeight: FontWeight.w900),
                    ),
                  ),
                if (hasSecondary)
                  OutlinedButton(
                    onPressed: onSecondary,
                    style: _outlineButtonStyle(),
                    child: Text(secondaryLabel!.trim()),
                  ),
              ],
            ),
          ],
        ],
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
  final String targetState;

  const _TaskLaneData(this.title, this.tasks, this.tone, this.targetState);
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

String _taskLaneState(String state) {
  return switch (state.trim()) {
    'doing' || 'in_progress' => 'doing',
    'done' || 'completed' => 'done',
    _ => 'todo',
  };
}

String _taskLaneTitle(String state) {
  return switch (state.trim()) {
    'doing' || 'in_progress' => '进行中',
    'done' || 'completed' => '已完成',
    _ => '待推进',
  };
}

int _progressPercent(int open, int done) {
  final total = open + done;
  if (total <= 0) return 0;
  return ((done / total) * 100).round().clamp(0, 100);
}

List<_RoadmapStepData> _buildRoadmapSteps(
  CareerLearningSummaryView learning,
  int overallProgress,
) {
  final hasLearningData =
      learning.plans.isNotEmpty || learning.tasks.isNotEmpty;
  final foundation = _roadmapPhaseProgress(
    learning,
    phase: 1,
    overallProgress: overallProgress,
    fallback: hasLearningData ? math.min(80, overallProgress).toInt() : 0,
  );
  final rag = _roadmapPhaseProgress(
    learning,
    phase: 2,
    overallProgress: overallProgress,
    fallback: hasLearningData ? math.min(65, overallProgress).toInt() : 0,
  );
  final agent = _roadmapPhaseProgress(
    learning,
    phase: 3,
    overallProgress: overallProgress,
    fallback: hasLearningData ? math.min(45, overallProgress).toInt() : 0,
  );
  final interview = _roadmapPhaseProgress(
    learning,
    phase: 4,
    overallProgress: overallProgress,
    fallback: learning.reviews.isNotEmpty ? math.min(35, overallProgress) : 0,
  );
  return [
    _RoadmapStepData(
      index: 1,
      title: '基础夯实',
      subtitle: _roadmapSubtitle(
        learning,
        fallback: 'Python / 算法 / 后端基础',
        planIndex: 0,
      ),
      progress: foundation,
      tone: ProductTone.primary,
    ),
    _RoadmapStepData(
      index: 2,
      title: 'LangChain / RAG',
      subtitle: '核心组件与检索增强',
      progress: rag,
      tone: ProductTone.info,
    ),
    _RoadmapStepData(
      index: 3,
      title: 'Agent 工程化',
      subtitle: '工具调用与流程编排',
      progress: agent,
      tone: ProductTone.purple,
    ),
    _RoadmapStepData(
      index: 4,
      title: '面试冲刺',
      subtitle: '项目表达与面试准备',
      progress: interview,
      tone: ProductTone.neutral,
    ),
  ];
}

String _roadmapSubtitle(
  CareerLearningSummaryView learning, {
  required String fallback,
  required int planIndex,
}) {
  if (learning.plans.length > planIndex) {
    final plan = learning.plans[planIndex];
    final tags = plan.focusSkillTags.take(3).join(' / ');
    return careerFirstNonEmpty(
      [tags, plan.targetRole, plan.description, plan.progressSummary],
      fallback: fallback,
    );
  }
  return fallback;
}

int _roadmapPhaseProgress(
  CareerLearningSummaryView learning, {
  required int phase,
  required int overallProgress,
  required int fallback,
}) {
  final related = learning.tasks
      .where((task) => _taskRoadmapPhase(task) == phase)
      .toList(growable: false);
  if (related.isEmpty) {
    return _capRoadmapProgress(fallback, overallProgress, learning);
  }
  final done = related.where(_isDoneTask).length;
  final open = related.where(_isOpenTask).length;
  return _capRoadmapProgress(
      _progressPercent(open, done), overallProgress, learning);
}

int _capRoadmapProgress(
  int progress,
  int overallProgress,
  CareerLearningSummaryView learning,
) {
  final normalized = progress.clamp(0, 100).toInt();
  if (learning.openTaskCount <= 0) return normalized;
  return math.min(normalized, overallProgress.clamp(0, 99)).toInt();
}

int _taskRoadmapPhase(CareerWorkbenchLearningTaskView task) {
  final haystack = [
    task.title,
    task.description,
    task.taskType,
    ...task.skillTags,
    ...task.successCriteria,
  ].join(' ').toLowerCase();
  if (_containsAny(haystack, const ['面试', '复盘', 'mock', '题', 'interview'])) {
    return 4;
  }
  if (_containsAny(
    haystack,
    const ['agent', '工具', 'workflow', 'langgraph', '多 agent'],
  )) {
    return 3;
  }
  if (_containsAny(
    haystack,
    const ['rag', 'langchain', '检索', '向量', '知识库', 'retrieval'],
  )) {
    return 2;
  }
  return 1;
}

bool _containsAny(String value, List<String> keywords) {
  return keywords.any((keyword) => value.contains(keyword.toLowerCase()));
}

int _taskVisualProgress(CareerWorkbenchLearningTaskView task) {
  return switch (task.state.trim()) {
    'doing' || 'in_progress' => task.progressNotes.trim().isEmpty ? 38 : 62,
    'blocked' => 28,
    'done' || 'completed' => 100,
    _ => 12,
  };
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

String _weaknessStateLabel(String state) {
  return switch (state.trim()) {
    'improving' => '处理中',
    'resolved' => '已补齐',
    'ignored' => '暂不处理',
    _ => '待处理',
  };
}

String _weaknessSourceLabel(CareerWorkbenchWeaknessView weakness) {
  final type = weakness.weaknessType.trim();
  if (type.contains('interview') || type.contains('面试')) {
    return '来自面试复盘';
  }
  if (type.contains('resume') || type.contains('简历')) {
    return '来自简历诊断';
  }
  if (type.contains('project') || type.contains('项目')) {
    return '来自项目差距';
  }
  if (type.contains('skill') || type.contains('gap')) {
    return '来自岗位匹配';
  }
  return '来自学习诊断';
}

ProductTone _severityTone(String severity) {
  return switch (severity.trim()) {
    'critical' || 'high' => ProductTone.warning,
    'low' => ProductTone.info,
    _ => ProductTone.neutral,
  };
}

int _reviewSortTime(CareerWorkbenchReviewView review) {
  final date = review.nextReviewAt ?? review.reviewAt ?? review.updatedAt;
  return date.millisecondsSinceEpoch;
}

bool _isReviewDue(CareerWorkbenchReviewView review) {
  final dueAt = review.nextReviewAt ?? review.reviewAt;
  if (dueAt == null) return false;
  final now = DateTime.now();
  final todayEnd = DateTime(now.year, now.month, now.day, 23, 59, 59);
  return !dueAt.isAfter(todayEnd);
}

ProductTone _reviewDisplayTone(CareerWorkbenchReviewView review) {
  if (_isReviewDue(review)) return ProductTone.primary;
  return _reviewTone(review.state);
}

String _reviewDueLabel(CareerWorkbenchReviewView review) {
  final dueAt = review.nextReviewAt ?? review.reviewAt;
  if (dueAt == null) return _reviewStateLabel(review.state);
  final now = DateTime.now();
  final today = DateTime(now.year, now.month, now.day);
  final date = DateTime(dueAt.year, dueAt.month, dueAt.day);
  final diff = date.difference(today).inDays;
  if (diff < 0) return '已到期';
  if (diff == 0) return '今天复盘';
  if (diff == 1) return '明天复盘';
  return careerFormatDateTime(dueAt);
}

String _reviewTypeLabel(String type) {
  return switch (type.trim()) {
    'spaced_repetition' => '间隔复盘',
    'interview_rehearsal' => '面试演练',
    'resume_review' => '简历复盘',
    'project_drill' => '项目演练',
    _ => '自定义复盘',
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

ButtonStyle _outlineButtonStyle(
    {Color foregroundColor = ProductColors.primary}) {
  return OutlinedButton.styleFrom(
    foregroundColor: foregroundColor,
    side: const BorderSide(color: ProductColors.borderStrong),
    padding: const EdgeInsets.symmetric(horizontal: 12),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    textStyle: AppTheme.ts(fontSize: 12, fontWeight: FontWeight.w900),
  );
}

ButtonStyle _primaryCompactButtonStyle() {
  return ElevatedButton.styleFrom(
    backgroundColor: ProductColors.primary,
    foregroundColor: Colors.white,
    elevation: 0,
    padding: const EdgeInsets.symmetric(horizontal: 10),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
    textStyle: AppTheme.ts(fontSize: 11, fontWeight: FontWeight.w900),
  );
}
