import 'package:flutter/material.dart';

class AppTheme {
  static const Color bg = Color(0xFF0D0D0D);
  static const Color surface = Color(0xFF171717);
  static const Color surfaceHover = Color(0xFF1E1E1E);
  static const Color surfaceActive = Color(0xFF252525);
  static const Color border = Color(0xFF2A2A2A);
  static const Color borderLight = Color(0xFF333333);
  static const Color textPrimary = Color(0xFFECECEC);
  static const Color textSecondary = Color(0xFF8E8E8E);
  static const Color textTertiary = Color(0xFF5A5A5A);
  static const Color accent = Color(0xFF10A37F);
  static const Color accentHover = Color(0xFF0E8C6C);
  static const Color danger = Color(0xFFEF4444);
  static const Color userBubble = Color(0xFF2A2A2A);
  static const Color assistantBubble = Color(0xFF171717);

  static const String _fontFamily = 'Inter';

  static TextStyle ts({
    double? fontSize,
    FontWeight? fontWeight,
    Color? color,
    double? height,
    double? letterSpacing,
  }) =>
      TextStyle(
        fontFamily: _fontFamily,
        fontSize: fontSize,
        fontWeight: fontWeight,
        color: color,
        height: height,
        letterSpacing: letterSpacing,
      );

  static ThemeData get dark {
    return ThemeData(
      brightness: Brightness.dark,
      useMaterial3: true,
      scaffoldBackgroundColor: bg,
      colorScheme: const ColorScheme.dark(
        primary: accent,
        secondary: accent,
        surface: surface,
        error: danger,
        onPrimary: Colors.white,
        onSecondary: Colors.white,
        onSurface: textPrimary,
        onError: Colors.white,
      ),
      textTheme: TextTheme(
        headlineLarge: ts(fontSize: 28, fontWeight: FontWeight.w600, color: textPrimary, letterSpacing: -0.5),
        headlineMedium: ts(fontSize: 22, fontWeight: FontWeight.w600, color: textPrimary, letterSpacing: -0.3),
        titleLarge: ts(fontSize: 18, fontWeight: FontWeight.w600, color: textPrimary),
        titleMedium: ts(fontSize: 15, fontWeight: FontWeight.w500, color: textPrimary),
        bodyLarge: ts(fontSize: 16, color: textPrimary, height: 1.6),
        bodyMedium: ts(fontSize: 14, color: textPrimary, height: 1.5),
        bodySmall: ts(fontSize: 12, color: textSecondary),
        labelSmall: ts(fontSize: 11, color: textTertiary, fontWeight: FontWeight.w500),
      ),
      dividerTheme: const DividerThemeData(color: border, thickness: 1),
      appBarTheme: AppBarTheme(
        backgroundColor: surface,
        elevation: 0,
        scrolledUnderElevation: 1,
        titleTextStyle: ts(fontSize: 16, fontWeight: FontWeight.w600, color: textPrimary),
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: border),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface,
        hintStyle: ts(color: textTertiary, fontSize: 15),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: accent, width: 1.5),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: accent,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          textStyle: ts(fontSize: 14, fontWeight: FontWeight.w500),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: textSecondary,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: ts(fontSize: 13, fontWeight: FontWeight.w500),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: surfaceActive,
        contentTextStyle: ts(color: textPrimary, fontSize: 13),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        behavior: SnackBarBehavior.floating,
      ),
      scrollbarTheme: ScrollbarThemeData(
        thumbColor: WidgetStateProperty.all(borderLight),
        trackColor: WidgetStateProperty.all(Colors.transparent),
        thickness: WidgetStateProperty.all(6),
        radius: const Radius.circular(3),
      ),
    );
  }

  static BoxDecoration get cardDecoration => BoxDecoration(
        color: surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: border),
      );

  static BoxDecoration get userBubbleDecoration => BoxDecoration(
        color: userBubble,
        borderRadius: BorderRadius.circular(16),
      );

  static BoxDecoration get assistantBubbleDecoration => BoxDecoration(
        color: assistantBubble,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: border, width: 0.5),
      );
}
