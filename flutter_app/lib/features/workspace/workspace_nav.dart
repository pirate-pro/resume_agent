import 'package:flutter/material.dart';

import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import 'workspace_models.dart';

class ProductSidebar extends StatelessWidget {
  final WorkspacePage activePage;
  final WorkspaceBadges badges;
  final ValueChanged<WorkspacePage> onPageChanged;
  final VoidCallback onNewSession;
  final VoidCallback onOpenChat;
  final bool compact;

  const ProductSidebar({
    super.key,
    required this.activePage,
    required this.badges,
    required this.onPageChanged,
    required this.onNewSession,
    required this.onOpenChat,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    final pages = [
      WorkspacePage.dashboard,
      WorkspacePage.projects,
      WorkspacePage.resumes,
      WorkspacePage.jdMatch,
      WorkspacePage.learning,
      WorkspacePage.notes,
    ];
    return Container(
      width: compact ? null : 260,
      decoration: const BoxDecoration(
        color: ProductColors.surface,
        border: Border(
          right: BorderSide(color: ProductColors.border),
        ),
      ),
      child: SafeArea(
        right: false,
        child: Column(
          children: [
            _SidebarBrand(
                compact: compact,
                onTap: () {
                  onPageChanged(WorkspacePage.dashboard);
                }),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
              child: _PrimaryCreateButton(onTap: onNewSession),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(14, 0, 14, 16),
                children: [
                  for (final page in pages) ...[
                    ProductNavItem(
                      page: page,
                      selected: activePage == page,
                      count: workspacePageBadge(page, badges),
                      onTap: () => onPageChanged(page),
                    ),
                    const SizedBox(height: 7),
                  ],
                  const SizedBox(height: 18),
                  const _QuickEntryTitle(),
                  const SizedBox(height: 10),
                  _WorkspaceQuickEntryGrid(
                    onGenerateResume: () =>
                        onPageChanged(WorkspacePage.resumes),
                    onAnalyzeJD: () => onPageChanged(WorkspacePage.jdMatch),
                    onInterviewPrep: () =>
                        onPageChanged(WorkspacePage.learning),
                    onAgent: onOpenChat,
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
              child: _AssistantStatusCard(onTap: onOpenChat),
            ),
          ],
        ),
      ),
    );
  }
}

class ProductNavItem extends StatelessWidget {
  final WorkspacePage page;
  final bool selected;
  final int count;
  final VoidCallback onTap;

  const ProductNavItem({
    super.key,
    required this.page,
    required this.selected,
    required this.count,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final color =
        selected ? ProductColors.primary : ProductColors.textSecondary;
    return Tooltip(
      message: workspacePageLabel(page),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 140),
            height: 44,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            decoration: BoxDecoration(
              color: selected ? ProductColors.primarySoft : Colors.transparent,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                color: selected
                    ? ProductColors.primary.withValues(alpha: 0.14)
                    : Colors.transparent,
              ),
            ),
            child: Row(
              children: [
                Icon(workspacePageIcon(page), size: 18, color: color),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    workspacePageLabel(page),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 13,
                      fontWeight: selected ? FontWeight.w900 : FontWeight.w700,
                      color: selected
                          ? ProductColors.primary
                          : ProductColors.textSecondary,
                    ),
                  ),
                ),
                if (count > 0)
                  Container(
                    constraints: const BoxConstraints(minWidth: 22),
                    height: 22,
                    padding: const EdgeInsets.symmetric(horizontal: 7),
                    decoration: BoxDecoration(
                      color: selected
                          ? ProductColors.surface
                          : AppTheme.surfaceHover.withValues(alpha: 0.78),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Center(
                      child: Text(
                        count.toString(),
                        style: AppTheme.ts(
                          fontSize: 10.5,
                          fontWeight: FontWeight.w900,
                          color: selected
                              ? ProductColors.primary
                              : ProductColors.textMuted,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SidebarBrand extends StatelessWidget {
  final bool compact;
  final VoidCallback onTap;

  const _SidebarBrand({
    required this.compact,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 18, 16, 4),
          child: Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [ProductColors.primary, Color(0xFF059669)],
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                  ),
                  borderRadius: BorderRadius.circular(16),
                  boxShadow: [
                    BoxShadow(
                      color: ProductColors.primary.withValues(alpha: 0.22),
                      blurRadius: 16,
                      offset: const Offset(0, 8),
                    ),
                  ],
                ),
                child: const Icon(
                  Icons.bolt_rounded,
                  size: 22,
                  color: Colors.white,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '求职 Agent',
                      style: AppTheme.ts(
                        fontSize: 16,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '你的智能求职伙伴',
                      style: AppTheme.ts(
                        fontSize: 11.5,
                        color: ProductColors.textMuted,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PrimaryCreateButton extends StatelessWidget {
  final VoidCallback onTap;

  const _PrimaryCreateButton({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 44,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: ProductColors.primary,
          foregroundColor: Colors.white,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.add_rounded, size: 18),
            const SizedBox(width: 7),
            Text(
              '新建会话',
              style: AppTheme.ts(
                fontSize: 13,
                fontWeight: FontWeight.w900,
                color: Colors.white,
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.auto_awesome_rounded, size: 15),
          ],
        ),
      ),
    );
  }
}

class _QuickEntryTitle extends StatelessWidget {
  const _QuickEntryTitle();

  @override
  Widget build(BuildContext context) {
    return Text(
      '工作台快捷入口',
      style: AppTheme.ts(
        fontSize: 12,
        fontWeight: FontWeight.w900,
        color: ProductColors.text,
      ),
    );
  }
}

class _WorkspaceQuickEntryGrid extends StatelessWidget {
  final VoidCallback onGenerateResume;
  final VoidCallback onAnalyzeJD;
  final VoidCallback onInterviewPrep;
  final VoidCallback onAgent;

  const _WorkspaceQuickEntryGrid({
    required this.onGenerateResume,
    required this.onAnalyzeJD,
    required this.onInterviewPrep,
    required this.onAgent,
  });

  @override
  Widget build(BuildContext context) {
    return GridView.count(
      crossAxisCount: 2,
      mainAxisSpacing: 8,
      crossAxisSpacing: 8,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      childAspectRatio: 2.3,
      children: [
        _QuickEntryButton(
          icon: Icons.description_outlined,
          label: '生成简历',
          onTap: onGenerateResume,
        ),
        _QuickEntryButton(
          icon: Icons.link_rounded,
          label: 'JD 分析',
          onTap: onAnalyzeJD,
        ),
        _QuickEntryButton(
          icon: Icons.chat_bubble_outline_rounded,
          label: '面试准备',
          onTap: onInterviewPrep,
        ),
        _QuickEntryButton(
          icon: Icons.auto_awesome_rounded,
          label: 'Agent 助手',
          onTap: onAgent,
        ),
      ],
    );
  }
}

class _QuickEntryButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  const _QuickEntryButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 9),
          decoration: BoxDecoration(
            color: ProductColors.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: ProductColors.border),
          ),
          child: Row(
            children: [
              Icon(icon, size: 15, color: ProductColors.primary),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.2,
                    fontWeight: FontWeight.w800,
                    color: ProductColors.textSecondary,
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

class _AssistantStatusCard extends StatelessWidget {
  final VoidCallback onTap;

  const _AssistantStatusCard({required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
          decoration: BoxDecoration(
            color: ProductColors.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: ProductColors.border),
          ),
          child: Row(
            children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: ProductColors.primary,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Icon(
                  Icons.groups_2_outlined,
                  size: 18,
                  color: Colors.white,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'AI 助理',
                      style: AppTheme.ts(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Row(
                      children: [
                        Container(
                          width: 7,
                          height: 7,
                          decoration: const BoxDecoration(
                            color: ProductColors.primary,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 5),
                        Text(
                          '在线',
                          style: AppTheme.ts(
                            fontSize: 11,
                            color: ProductColors.textMuted,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.keyboard_arrow_up_rounded,
                size: 18,
                color: ProductColors.textMuted,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
