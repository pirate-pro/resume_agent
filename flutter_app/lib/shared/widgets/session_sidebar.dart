import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../theme/app_theme.dart';

class SessionSidebar extends StatelessWidget {
  final List<SessionMeta> sessions;
  final String? activeSessionId;
  final Function(String) onSessionTap;
  final Function(String) onSessionDelete;
  final Future<bool> Function(String, String) onSessionRename;
  final Future<bool> Function(String, bool) onSessionPinToggle;
  final VoidCallback onNewSession;
  final bool collapsed;
  final VoidCallback onToggleCollapse;

  const SessionSidebar({
    super.key,
    required this.sessions,
    required this.activeSessionId,
    required this.onSessionTap,
    required this.onSessionDelete,
    required this.onSessionRename,
    required this.onSessionPinToggle,
    required this.onNewSession,
    this.collapsed = false,
    required this.onToggleCollapse,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      decoration: AppTheme.floatingPanelDecoration(radius: 30, alpha: 0.9),
      clipBehavior: Clip.antiAlias,
      child: collapsed ? _CollapsedRail(this) : _ExpandedSidebar(this),
    );
  }

  void _confirmDelete(BuildContext context, SessionMeta session) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppTheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        title: Text('删除会话', style: AppTheme.ts(fontWeight: FontWeight.w600)),
        content: Text(
          '确定要删除「${session.title}」吗？此操作不可恢复。',
          style: AppTheme.ts(color: AppTheme.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              onSessionDelete(session.id);
            },
            style: TextButton.styleFrom(foregroundColor: AppTheme.danger),
            child: const Text('删除'),
          ),
        ],
      ),
    );
  }
}

class _ExpandedSidebar extends StatelessWidget {
  final SessionSidebar parent;

