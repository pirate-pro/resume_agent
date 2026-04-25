import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/providers/theme_provider.dart';
import 'features/home/home_screen.dart';
import 'shared/theme/app_theme.dart';

void main() {
  runApp(const ProviderScope(child: AgentApp()));
}

class AgentApp extends ConsumerWidget {
  const AgentApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final themeMode = ref.watch(themeModeProvider);
    AppTheme.applyMode(themeMode);

    return MaterialApp(
      title: 'Agent Runtime',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: themeMode,
      home: const HomeScreen(),
    );
  }
}
