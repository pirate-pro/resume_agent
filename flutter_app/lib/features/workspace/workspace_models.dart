import 'package:flutter/material.dart';

enum WorkspacePage {
  dashboard,
  projects,
  resumes,
  jdMatch,
  learning,
  notes,
  chat,
}

class WorkspaceNavBadge {
  final int count;

  const WorkspaceNavBadge(this.count);
}

class WorkspaceBadges {
  final int applications;
  final int resumes;
  final int jdMatches;
  final int learningTasks;
  final int notes;

  const WorkspaceBadges({
    required this.applications,
    required this.resumes,
    required this.jdMatches,
    required this.learningTasks,
    required this.notes,
  });
}

String workspacePageLabel(WorkspacePage page) {
  return switch (page) {
    WorkspacePage.dashboard => '总览',
    WorkspacePage.projects => '求职项目',
    WorkspacePage.resumes => '简历资料',
    WorkspacePage.jdMatch => 'JD 匹配',
    WorkspacePage.learning => '学习计划',
    WorkspacePage.notes => '笔记',
    WorkspacePage.chat => 'Agent 助手',
  };
}

String workspacePageSubtitle(WorkspacePage page) {
  return switch (page) {
    WorkspacePage.dashboard => '当前状态、下一步和最近推进',
    WorkspacePage.projects => '围绕岗位推进简历、匹配和面试',
    WorkspacePage.resumes => '管理简历画像、诊断和定制版本',
    WorkspacePage.jdMatch => '分析岗位要求、匹配度和差距',
    WorkspacePage.learning => '把短板转成可执行学习任务',
    WorkspacePage.notes => '沉淀面试准备、复盘和资料摘记',
    WorkspacePage.chat => '通过对话执行求职动作',
  };
}

IconData workspacePageIcon(WorkspacePage page) {
  return switch (page) {
    WorkspacePage.dashboard => Icons.home_outlined,
    WorkspacePage.projects => Icons.business_center_outlined,
    WorkspacePage.resumes => Icons.badge_outlined,
    WorkspacePage.jdMatch => Icons.analytics_outlined,
    WorkspacePage.learning => Icons.school_outlined,
    WorkspacePage.notes => Icons.sticky_note_2_outlined,
    WorkspacePage.chat => Icons.auto_awesome_rounded,
  };
}

int workspacePageBadge(WorkspacePage page, WorkspaceBadges badges) {
  return switch (page) {
    WorkspacePage.dashboard => 0,
    WorkspacePage.projects => badges.applications,
    WorkspacePage.resumes => badges.resumes,
    WorkspacePage.jdMatch => badges.jdMatches,
    WorkspacePage.learning => badges.learningTasks,
    WorkspacePage.notes => badges.notes,
    WorkspacePage.chat => 0,
  };
}

bool getWorkspacePageNeedsWorkbench(WorkspacePage page) {
  return switch (page) {
    WorkspacePage.dashboard => true,
    WorkspacePage.projects => true,
    WorkspacePage.resumes => true,
    WorkspacePage.jdMatch => true,
    WorkspacePage.learning => true,
    WorkspacePage.notes => true,
    WorkspacePage.chat => false,
  };
}
