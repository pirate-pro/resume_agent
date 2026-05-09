import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:resume_agent_app/core/models/api_models.dart';
import 'package:resume_agent_app/shared/widgets/chat_bubble.dart';

void main() {
  testWidgets('求职报告结构化卡片渲染 Markdown 而不是展示源码', (tester) async {
    final message = ChatMessage(
      role: 'assistant',
      content: '''
# 张明 - 简历诊断报告
简历诊断完成。以下是核心结论：
**诊断目标岗位方向：** AI Agent 后端工程师 / 平台研发工程师 / 后端工程师

## 诊断摘要
**候选人：** 张明，4 年后端工程师，坐标上海
**目标岗位：** AI Agent 后端工程师

## 核心优势
1. **LLM Agent 应用落地经验（强）**：从零设计 `Agent Runtime`，支持 **SSE 流式对话** 和 tool calling。
2. 技术栈：Python / FastAPI / PostgreSQL / Redis

## 风险点
| 风险项 | 等级 | 说明 |
| --- | --- | --- |
| **LLM 经验表达偏弱** | 中 | 需要补充 **RAG** 和 `MLOps` 细节 |

## 关键改进建议
1. **补充架构决策**：说明 Runtime vs LangChain 的取舍
''',
      answerFormat: 'markdown',
      renderHint: 'markdown',
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: ChatBubble(message: message),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('**'), findsNothing);
    expect(find.textContaining('# 张明'), findsNothing);
    expect(find.textContaining('```'), findsNothing);
    expect(find.textContaining('诊断目标岗位方向'), findsWidgets);
    expect(find.textContaining('LLM Agent 应用落地经验'), findsWidgets);
    expect(find.textContaining('补充架构决策'), findsWidgets);
  });
}
