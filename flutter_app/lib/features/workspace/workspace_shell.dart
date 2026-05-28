import 'package:flutter/material.dart';

import '../../shared/theme/product_tokens.dart';
import 'workspace_models.dart';
import 'workspace_nav.dart';
import 'workspace_top_bar.dart';

class ProductWorkspaceShell extends StatefulWidget {
  final WorkspacePage activePage;
  final WorkspaceBadges badges;
  final bool serverReachable;
  final Widget child;
  final ValueChanged<WorkspacePage> onPageChanged;
  final VoidCallback onNewSession;
  final VoidCallback onOpenChat;
  final VoidCallback onOpenSessionHistory;
  final ValueChanged<String> onCommandSubmitted;

  const ProductWorkspaceShell({
    super.key,
    required this.activePage,
    required this.badges,
    required this.serverReachable,
    required this.child,
    required this.onPageChanged,
    required this.onNewSession,
    required this.onOpenChat,
    required this.onOpenSessionHistory,
    required this.onCommandSubmitted,
  });

  @override
  State<ProductWorkspaceShell> createState() => _ProductWorkspaceShellState();
}

class _ProductWorkspaceShellState extends State<ProductWorkspaceShell> {
  void _openMobileNav(BuildContext context) {
    showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) {
        final height = MediaQuery.sizeOf(sheetContext).height;
        return Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(20),
            child: SizedBox(
              height: (height * 0.86).clamp(520.0, 760.0),
              child: ProductSidebar(
                activePage: widget.activePage,
                badges: widget.badges,
                compact: true,
                onPageChanged: (page) {
                  Navigator.of(sheetContext).pop();
                  widget.onPageChanged(page);
                },
                onNewSession: () {
                  Navigator.of(sheetContext).pop();
                  widget.onNewSession();
                },
                onOpenChat: () {
                  Navigator.of(sheetContext).pop();
                  widget.onOpenChat();
                },
              ),
            ),
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final desktop = width >= ProductBreakpoints.shellDesktop;
        return Material(
          color: ProductColors.canvas,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (desktop)
                ProductSidebar(
                  activePage: widget.activePage,
                  badges: widget.badges,
                  onPageChanged: widget.onPageChanged,
                  onNewSession: widget.onNewSession,
                  onOpenChat: widget.onOpenChat,
                ),
              Expanded(
                child: Column(
                  children: [
                    WorkspaceTopBar(
                      activePage: widget.activePage,
                      showMenu: !desktop,
                      serverReachable: widget.serverReachable,
                      onMenuTap: () => _openMobileNav(context),
                      onNewSession: widget.onNewSession,
                      onOpenSessionHistory: widget.onOpenSessionHistory,
                      onOpenWorkbench: () =>
                          widget.onPageChanged(WorkspacePage.projects),
                      onCommandSubmitted: widget.onCommandSubmitted,
                    ),
                    Expanded(
                      child: Padding(
                        padding: EdgeInsets.fromLTRB(
                          desktop ? 24 : 14,
                          0,
                          desktop ? 24 : 14,
                          desktop ? 24 : 14,
                        ),
                        child: widget.child,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
