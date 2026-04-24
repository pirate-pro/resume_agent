import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../core/models/api_models.dart';
import '../theme/app_theme.dart';

class SessionSidebar extends StatelessWidget {
  final List<SessionMeta> sessions;
  final String? activeSessionId;
  final Function(String) onSessionTap;
  final Function(String) onSessionDelete;
  final VoidCallback onNewSession;
  final bool collapsed;
  final VoidCallback onToggleCollapse;

  const SessionSidebar({
    super.key,
    required this.sessions,
    required this.activeSessionId,
    required this.onSessionTap,
    required this.onSessionDelete,
    required this.onNewSession,
    this.collapsed = false,
    required this.onToggleCollapse,
  });

  @override
  Widget build(BuildContext context) {
    if (collapsed) {
      return Container(
        width: 52,
        color: AppTheme.surface,
        child: Column(
          children: [
            const SizedBox(height: 12),
            _IconBtn(icon: Icons.menu_rounded, onTap: onToggleCollapse),
            const SizedBox(height: 8),
            _IconBtn(
                icon: Icons.add_rounded, onTap: onNewSession, accent: true),
          ],
        ),
      );
    }

    return Container(
      width: 260,
      decoration: const BoxDecoration(
        color: AppTheme.surface,
        border:
            Border(right: BorderSide(color: AppTheme.border, width: 0.5)),
      ),
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
            child: Row(
              children: [
                Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(
                      colors: [AppTheme.accent, Color(0xFF059669)],
                    ),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Center(
                    child: Icon(Icons.bolt_rounded,
                        size: 17, color: Colors.white),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    "Agent Runtime",
                    style: AppTheme.ts(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.textPrimary),
                  ),
                ),
                _IconBtn(
                  icon: Icons.chevron_left_rounded,
                  size: 20,
                  onTap: onToggleCollapse,
                ),
              ],
            ),
          ),
          // New session button
          Padding(
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: onNewSession,
                icon: const Icon(Icons.add_rounded, size: 16),
                label: Text("新会话",
                    style: AppTheme.ts(
                        fontSize: 13, fontWeight: FontWeight.w500)),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppTheme.textPrimary,
                  side: const BorderSide(color: AppTheme.border),
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 4),
          // Session list
          Expanded(
            child: sessions.isEmpty
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(Icons.chat_bubble_outline_rounded,
                            size: 32, color: AppTheme.textTertiary),
                        const SizedBox(height: 8),
                        Text("暂无会话",
                            style: AppTheme.ts(
                                fontSize: 13, color: AppTheme.textTertiary)),
                      ],
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    itemCount: sessions.length,
                    itemBuilder: (_, i) => _SessionTile(
                      session: sessions[i],
                      isActive: sessions[i].id == activeSessionId,
                      onTap: () => onSessionTap(sessions[i].id),
                      onDelete: () =>
                          _confirmDelete(context, sessions[i]),
                    ),
                  ),
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              children: [
                const Icon(Icons.circle, size: 8, color: AppTheme.accent),
                const SizedBox(width: 8),
                Text("${sessions.length} 个会话",
                    style: AppTheme.ts(
                        fontSize: 11, color: AppTheme.textTertiary)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  void _confirmDelete(BuildContext context, SessionMeta session) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: AppTheme.surface,
        shape:
            RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        title: Text("删除会话",
            style: AppTheme.ts(fontWeight: FontWeight.w600)),
        content: Text(
          "确定要删除「${session.title}」吗？此操作不可恢复。",
          style: AppTheme.ts(color: AppTheme.textSecondary),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text("取消"),
          ),
          TextButton(
            onPressed: () {
              Navigator.pop(context);
              onSessionDelete(session.id);
            },
            style:
                TextButton.styleFrom(foregroundColor: AppTheme.danger),
            child: const Text("删除"),
          ),
        ],
      ),
    );
  }
}

class _SessionTile extends StatefulWidget {
  final SessionMeta session;
  final bool isActive;
  final VoidCallback onTap;
  final VoidCallback onDelete;

  const _SessionTile({
    required this.session,
    required this.isActive,
    required this.onTap,
    required this.onDelete,
  });

  @override
  State<_SessionTile> createState() => _SessionTileState();
}

class _SessionTileState extends State<_SessionTile> {
  bool _hovering = false;

  @override
  Widget build(BuildContext context) {
    final active = widget.isActive;
    return MouseRegion(
      onEnter: (_) => setState(() => _hovering = true),
      onExit: (_) => setState(() => _hovering = false),
      child: GestureDetector(
        onTap: widget.onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 120),
          margin: const EdgeInsets.only(bottom: 2),
          padding:
              const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(
            color: active
                ? AppTheme.surfaceActive
                : _hovering
                    ? AppTheme.surfaceHover
                    : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
            border: active
                ? Border.all(color: AppTheme.borderLight, width: 0.5)
                : null,
          ),
          child: Row(
            children: [
              Icon(Icons.chat_rounded,
                  size: 15,
                  color:
                      active ? AppTheme.accent : AppTheme.textTertiary),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(widget.session.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                            fontSize: 13,
                            fontWeight:
                                active ? FontWeight.w500 : FontWeight.w400,
                            color: active
                                ? AppTheme.textPrimary
                                : AppTheme.textSecondary)),
                    const SizedBox(height: 2),
                    Text(_formatDate(widget.session.createdAt),
                        style: AppTheme.ts(
                            fontSize: 11, color: AppTheme.textTertiary)),
                  ],
                ),
              ),
              if (_hovering)
                SizedBox(
                  width: 24,
                  height: 24,
                  child: IconButton(
                    padding: EdgeInsets.zero,
                    iconSize: 14,
                    icon: const Icon(Icons.delete_outline_rounded,
                        color: AppTheme.textTertiary),
                    onPressed: widget.onDelete,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatDate(DateTime dt) {
    final now = DateTime.now();
    if (dt.year == now.year &&
        dt.month == now.month &&
        dt.day == now.day) {
      return DateFormat("HH:mm").format(dt);
    }
    return DateFormat("MM/dd HH:mm").format(dt);
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
    return SizedBox(
      width: 32,
      height: 32,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(8),
          onTap: onTap,
          child: Icon(icon,
              size: size,
              color: accent ? AppTheme.accent : AppTheme.textSecondary),
        ),
      ),
    );
  }
}
