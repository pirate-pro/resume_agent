import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';

class UploadStatus extends StatelessWidget {
  final String? status;
  final bool isLoading;

  const UploadStatus({
    required this.status,
    required this.isLoading,
  });

  @override
  Widget build(BuildContext context) {
    if (status == null || status!.isEmpty) {
      return SizedBox.shrink();
    }

    return Container(
      padding: EdgeInsets.all(AppTokens.spacingSm),
      margin: EdgeInsets.only(bottom: AppTokens.spacingMd),
      decoration: BoxDecoration(
        color: AppTokens.hoverBg,
        borderRadius: BorderRadius.circular(AppTokens.radiusSm),
      ),
      child: Row(
        children: [
          if (isLoading) ...[
            SizedBox(
              width: 16,
              height: 16,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation(AppTokens.accent),
              ),
            ),
            SizedBox(width: AppTokens.spacingSm),
          ],
          Expanded(
            child: Text(
              status!,
              style: TextStyle(
                fontSize: AppTokens.fontSizeXs,
                color: AppTokens.textSub,
              ),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}