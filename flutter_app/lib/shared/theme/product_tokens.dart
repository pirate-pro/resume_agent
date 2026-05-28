import 'package:flutter/material.dart';

import 'app_theme.dart';

enum ProductTone { primary, info, warning, danger, purple, neutral }

class ProductBreakpoints {
  static const shellDesktop = 1100.0;
  static const contentRail = 1040.0;
  static const compact = 760.0;

  const ProductBreakpoints._();
}

class ProductColors {
  static const canvas = Color(0xFFF7FAF9);
  static const surface = Color(0xFFFFFFFF);
  static const surfaceSoft = Color(0xFFF2F8F6);
  static const surfaceMint = Color(0xFFEAF8F3);
  static const border = Color(0xFFDDE8E4);
  static const borderStrong = Color(0xFFC9D8D3);

  static const primary = Color(0xFF0F9B78);
  static const primaryHover = Color(0xFF0B7E62);
  static const primarySoft = Color(0xFFE5F6F1);

  static const info = Color(0xFF2563EB);
  static const infoSoft = Color(0xFFEFF6FF);
  static const warning = Color(0xFFF59E0B);
  static const warningSoft = Color(0xFFFFF7E6);
  static const danger = Color(0xFFEF4444);
  static const dangerSoft = Color(0xFFFFF1F2);
  static const purple = Color(0xFF8B5CF6);
  static const purpleSoft = Color(0xFFF5F3FF);

  static const text = Color(0xFF14211B);
  static const textSecondary = Color(0xFF55645F);
  static const textMuted = Color(0xFF8A9892);
}

class ProductToneStyle {
  final Color color;
  final Color soft;
  final IconData fallbackIcon;

  const ProductToneStyle({
    required this.color,
    required this.soft,
    required this.fallbackIcon,
  });
}

ProductToneStyle productToneStyle(ProductTone tone) {
  return switch (tone) {
    ProductTone.primary => const ProductToneStyle(
        color: ProductColors.primary,
        soft: ProductColors.primarySoft,
        fallbackIcon: Icons.auto_awesome_rounded,
      ),
    ProductTone.info => const ProductToneStyle(
        color: ProductColors.info,
        soft: ProductColors.infoSoft,
        fallbackIcon: Icons.description_outlined,
      ),
    ProductTone.warning => const ProductToneStyle(
        color: ProductColors.warning,
        soft: ProductColors.warningSoft,
        fallbackIcon: Icons.warning_amber_rounded,
      ),
    ProductTone.danger => const ProductToneStyle(
        color: ProductColors.danger,
        soft: ProductColors.dangerSoft,
        fallbackIcon: Icons.priority_high_rounded,
      ),
    ProductTone.purple => const ProductToneStyle(
        color: ProductColors.purple,
        soft: ProductColors.purpleSoft,
        fallbackIcon: Icons.school_outlined,
      ),
    ProductTone.neutral => ProductToneStyle(
        color: AppTheme.textSecondary,
        soft: AppTheme.surfaceHover,
        fallbackIcon: Icons.circle_outlined,
      ),
  };
}

class ProductSurface {
  static BoxDecoration card({
    double radius = 16,
    Color? color,
    Color? borderColor,
  }) {
    return BoxDecoration(
      color: color ?? ProductColors.surface,
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: borderColor ?? ProductColors.border),
      boxShadow: [
        BoxShadow(
          color: Colors.black.withValues(alpha: 0.05),
          blurRadius: 18,
          offset: const Offset(0, 8),
        ),
      ],
    );
  }

  static BoxDecoration softCard({
    double radius = 16,
    ProductTone tone = ProductTone.primary,
  }) {
    final style = productToneStyle(tone);
    return BoxDecoration(
      color: style.soft.withValues(alpha: 0.72),
      borderRadius: BorderRadius.circular(radius),
      border: Border.all(color: style.color.withValues(alpha: 0.14)),
    );
  }

  static BoxDecoration hero() {
    return BoxDecoration(
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          ProductColors.surfaceMint,
          ProductColors.surface,
          ProductColors.infoSoft.withValues(alpha: 0.56),
        ],
      ),
      borderRadius: BorderRadius.circular(18),
      border: Border.all(color: ProductColors.primary.withValues(alpha: 0.18)),
      boxShadow: [
        BoxShadow(
          color: ProductColors.primary.withValues(alpha: 0.08),
          blurRadius: 24,
          offset: const Offset(0, 12),
        ),
      ],
    );
  }
}
