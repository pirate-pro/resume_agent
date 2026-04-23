import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';
import 'package:agent_runtime/shared/models/session.dart';

class SessionList extends StatelessWidget {
  final List<Session> sessions;
  final String? currentSessionId;
  final Function(String) onSelectSession;
  final Function(String) onDeleteSession;

  const SessionList({
    required this.sessions,
    required this.currentSessionId,
    required this.onSelectSession,
    required this.onDeleteSession,
  });

  @override
  Widget build(BuildContext context) {
    if (sessions.isEmpty) {
      return Center(
        child: Text(
          '无历史',
          style: TextStyle(
            fontSize: AppTokens.fontSizeSm,
            color: AppTokens.textSub,
          ),
        ),
      );
    }

    return ListView.builder(
      padding: EdgeInsets.all(AppTokens.spacingSm),
      itemCount: sessions.length,
      itemBuilder: (context, index) {
        final session = sessions[index];
        final isSelected = session.id == currentSessionId;

        return Container(
          margin: EdgeInsets.only(bottom: AppTokens.spacingSm),
          decoration: BoxDecoration(
            color: isSelected ? AppTokens.hoverBg : Colors.transparent,
            borderRadius: BorderRadius.circular(AppTokens.radiusMd),
            border: isSelected
                ? Border.all(
                    color: AppTokens.accent.withOpacity(0.3),
                  )
                : null,
          ),
          child: ListTile(
            contentPadding: EdgeInsets.symmetric(
              horizontal: AppTokens.spacingMd,
              vertical: AppTokens.spacingSm,
            ),
            leading: Icon(
              Icons.chat,
              color: isSelected ? AppTokens.accent : AppTokens.textSub,
            ),
            title: Text(
              session.title,
              style: TextStyle(
                fontSize: AppTokens.fontSizeBase,
                fontWeight: isSelected ? AppTokens.fontWeightMedium : AppTokens.fontWeightNormal,
                color: isSelected ? AppTokens.textMain : AppTokens.textSub,
              ),
            ),
            subtitle: Text(
              session.preview ?? '暂无预览',
              style: TextStyle(
                fontSize: AppTokens.fontSizeXs,
                color: AppTokens.textSub,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            trailing: IconButton(
              icon: Icon(
                Icons.delete,
                color: AppTokens.danger,
                size: 20,
              ),
              onPressed: () {
                onDeleteSession(session.id);
              },
            ),
            onTap: () {
              onSelectSession(session.id);
            },
          ),
        );
      },
    );
  }
}