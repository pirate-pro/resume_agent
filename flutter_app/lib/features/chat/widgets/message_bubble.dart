import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_highlight/flutter_highlight.dart';
import 'package:flutter_highlight/themes/atom-one-dark.dart';
import 'package:markdown/markdown.dart' as md;
import 'package:agent_runtime/core/theme/app_theme.dart';
import 'package:agent_runtime/shared/models/message.dart';

class MessageBubble extends StatelessWidget {
  final Message message;
  final bool showThinking;

  const MessageBubble({
    required this.message,
    this.showThinking = true,
  });

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == 'user';
    final bubbleColor = _getBubbleColor(message.role);
    final alignment = isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start;

    return Padding(
      padding: EdgeInsets.symmetric(
        vertical: AppTokens.spacingSm,
        horizontal: AppTokens.spacingMd,
      ),
      child: Column(
        crossAxisAlignment: alignment,
        children: [
          Container(
            constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.7,
            ),
            decoration: BoxDecoration(
              color: bubbleColor,
              borderRadius: BorderRadius.only(
                topLeft: Radius.circular(AppTokens.radiusLg),
                topRight: Radius.circular(AppTokens.radiusLg),
                bottomLeft: Radius.circular(isUser ? AppTokens.radiusLg : 0),
                bottomRight: Radius.circular(isUser ? 0 : AppTokens.radiusLg),
              ),
              boxShadow: [
                AppTokens.shadowMd,
              ],
            ),
            padding: EdgeInsets.all(AppTokens.spacingMd),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (message.role != 'user') ...[
                  Text(
                    message.role == 'assistant' ? 'AI' : 'Error',
                    style: TextStyle(
                      fontSize: AppTokens.fontSizeXs,
                      fontWeight: AppTokens.fontWeightMedium,
                      color: AppTokens.textSub,
                    ),
                  ),
                  SizedBox(height: AppTokens.spacingXs),
                ],
                MarkdownBody(
                  data: message.content,
                  styleSheet: MarkdownStyleSheet(
                    p: TextStyle(
                      fontSize: AppTokens.fontSizeBase,
                      color: AppTokens.textMain,
                      height: 1.5,
                    ),
                    code: TextStyle(
                      fontFamily: 'IBM Plex Mono',
                      fontSize: AppTokens.fontSizeSm,
                      color: AppTokens.accent,
                    ),
                    codeblockDecoration: BoxDecoration(
                      color: AppTokens.hoverBg,
                      borderRadius: BorderRadius.circular(AppTokens.radiusMd),
                    ),
                  ),
                  builders: {
                    'code': HighlightBuilder(),
                  },
                ),
                if (message.thinking != null && showThinking) ...[
                  SizedBox(height: AppTokens.spacingSm),
                  ThinkingBlock(thinking: message.thinking!),
                ],
              ],
            ),
          ),
          if (message.streaming) ...[
            SizedBox(height: AppTokens.spacingSm),
            Container(
              padding: EdgeInsets.all(AppTokens.spacingSm),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(
                    '正在生成...',
                    style: TextStyle(
                      fontSize: AppTokens.fontSizeSm,
                      color: AppTokens.textSub,
                    ),
                  ),
                  SizedBox(width: AppTokens.spacingSm),
                  SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor: AlwaysStoppedAnimation(AppTokens.accent),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Color _getBubbleColor(String role) {
    switch (role) {
      case 'user':
        return MessageColors.userBubble;
      case 'assistant':
        return MessageColors.botBubble;
      case 'error':
        return MessageColors.errorBubble;
      default:
        return MessageColors.botBubble;
    }
  }
}

class HighlightBuilder extends MarkdownElementBuilder {
  @override
  Widget? visitElementAfter(md.Element element, TextStyle? preferredStyle) {
    if (element.tag != 'code') return null;

    final cssClass = element.attributes['class'] ?? '';
    final languageParts =
        cssClass.split(' ').where((part) => part.isNotEmpty).toList();
    final language = languageParts.isNotEmpty ? languageParts.last : 'text';

    return HighlightView(
      element.textContent,
      language: language,
      theme: atomOneDarkTheme,
      padding: EdgeInsets.all(AppTokens.spacingSm),
      textStyle: TextStyle(
        fontFamily: 'IBM Plex Mono',
        fontSize: AppTokens.fontSizeSm,
        color: AppTokens.textMain,
      ),
    );
  }
}

class ThinkingBlock extends StatelessWidget {
  final String thinking;

  const ThinkingBlock({required this.thinking});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: AppTokens.hoverBg,
        borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        border: Border.all(
          color: AppTokens.textSub.withOpacity(0.2),
        ),
      ),
      padding: EdgeInsets.all(AppTokens.spacingMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '执行过程',
            style: TextStyle(
              fontSize: AppTokens.fontSizeSm,
              fontWeight: AppTokens.fontWeightMedium,
              color: AppTokens.textSub,
            ),
          ),
          SizedBox(height: AppTokens.spacingSm),
          Text(
            thinking,
            style: TextStyle(
              fontSize: AppTokens.fontSizeXs,
              color: AppTokens.textSub,
              fontFamily: 'IBM Plex Mono',
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}
