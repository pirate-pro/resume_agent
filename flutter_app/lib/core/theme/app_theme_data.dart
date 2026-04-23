import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class AppThemeData {
  static ThemeData darkTheme() {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: AppTokens.canvasBg,
      colorScheme: ColorScheme.dark(
        primary: AppTokens.accent,
        secondary: AppTokens.accent,
        surface: AppTokens.shellBg,
        onSurface: AppTokens.textMain,
        error: AppTokens.danger,
        onError: AppTokens.textMain,
      ),
      textTheme: TextTheme(
        displayLarge: TextStyle(
          fontSize: AppTokens.fontSize2Xl,
          fontWeight: AppTokens.fontWeightBold,
          color: AppTokens.textMain,
        ),
        displayMedium: TextStyle(
          fontSize: AppTokens.fontSizeXl,
          fontWeight: AppTokens.fontWeightSemibold,
          color: AppTokens.textMain,
        ),
        displaySmall: TextStyle(
          fontSize: AppTokens.fontSizeLg,
          fontWeight: AppTokens.fontWeightSemibold,
          color: AppTokens.textMain,
        ),
        headlineMedium: TextStyle(
          fontSize: AppTokens.fontSizeLg,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        headlineSmall: TextStyle(
          fontSize: AppTokens.fontSizeBase,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        titleLarge: TextStyle(
          fontSize: AppTokens.fontSizeLg,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        titleMedium: TextStyle(
          fontSize: AppTokens.fontSizeBase,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        titleSmall: TextStyle(
          fontSize: AppTokens.fontSizeSm,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        bodyLarge: TextStyle(
          fontSize: AppTokens.fontSizeBase,
          fontWeight: AppTokens.fontWeightNormal,
          color: AppTokens.textMain,
        ),
        bodyMedium: TextStyle(
          fontSize: AppTokens.fontSizeBase,
          fontWeight: AppTokens.fontWeightNormal,
          color: AppTokens.textMain,
        ),
        bodySmall: TextStyle(
          fontSize: AppTokens.fontSizeSm,
          fontWeight: AppTokens.fontWeightNormal,
          color: AppTokens.textSub,
        ),
        labelLarge: TextStyle(
          fontSize: AppTokens.fontSizeBase,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        labelMedium: TextStyle(
          fontSize: AppTokens.fontSizeSm,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        labelSmall: TextStyle(
          fontSize: AppTokens.fontSizeXs,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textSub,
        ),
      ),
      cardTheme: CardThemeData(
        color: AppTokens.shellBg,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusLg),
        ),
        margin: EdgeInsets.zero,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppTokens.hoverBg,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: BorderSide(color: Colors.transparent),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: BorderSide(color: Colors.transparent),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: BorderSide(color: AppTokens.accent),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: BorderSide(color: AppTokens.danger),
        ),
        focusedErrorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
          borderSide: BorderSide(color: AppTokens.danger),
        ),
        contentPadding: EdgeInsets.symmetric(
          horizontal: AppTokens.spacingMd,
          vertical: AppTokens.spacingSm,
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppTokens.accent,
          foregroundColor: Colors.white,
          padding: EdgeInsets.symmetric(
            horizontal: AppTokens.spacingLg,
            vertical: AppTokens.spacingMd,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppTokens.radiusLg),
          ),
          elevation: 0,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppTokens.accent,
          padding: EdgeInsets.zero,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppTokens.accent,
          side: BorderSide(color: AppTokens.accent),
          padding: EdgeInsets.symmetric(
            horizontal: AppTokens.spacingLg,
            vertical: AppTokens.spacingMd,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppTokens.radiusLg),
          ),
          elevation: 0,
        ),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppTokens.hoverBg,
        selectedColor: AppTokens.accent.withOpacity(0.1),
        secondarySelectedColor: AppTokens.accent.withOpacity(0.2),
        labelStyle: TextStyle(
          fontSize: AppTokens.fontSizeSm,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textSub,
        ),
        padding: EdgeInsets.symmetric(
          horizontal: AppTokens.spacingMd,
          vertical: AppTokens.spacingSm,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusMd),
        ),
      ),
      dividerTheme: DividerThemeData(
        color: Colors.white.withOpacity(0.1),
        thickness: 1,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppTokens.shellBg,
        elevation: 0,
        titleTextStyle: TextStyle(
          fontSize: AppTokens.fontSizeLg,
          fontWeight: AppTokens.fontWeightMedium,
          color: AppTokens.textMain,
        ),
        iconTheme: IconThemeData(color: AppTokens.textMain),
        actionsIconTheme: IconThemeData(color: AppTokens.textMain),
      ),
      bottomNavigationBarTheme: BottomNavigationBarThemeData(
        backgroundColor: AppTokens.shellBg,
        selectedItemColor: AppTokens.accent,
        unselectedItemColor: AppTokens.textSub,
        elevation: 0,
      ),
      drawerTheme: DrawerThemeData(
        backgroundColor: AppTokens.shellBg,
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: AppTokens.shellBg,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTokens.radiusLg),
        ),
      ),
      bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: AppTokens.shellBg,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(
            top: Radius.circular(AppTokens.radiusLg),
          ),
        ),
      ),
    );
  }
}
