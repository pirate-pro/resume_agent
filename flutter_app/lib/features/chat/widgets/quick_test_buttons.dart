import 'package:flutter/material.dart';
import 'package:agent_runtime/core/theme/app_theme.dart';

class QuickTestButtons extends StatelessWidget {
  final Function(String) onTest;

  const QuickTestButtons({required this.onTest});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.all(AppTokens.spacingMd),
      decoration: BoxDecoration(
        color: AppTokens.shellBg,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '快速测试',
            style: TextStyle(
              fontSize: AppTokens.fontSizeSm,
              fontWeight: AppTokens.fontWeightMedium,
              color: AppTokens.textSub,
            ),
          ),
          SizedBox(height: AppTokens.spacingSm),
          Wrap(
            spacing: AppTokens.spacingMd,
            runSpacing: AppTokens.spacingSm,
            children: [
              _buildTestButton(
                '记忆偏好',
                '请记住我先不用数据库',
                Icons.memory,
              ),
              _buildTestButton(
                '写文件',
                '请在 workspace 写一个 hello.txt',
                Icons.edit,
              ),
              _buildTestButton(
                '读文件',
                '请帮我读取 workspace 里的文件',
                Icons.file_open,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildTestButton(String label, String prompt, IconData icon) {
    return ElevatedButton.icon(
      onPressed: () {
        onTest(prompt);
      },
      icon: Icon(icon, size: 16),
      label: Text(
        label,
        style: TextStyle(
          fontSize: AppTokens.fontSizeXs,
        ),
      ),
      style: ElevatedButton.styleFrom(
        backgroundColor: AppTokens.hoverBg,
        foregroundColor: AppTokens.textMain,
        padding: EdgeInsets.symmetric(
          horizontal: AppTokens.spacingMd,
          vertical: AppTokens.spacingSm,
        ),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        elevation: 0,
      ),
    );
  }
}