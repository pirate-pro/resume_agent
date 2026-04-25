import 'package:flutter/material.dart';

class AppTheme {
  static const String _fontFamily = 'Inter';

  static const _AppPalette _darkPalette = _AppPalette(
    bg: Color(0xFF0A0D11),
    surface: Color(0xFF151A1F),
    surfaceHover: Color(0xFF1B2128),
    surfaceActive: Color(0xFF222A33),
    border: Color(0xFF28303A),
    borderLight: Color(0xFF36414C),
    textPrimary: Color(0xFFECECEC),
    textSecondary: Color(0xFF8E8E8E),
    textTertiary: Color(0xFF5A5A5A),
    accent: Color(0xFF10A37F),
    accentHover: Color(0xFF0E8C6C),
    danger: Color(0xFFEF4444),
    userBubble: Color(0xFF2A323D),
    assistantBubble: Color(0xFF171C22),
    shellGradientA: Color(0xFF091017),
    shellGradientB: Color(0xFF0D1218),
    shellGradientC: Color(0xFF0A0D11),
    panelShadow: Color(0x47000000),
  );

  static const _AppPalette _lightPalette = _AppPalette(
    bg: Color(0xFFF4F7F8),
    surface: Color(0xFFFFFFFF),
    surfaceHover: Color(0xFFF1F5F7),
    surfaceActive: Color(0xFFE6EDF1),
    border: Color(0xFFD6DEE4),
    borderLight: Color(0xFFC3CDD6),
    textPrimary: Color(0xFF15202B),
    textSecondary: Color(0xFF52606D),
    textTertiary: Color(0xFF7A8794),
    accent: Color(0xFF0F9B78),
    accentHover: Color(0xFF0D8466),
    danger: Color(0xFFDC2626),
    userBubble: Color(0xFFE4ECF6),
    assistantBubble: Color(0xFFFFFFFF),
    shellGradientA: Color(0xFFF9FBFC),
    shellGradientB: Color(0xFFF1F6F7),
    shellGradientC: Color(0xFFEAF1F4),
    panelShadow: Color(0x16000000),
  );

  static _AppPalette _activePalette = _darkPalette;

  static void applyMode(ThemeMode mode) {
    _activePalette = mode == ThemeMode.light ? _lightPalette : _darkPalette;
  }

  static bool get isDark => identical(_activePalette, _darkPalette);

  static Color get bg => _activePalette.bg;
  static Color get surface => _activePalette.surface;
  static Color get surfaceHover => _activePalette.surfaceHover;
  static Color get surfaceActive => _activePalette.surfaceActive;
  static Color get border => _activePalette.border;
  static Color get borderLight => _activePalette.borderLight;
  static Color get textPrimary => _activePalette.textPrimary;
  static Color get textSecondary => _activePalette.textSecondary;
  static Color get textTertiary => _activePalette.textTertiary;
  static Color get accent => _activePalette.accent;
  static Color get accentHover => _activePalette.accentHover;
  static Color get danger => _activePalette.danger;
  static Color get userBubble => _activePalette.userBubble;
  static Color get assistantBubble => _activePalette.assistantBubble;

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

  static ThemeData get dark => _buildTheme(_darkPalette, Brightness.dark);
  static ThemeData get light => _buildTheme(_lightPalette, Brightness.light);

