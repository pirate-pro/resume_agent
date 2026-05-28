import 'dart:async';

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../../shared/theme/product_tokens.dart';
import '../career_workbench/career_workbench_provider.dart';

typedef CareerPromptSender = Future<void> Function(
  String prompt, {
  CareerWorkbenchActionRequest? action,
});

String careerFirstNonEmpty(List<String?> values, {String fallback = ''}) {
  for (final value in values) {
    final text = value?.trim() ?? '';
    if (text.isNotEmpty) return text;
  }
  return fallback;
}

String careerDisplaySummary(
  String? value, {
  String fallback = '',
  int maxChars = 140,
}) {
  var text = (value?.trim().isNotEmpty == true ? value!.trim() : fallback)
      .replaceAll(RegExp(r'\s+'), ' ');
  text = text.replaceAll(
    RegExp(
      r'\b(?:application|artifact|career_profile|jd_analysis|job_fit_report|resume_profile|resume_version|session|sess)_[A-Za-z0-9_-]+\b',
    ),
    '相关资料',
  );
  text = text.replaceAll(RegExp(r'(相关资料[，、\s]*){2,}'), '相关资料');
  if (maxChars > 0 && text.length > maxChars) {
    return '${text.substring(0, maxChars).trimRight()}…';
  }
  return text;
}

String careerShortLabel(String? value, {String fallback = '待补充'}) {
  final text = value?.trim() ?? '';
  return text.isEmpty ? fallback : text;
}

String careerStageLabel(String? stage) {
  return switch ((stage ?? '').trim()) {
    'draft' => '草稿',
    'ready_to_apply' => '准备投递',
    'applied' => '已投递',
    'screening' => '简历筛选',
    'interviewing' => '面试中',
    'offer' => 'Offer',
    'rejected' => '已结束',
    'paused' => '暂停',
    _ => '待推进',
  };
}

ProductTone careerStageTone(String? stage) {
  return switch ((stage ?? '').trim()) {
    'ready_to_apply' || 'applied' || 'screening' => ProductTone.info,
    'interviewing' || 'offer' => ProductTone.primary,
    'paused' => ProductTone.warning,
    'rejected' => ProductTone.neutral,
    _ => ProductTone.neutral,
  };
}

String careerPriorityLabel(String? priority) {
  return switch ((priority ?? '').trim()) {
    'urgent' => '紧急',
    'high' => '高',
    'medium' => '中',
    'low' => '低',
    _ => '中',
  };
}

ProductTone careerPriorityTone(String? priority) {
  return switch ((priority ?? '').trim()) {
    'urgent' || 'high' => ProductTone.warning,
    'low' => ProductTone.info,
    _ => ProductTone.neutral,
  };
}

String careerRecommendationLabel(String? recommendation, int? score) {
  final value = (recommendation ?? '').trim();
  if (value == 'recommended' || value == 'strong') return '良好';
  if (value == 'cautious') return '谨慎推进';
  if (value == 'not_recommended') return '高风险';
  if (score == null) return '待评估';
  if (score >= 80) return '良好';
  if (score >= 60) return '谨慎推进';
  return '高风险';
}

ProductTone careerScoreTone(int? score) {
  if (score == null) return ProductTone.neutral;
  if (score >= 80) return ProductTone.primary;
  if (score >= 60) return ProductTone.warning;
  return ProductTone.danger;
}

IconData careerActionIcon(String? actionType) {
  return switch ((actionType ?? '').trim()) {
    'custom_resume' => Icons.description_outlined,
    'resume_optimize' => Icons.tune_rounded,
    'interview_prep' => Icons.chat_bubble_outline_rounded,
    'learning_task' => Icons.school_outlined,
    'pre_apply_check' => Icons.checklist_rounded,
    'note' || 'note_create' => Icons.sticky_note_2_outlined,
    _ => Icons.auto_fix_high_outlined,
  };
}

String careerAssetTypeLabel(String? type) {
  return switch ((type ?? '').trim()) {
    'resume_profile' => '简历画像',
    'career_profile' => '职业画像',
    'jd_analysis' => 'JD 分析',
    'job_fit_report' => '匹配报告',
    'resume_version' => '简历版本',
    'note' => '笔记',
    'learning_task' => '学习任务',
    _ => '资料',
  };
}

String careerFormatDateTime(DateTime? value) {
  if (value == null) return '-';
  return DateFormat('MM-dd HH:mm').format(value);
}

String careerFormatDate(DateTime? value) {
  if (value == null) return '-';
  return DateFormat('yyyy-MM-dd').format(value);
}

void sendCareerPromptAction({
  required CareerPromptSender? sender,
  required CareerApplicationView? application,
  required String label,
  required String actionType,
  required String origin,
  String? detail,
}) {
  if (sender == null || application == null) return;
  final suffix = detail?.trim().isNotEmpty == true ? '。${detail!.trim()}' : '';
  unawaited(
    sender(
      '请基于求职项目 ${application.applicationId} 执行：$label$suffix',
      action: CareerWorkbenchActionRequest(
        applicationId: application.applicationId,
        actionType: actionType,
        label: label,
        origin: origin,
      ),
    ),
  );
}
