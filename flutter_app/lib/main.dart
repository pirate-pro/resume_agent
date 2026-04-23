import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:agent_runtime/core/theme/app_theme_data.dart';
import 'package:agent_runtime/features/chat/chat_page.dart';

void main() {
  runApp(const ProviderScope(child: MyApp()));
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Agent Runtime',
      theme: AppThemeData.darkTheme(),
      home: const ChatPage(),
      debugShowCheckedModeBanner: false,
    );
  }
}