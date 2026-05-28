import 'package:flutter/material.dart';

import '../../shared/theme/app_theme.dart';
import '../../shared/theme/product_tokens.dart';
import 'workspace_models.dart';

class WorkspaceTopBar extends StatefulWidget {
  final WorkspacePage activePage;
  final bool showMenu;
  final bool serverReachable;
  final VoidCallback? onMenuTap;
  final VoidCallback onNewSession;
  final VoidCallback onOpenWorkbench;
  final ValueChanged<String> onCommandSubmitted;

  const WorkspaceTopBar({
    super.key,
    required this.activePage,
    required this.serverReachable,
    required this.onNewSession,
    required this.onOpenWorkbench,
    required this.onCommandSubmitted,
    this.showMenu = false,
    this.onMenuTap,
  });

  @override
  State<WorkspaceTopBar> createState() => _WorkspaceTopBarState();
}

class _WorkspaceTopBarState extends State<WorkspaceTopBar> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit(String value) {
    final text = value.trim();
    if (text.isEmpty) return;
    widget.onCommandSubmitted(text);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < ProductBreakpoints.compact;
        final search = _GlobalSearchBox(
          controller: _controller,
          compact: compact,
          onSubmitted: _submit,
        );
        final actions = _TopActions(
          serverReachable: widget.serverReachable,
          compact: compact,
          onNewSession: widget.onNewSession,
          onOpenWorkbench: widget.onOpenWorkbench,
          showWorkbenchShortcut: widget.activePage != WorkspacePage.chat,
        );
        if (compact) {
          return Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
            child: Column(
              children: [
                Row(
                  children: [
                    if (widget.showMenu)
                      _TopIconButton(
                        tooltip: '打开导航',
                        icon: Icons.menu_rounded,
                        onTap: widget.onMenuTap,
                      ),
                    if (widget.showMenu) const SizedBox(width: 10),
                    Expanded(child: _TopTitle(page: widget.activePage)),
                    const SizedBox(width: 10),
                    actions,
                  ],
                ),
                const SizedBox(height: 10),
                search,
              ],
            ),
          );
        }
        return Padding(
          padding: const EdgeInsets.fromLTRB(24, 14, 24, 12),
          child: Row(
            children: [
              if (widget.showMenu)
                _TopIconButton(
                  tooltip: '打开导航',
                  icon: Icons.menu_rounded,
                  onTap: widget.onMenuTap,
                ),
              if (widget.showMenu) const SizedBox(width: 12),
              SizedBox(width: 220, child: _TopTitle(page: widget.activePage)),
              const SizedBox(width: 18),
              Expanded(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 620),
                    child: search,
                  ),
                ),
              ),
              const SizedBox(width: 18),
              actions,
            ],
          ),
        );
      },
    );
  }
}

class _TopTitle extends StatelessWidget {
  final WorkspacePage page;

  const _TopTitle({required this.page});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          workspacePageLabel(page),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppTheme.ts(
            fontSize: 17,
            fontWeight: FontWeight.w900,
            color: ProductColors.text,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          workspacePageSubtitle(page),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppTheme.ts(
            fontSize: 11.2,
            color: ProductColors.textMuted,
          ),
        ),
      ],
    );
  }
}

class _GlobalSearchBox extends StatelessWidget {
  final TextEditingController controller;
  final bool compact;
  final ValueChanged<String> onSubmitted;