  const _ExpandedSidebar(this.parent);

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 18, 14, 12),
          child: Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    colors: [AppTheme.accent, Color(0xFF059669)],
                  ),
                  borderRadius: BorderRadius.circular(16),
                ),
                child: const Center(
                  child: Icon(
                    Icons.bolt_rounded,
                    size: 20,
                    color: Colors.white,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Agent Runtime',
                      style: AppTheme.ts(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: AppTheme.textPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      '会话与上下文',
                      style: AppTheme.ts(
                        fontSize: 11,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              _IconBtn(
                icon: Icons.chevron_left_rounded,
                size: 20,
                onTap: parent.onToggleCollapse,
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(14, 4, 14, 10),
          child: SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              onPressed: parent.onNewSession,
              icon: const Icon(Icons.add_rounded, size: 18),
              label: Text(
                '新会话',
                style: AppTheme.ts(fontSize: 13, fontWeight: FontWeight.w600),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.surfaceActive,
                foregroundColor: AppTheme.textPrimary,
                elevation: 0,
                padding: const EdgeInsets.symmetric(vertical: 14),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(18),
                  side: BorderSide(
                    color: AppTheme.borderLight.withValues(alpha: 0.8),
                  ),
                ),
              ),
            ),
          ),
        ),
        Expanded(
          child: parent.sessions.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(
                        Icons.chat_bubble_outline_rounded,
                        size: 34,
                        color: AppTheme.textTertiary,
                      ),
                      const SizedBox(height: 10),
                      Text(
                        '暂无会话',
                        style: AppTheme.ts(
                          fontSize: 13,
                          color: AppTheme.textTertiary,
                        ),
                      ),
                    ],
                  ),
                )
              : ListView.builder(
                  padding: const EdgeInsets.fromLTRB(10, 4, 10, 14),
                  itemCount: parent.sessions.length,
                  itemBuilder: (_, i) => _SessionTile(
                    session: parent.sessions[i],
                    isActive: parent.sessions[i].id == parent.activeSessionId,
                    onTap: () => parent.onSessionTap(parent.sessions[i].id),
                    onRename: (title) =>
                        parent.onSessionRename(parent.sessions[i].id, title),
                    onPinToggle: (isPinned) => parent.onSessionPinToggle(
                      parent.sessions[i].id,
                      isPinned,
                    ),
                    onDelete: () =>
                        parent._confirmDelete(context, parent.sessions[i]),
                  ),
                ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
            decoration: BoxDecoration(
              color: AppTheme.surface.withValues(alpha: 0.82),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: AppTheme.border),
            ),
            child: Row(
              children: [
                const Icon(Icons.circle, size: 8, color: AppTheme.accent),
                const SizedBox(width: 8),
                Text(
                  '${parent.sessions.length} 个会话',
                  style: AppTheme.ts(
                    fontSize: 11,
                    color: AppTheme.textTertiary,
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _CollapsedRail extends StatelessWidget {
  final SessionSidebar parent;

  const _CollapsedRail(this.parent);

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const SizedBox(height: 14),
        _IconBtn(icon: Icons.menu_rounded, onTap: parent.onToggleCollapse),
        const SizedBox(height: 10),
        _IconBtn(
          icon: Icons.add_rounded,
          onTap: parent.onNewSession,
          accent: true,
        ),
        const SizedBox(height: 12),
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            itemCount: parent.sessions.length,
            itemBuilder: (_, i) {
              final session = parent.sessions[i];
              final active = session.id == parent.activeSessionId;
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Tooltip(
                  message: session.title,
                  child: InkWell(
                    borderRadius: BorderRadius.circular(18),
                    onTap: () => parent.onSessionTap(session.id),
                    child: Container(
                      width: 52,
                      height: 52,
                      decoration: BoxDecoration(
                        color: active
                            ? AppTheme.accent.withValues(alpha: 0.16)
                            : AppTheme.surface.withValues(alpha: 0.78),
                        borderRadius: BorderRadius.circular(18),
                        border: Border.all(
                          color: active
                              ? AppTheme.accent.withValues(alpha: 0.4)
                              : AppTheme.border,
                        ),
                      ),
                      child: Icon(
                        session.isPinned
                            ? Icons.push_pin_rounded
                            : Icons.chat_bubble_rounded,
                        size: 18,
                        color: active
                            ? AppTheme.accent
                            : AppTheme.textSecondary,
                      ),
                    ),
                  ),
                ),
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Text(
            '${parent.sessions.length}',
            style: AppTheme.ts(fontSize: 11, color: AppTheme.textTertiary),
          ),
        ),
      ],
    );
  }
}

class _SessionTile extends StatefulWidget {
  final SessionMeta session;
  final bool isActive;
  final VoidCallback onTap;
  final Future<bool> Function(String title) onRename;
  final Future<bool> Function(bool isPinned) onPinToggle;
  final VoidCallback onDelete;

  const _SessionTile({
    required this.session,
    required this.isActive,
    required this.onTap,
    required this.onRename,
    required this.onPinToggle,
    required this.onDelete,
  });

  @override
  State<_SessionTile> createState() => _SessionTileState();
}

class _SessionTileState extends State<_SessionTile> {
  bool _hovering = false;
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final active = widget.isActive;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovering = true),
      onExit: (_) => setState(() => _hovering = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 140),
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
          decoration: BoxDecoration(
            color: active
                ? AppTheme.accent.withValues(alpha: 0.12)
                : _hovering
                ? AppTheme.surfaceHover.withValues(alpha: 0.9)
                : AppTheme.surface.withValues(alpha: 0.68),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: active
                  ? AppTheme.accent.withValues(alpha: 0.35)
                  : AppTheme.border.withValues(alpha: 0.9),
            ),
          ),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: active
                      ? AppTheme.accent.withValues(alpha: 0.16)
                      : AppTheme.surfaceActive,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Icon(
                  Icons.chat_rounded,
                  size: 16,
                  color: active ? AppTheme.accent : AppTheme.textSecondary,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        if (widget.session.isPinned) ...[
                          const Icon(
                            Icons.push_pin_rounded,
                            size: 12,
                            color: AppTheme.accent,
                          ),
                          const SizedBox(width: 6),
                        ],
                        Expanded(
                          child: Text(
                            widget.session.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 13,
                              fontWeight: active
                                  ? FontWeight.w600
                                  : FontWeight.w500,
                              color: AppTheme.textPrimary,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _formatMeta(widget.session),
                      style: AppTheme.ts(
                        fontSize: 11,
                        color: AppTheme.textTertiary,
                      ),
                    ),
                  ],
                ),
              ),
              AnimatedOpacity(
                duration: const Duration(milliseconds: 140),
                opacity: (_hovering || widget.session.isPinned) ? 1 : 0,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _ActionIconButton(
                      icon: Icons.edit_outlined,
                      tooltip: '重命名',
                      onPressed: _busy ? null : _renameSession,
                    ),
                    _ActionIconButton(
                      icon: widget.session.isPinned
                          ? Icons.push_pin_rounded
                          : Icons.push_pin_outlined,
                      tooltip: widget.session.isPinned ? '取消置顶' : '置顶会话',
                      color: widget.session.isPinned
                          ? AppTheme.accent
                          : AppTheme.textTertiary,
                      onPressed: _busy ? null : _togglePin,
                    ),
                    _ActionIconButton(
                      icon: Icons.delete_outline_rounded,
                      tooltip: '删除会话',
                      onPressed: _busy ? null : widget.onDelete,
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

  Future<void> _renameSession() async {
    final controller = TextEditingController(text: widget.session.title);
    final result = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        backgroundColor: AppTheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        title: Text('重命名会话', style: AppTheme.ts(fontWeight: FontWeight.w600)),
        content: TextField(
          controller: controller,
          autofocus: true,
          maxLength: 40,
          decoration: const InputDecoration(
            hintText: '输入新的会话名称',
            counterText: '',
          ),
          onSubmitted: (value) => Navigator.of(dialogContext).pop(value.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () =>
                Navigator.of(dialogContext).pop(controller.text.trim()),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (!mounted || result == null) {
      return;
    }
    final normalized = result.trim();
    if (normalized.isEmpty || normalized == widget.session.title) {
      return;
    }
    setState(() => _busy = true);
    final ok = await widget.onRename(normalized);
    if (!mounted) return;
    setState(() => _busy = false);
    if (!ok) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('会话重命名失败')));
    }
  }

  Future<void> _togglePin() async {
    setState(() => _busy = true);
    final ok = await widget.onPinToggle(!widget.session.isPinned);
    if (!mounted) return;
    setState(() => _busy = false);
    if (!ok) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('更新会话置顶状态失败')));
    }
  }

  String _formatMeta(SessionMeta session) {
    final time = _formatDate(session.updatedAt);
    if (session.isPinned) {
      return '已置顶 · $time';
    }
    return time;
  }

  String _formatDate(DateTime dt) {
    final now = DateTime.now();
    if (dt.year == now.year && dt.month == now.month && dt.day == now.day) {
      return DateFormat('HH:mm').format(dt);
    }
    return DateFormat('MM/dd HH:mm').format(dt);
  }
}

class _ActionIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  final Color? color;

  const _ActionIconButton({
    required this.icon,
    required this.tooltip,
    required this.onPressed,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 28,
      height: 28,
      child: IconButton(
        padding: EdgeInsets.zero,
        iconSize: 16,
        tooltip: tooltip,
        icon: Icon(icon, color: color ?? AppTheme.textTertiary),
        onPressed: onPressed,
      ),
    );
  }
}

class _IconBtn extends StatelessWidget {
  final IconData icon;
  final VoidCallback onTap;
  final bool accent;
  final double size;

  const _IconBtn({
    required this.icon,
    required this.onTap,
    this.accent = false,
    this.size = 22,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(18),
        onTap: onTap,
        child: Container(
          width: 40,
          height: 40,
          decoration: BoxDecoration(
            color: accent
                ? AppTheme.accent.withValues(alpha: 0.16)
                : AppTheme.surface.withValues(alpha: 0.82),
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: accent
                  ? AppTheme.accent.withValues(alpha: 0.3)
                  : AppTheme.border,
            ),
          ),
          child: Icon(
            icon,
            size: size,
            color: accent ? AppTheme.accent : AppTheme.textSecondary,
          ),
        ),
      ),
    );
  }
}