  static ThemeData _buildTheme(_AppPalette palette, Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    return ThemeData(
      brightness: brightness,
      useMaterial3: true,
      scaffoldBackgroundColor: palette.bg,
      colorScheme: ColorScheme(
        brightness: brightness,
        primary: palette.accent,
        onPrimary: Colors.white,
        secondary: palette.accent,
        onSecondary: Colors.white,
        error: palette.danger,
        onError: Colors.white,
        surface: palette.surface,
        onSurface: palette.textPrimary,
      ),
      textTheme: TextTheme(
        headlineLarge: ts(
          fontSize: 28,
          fontWeight: FontWeight.w600,
          color: palette.textPrimary,
          letterSpacing: -0.5,
        ),
        headlineMedium: ts(
          fontSize: 22,
          fontWeight: FontWeight.w600,
          color: palette.textPrimary,
          letterSpacing: -0.3,
        ),
        titleLarge: ts(
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: palette.textPrimary,
        ),
        titleMedium: ts(
          fontSize: 15,
          fontWeight: FontWeight.w500,
          color: palette.textPrimary,
        ),
        bodyLarge: ts(fontSize: 16, color: palette.textPrimary, height: 1.6),
        bodyMedium: ts(fontSize: 14, color: palette.textPrimary, height: 1.5),
        bodySmall: ts(fontSize: 12, color: palette.textSecondary),
        labelSmall: ts(
          fontSize: 11,
          color: palette.textTertiary,
          fontWeight: FontWeight.w500,
        ),
      ),
      dividerTheme: DividerThemeData(color: palette.border, thickness: 1),
      appBarTheme: AppBarTheme(
        backgroundColor: palette.surface,
        elevation: 0,
        scrolledUnderElevation: 1,
        titleTextStyle: ts(
          fontSize: 16,
          fontWeight: FontWeight.w600,
          color: palette.textPrimary,
        ),
      ),
      cardTheme: CardThemeData(
        color: palette.surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: palette.border),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: palette.surface,
        hintStyle: ts(color: palette.textTertiary, fontSize: 15),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: palette.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: palette.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: palette.accent, width: 1.5),
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: palette.accent,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          textStyle: ts(fontSize: 14, fontWeight: FontWeight.w500),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: palette.textSecondary,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: ts(fontSize: 13, fontWeight: FontWeight.w500),
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: palette.surfaceActive,
        contentTextStyle: ts(color: palette.textPrimary, fontSize: 13),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        behavior: SnackBarBehavior.floating,
      ),
      scrollbarTheme: ScrollbarThemeData(
        thumbColor: WidgetStateProperty.all(palette.borderLight),
        trackColor: WidgetStateProperty.all(Colors.transparent),
        thickness: WidgetStateProperty.all(6),
        radius: const Radius.circular(3),
      ),
      splashColor: palette.accent.withValues(alpha: isDark ? 0.14 : 0.08),
      highlightColor: Colors.transparent,
      hoverColor: palette.surfaceHover.withValues(alpha: isDark ? 0.72 : 0.9),
    );
  }

  static BoxDecoration get cardDecoration => BoxDecoration(
        color: surface,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: border),
      );

  static BoxDecoration get appShellDecoration => BoxDecoration(
        gradient: LinearGradient(
          colors: [
            _activePalette.shellGradientA,
            _activePalette.shellGradientB,
            _activePalette.shellGradientC,
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
      );

  static BoxDecoration floatingPanelDecoration({
    double radius = 28,
    double alpha = 0.88,
  }) =>
      BoxDecoration(
        color: surface.withValues(alpha: alpha),
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: borderLight.withValues(alpha: 0.75)),
        boxShadow: [
          BoxShadow(
            color: _activePalette.panelShadow,
            blurRadius: isDark ? 40 : 28,
            offset: const Offset(0, 20),
          ),
        ],
      );

  static BoxDecoration get userBubbleDecoration => BoxDecoration(
        color: userBubble,
        borderRadius: BorderRadius.circular(22),
      );

  static BoxDecoration get assistantBubbleDecoration => BoxDecoration(
        color: assistantBubble,
        borderRadius: BorderRadius.circular(22),
        border: Border.all(color: border, width: 0.5),
      );
}

class _AppPalette {
  final Color bg;
  final Color surface;
  final Color surfaceHover;
  final Color surfaceActive;
  final Color border;
  final Color borderLight;
  final Color textPrimary;
  final Color textSecondary;
  final Color textTertiary;
  final Color accent;
  final Color accentHover;
  final Color danger;
  final Color userBubble;
  final Color assistantBubble;
  final Color shellGradientA;
  final Color shellGradientB;
  final Color shellGradientC;
  final Color panelShadow;

  const _AppPalette({
    required this.bg,
    required this.surface,
    required this.surfaceHover,
    required this.surfaceActive,
    required this.border,
    required this.borderLight,
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.accent,
    required this.accentHover,
    required this.danger,
    required this.userBubble,
    required this.assistantBubble,
    required this.shellGradientA,
    required this.shellGradientB,
    required this.shellGradientC,
    required this.panelShadow,
  });
}