  const _GlobalSearchBox({
    required this.controller,
    required this.compact,
    required this.onSubmitted,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 44,
      decoration: BoxDecoration(
        color: ProductColors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: ProductColors.border),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 16,
            offset: const Offset(0, 7),
          ),
        ],
      ),
      child: Row(
        children: [
          const SizedBox(width: 13),
          const Icon(Icons.search_rounded,
              size: 18, color: ProductColors.textMuted),
          const SizedBox(width: 8),
          Expanded(
            child: TextField(
              controller: controller,
              onSubmitted: onSubmitted,
              style: AppTheme.ts(fontSize: 13, color: ProductColors.text),
              decoration: InputDecoration(
                border: InputBorder.none,
                enabledBorder: InputBorder.none,
                focusedBorder: InputBorder.none,
                isDense: true,
                contentPadding: EdgeInsets.zero,
                hintText: compact ? '搜索或输入命令' : '搜索项目、岗位、笔记，或输入命令（如：分析 JD 匹配度）',
                hintStyle: AppTheme.ts(
                  fontSize: 12.6,
                  color: ProductColors.textMuted,
                ),
              ),
            ),
          ),
          if (!compact) ...[
            Container(
              margin: const EdgeInsets.only(right: 10),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: AppTheme.surfaceHover.withValues(alpha: 0.72),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: ProductColors.border),
              ),
              child: Text(
                '⌘ K',
                style: AppTheme.ts(
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  color: ProductColors.textMuted,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _TopActions extends StatelessWidget {
  final bool serverReachable;
  final bool compact;
  final VoidCallback onNewSession;
  final VoidCallback onOpenWorkbench;
  final bool showWorkbenchShortcut;

  const _TopActions({
    required this.serverReachable,
    required this.compact,
    required this.onNewSession,
    required this.onOpenWorkbench,
    required this.showWorkbenchShortcut,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (!compact && showWorkbenchShortcut) ...[
          Tooltip(
            message: '求职工作台',
            child: _TopIconButton(
              icon: Icons.business_center_outlined,
              onTap: onOpenWorkbench,
            ),
          ),
          const SizedBox(width: 8),
        ],
        SizedBox(
          height: 40,
          child: ElevatedButton.icon(
            onPressed: onNewSession,
            icon: const Icon(Icons.add_rounded, size: 17),
            label: Text(
              '新建',
              style: AppTheme.ts(
                fontSize: 12.5,
                fontWeight: FontWeight.w900,
                color: Colors.white,
              ),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: ProductColors.primary,
              foregroundColor: Colors.white,
              elevation: 0,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
            ),
          ),
        ),
        if (!compact) ...[
          const SizedBox(width: 8),
          _TopIconButton(
            tooltip: serverReachable ? '后端在线' : '后端离线',
            icon: serverReachable
                ? Icons.notifications_none_rounded
                : Icons.cloud_off_outlined,
            badge: serverReachable ? null : '!',
            onTap: () {},
          ),
          const SizedBox(width: 8),
          _TopIconButton(
            tooltip: '设置',
            icon: Icons.settings_outlined,
            onTap: () {},
          ),
        ],
        const SizedBox(width: 8),
        Container(
          width: 38,
          height: 38,
          decoration: const BoxDecoration(
            color: ProductColors.primary,
            shape: BoxShape.circle,
          ),
          child: Center(
            child: Text(
              'AI',
              style: AppTheme.ts(
                fontSize: 12,
                fontWeight: FontWeight.w900,
                color: Colors.white,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _TopIconButton extends StatelessWidget {
  final IconData icon;
  final VoidCallback? onTap;
  final String? tooltip;
  final String? badge;

  const _TopIconButton({
    required this.icon,
    this.onTap,
    this.tooltip,
    this.badge,
  });

  @override
  Widget build(BuildContext context) {
    final button = Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: ProductColors.surface,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: ProductColors.border),
              ),
              child: Icon(icon, size: 19, color: ProductColors.textSecondary),
            ),
            if (badge != null)
              Positioned(
                right: -3,
                top: -4,
                child: Container(
                  constraints: const BoxConstraints(minWidth: 16),
                  height: 16,
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  decoration: const BoxDecoration(
                    color: ProductColors.danger,
                    shape: BoxShape.circle,
                  ),
                  child: Center(
                    child: Text(
                      badge!,
                      style: AppTheme.ts(
                        fontSize: 9,
                        fontWeight: FontWeight.w900,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
    if (tooltip == null) return button;
    return Tooltip(message: tooltip!, child: button);
  }
}
