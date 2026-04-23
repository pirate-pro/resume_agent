import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';

class ErrorHandler extends StatelessWidget {
  final String? error;
  final VoidCallback onRetry;

  const ErrorHandler({
    required this.error,
    required this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    if (error == null || error!.isEmpty) {
      return SizedBox.shrink();
    }

    return Container(
      margin: EdgeInsets.all(AppTokens.spacingMd),
      padding: EdgeInsets.all(AppTokens.spacingMd),
      decoration: BoxDecoration(
        color: AppTokens.danger.withOpacity(0.1),
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(
          color: AppTokens.danger.withOpacity(0.3),
        ),
      ),
      child: Row(
        children: [
          Icon(
            Icons.error_outline,
            color: AppTokens.danger,
            size: 20,
          ),
          SizedBox(width: AppTokens.spacingMd),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '错误',
                  style: TextStyle(
                    fontSize: AppTokens.fontSizeSm,
                    fontWeight: AppTokens.fontWeightMedium,
                    color: AppTokens.danger,
                  ),
                ),
                SizedBox(height: AppTokens.spacingXs),
                Text(
                  error!,
                  style: TextStyle(
                    fontSize: AppTokens.fontSizeXs,
                    color: AppTokens.textSub,
                  ),
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          IconButton(
            icon: Icon(
              Icons.refresh,
              color: AppTokens.accent,
              size: 20,
            ),
            onPressed: onRetry,
          ),
        ],
      ),
    );
  }
}