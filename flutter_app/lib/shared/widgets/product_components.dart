import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/product_tokens.dart';

class ProductCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry padding;
  final ProductTone? tone;
  final bool soft;

  const ProductCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(16),
    this.tone,
    this.soft = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: padding,
      decoration: soft
          ? ProductSurface.softCard(tone: tone ?? ProductTone.primary)
          : ProductSurface.card(),
      child: child,
    );
  }
}

class ProductSection extends StatelessWidget {
  final String title;
  final String? subtitle;
  final IconData icon;
  final ProductTone tone;
  final Widget child;
  final Widget? trailing;

  const ProductSection({
    super.key,
    required this.title,
    required this.icon,
    required this.child,
    this.subtitle,
    this.tone = ProductTone.primary,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return ProductCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              ProductIconTile(icon: icon, tone: tone, size: 36),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: AppTheme.ts(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    if (subtitle?.trim().isNotEmpty == true) ...[
                      const SizedBox(height: 2),
                      Text(
                        subtitle!.trim(),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11,
                          color: ProductColors.textMuted,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              if (trailing != null) ...[
                const SizedBox(width: 8),
                IconTheme(
                  data: IconThemeData(color: style.color, size: 16),
                  child: trailing!,
                ),
              ],
            ],
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

class ProductIconTile extends StatelessWidget {
  final IconData icon;
  final ProductTone tone;
  final double size;

  const ProductIconTile({
    super.key,
    required this.icon,
    this.tone = ProductTone.primary,
    this.size = 44,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: style.soft,
        borderRadius: BorderRadius.circular(size <= 36 ? 12 : 16),
        border: Border.all(color: style.color.withValues(alpha: 0.12)),
      ),
      child: Icon(icon, size: size * 0.46, color: style.color),
    );
  }
}

class ProductTag extends StatelessWidget {
  final String label;
  final ProductTone tone;
  final IconData? icon;

  const ProductTag({
    super.key,
    required this.label,
    this.tone = ProductTone.primary,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
      decoration: BoxDecoration(
        color: style.soft.withValues(alpha: 0.86),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: style.color.withValues(alpha: 0.14)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 12, color: style.color),
            const SizedBox(width: 5),
          ],
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: AppTheme.ts(
              fontSize: 10.8,
              fontWeight: FontWeight.w800,
              color: style.color,
            ),
          ),
        ],
      ),
    );
  }
}

class ProductScoreRing extends StatelessWidget {
  final int? score;
  final double size;
  final String label;
  final String suffix;

  const ProductScoreRing({
    super.key,
    required this.score,
    this.size = 84,
    this.label = '匹配度',
    this.suffix = '',
  });

  @override
  Widget build(BuildContext context) {
    final safeScore = score?.clamp(0, 100);
    final color = _scoreColor(safeScore);
    final value = safeScore == null ? null : safeScore / 100;
    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        alignment: Alignment.center,
        children: [
          SizedBox.expand(
            child: CircularProgressIndicator(
              value: value?.toDouble(),
              strokeWidth: size >= 80 ? 7 : 5,
              strokeCap: StrokeCap.round,
              color: color,
              backgroundColor: color.withValues(alpha: 0.12),
            ),
          ),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              RichText(
                text: TextSpan(
                  children: [
                    TextSpan(
                      text: safeScore?.toString() ?? '-',
                      style: AppTheme.ts(
                        fontSize: size >= 80 ? 25 : 17,
                        height: 1,
                        fontWeight: FontWeight.w900,
                        color: ProductColors.text,
                      ),
                    ),
                    if (suffix.isNotEmpty)
                      TextSpan(
                        text: suffix,
                        style: AppTheme.ts(
                          fontSize: size >= 80 ? 13 : 10,
                          height: 1,
                          fontWeight: FontWeight.w900,
                          color: ProductColors.text,
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 3),
              Text(
                label,
                style: AppTheme.ts(
                  fontSize: size >= 80 ? 10.5 : 9,
                  height: 1,
                  fontWeight: FontWeight.w800,
                  color: ProductColors.textMuted,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class ProductMetricCard extends StatelessWidget {
  final String label;
  final String value;
  final String? trend;
  final IconData icon;
  final ProductTone tone;

  const ProductMetricCard({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
    this.trend,
    this.tone = ProductTone.primary,
  });

  @override
  Widget build(BuildContext context) {
    return ProductCard(
      padding: const EdgeInsets.fromLTRB(11, 10, 11, 10),
      child: Row(
        children: [
          ProductIconTile(icon: icon, tone: tone, size: 36),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 21,
                    height: 1,
                    fontWeight: FontWeight.w900,
                    color: ProductColors.text,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: AppTheme.ts(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w700,
                    color: ProductColors.textSecondary,
                  ),
                ),
                if (trend?.trim().isNotEmpty == true) ...[
                  const SizedBox(height: 3),
                  Text(
                    trend!.trim(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: AppTheme.ts(
                      fontSize: 10.5,
                      fontWeight: FontWeight.w700,
                      color: productToneStyle(tone).color,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class ProductActionTile extends StatelessWidget {
  final String title;
  final String subtitle;
  final IconData icon;
  final ProductTone tone;
  final String? badge;
  final VoidCallback? onTap;
  final String? actionLabel;
  final VoidCallback? onSecondaryTap;
  final String? secondaryActionLabel;

  const ProductActionTile({
    super.key,
    required this.title,
    required this.subtitle,
    required this.icon,
    this.tone = ProductTone.primary,
    this.badge,
    this.onTap,
    this.actionLabel,
    this.onSecondaryTap,
    this.secondaryActionLabel,
  });

  @override
  Widget build(BuildContext context) {
    final style = productToneStyle(tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
          decoration: BoxDecoration(
            color: style.soft.withValues(alpha: 0.58),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: style.color.withValues(alpha: 0.12)),
          ),
          child: Row(
            children: [
              ProductIconTile(icon: icon, tone: tone, size: 34),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: AppTheme.ts(
                              fontSize: 12.4,
                              fontWeight: FontWeight.w900,
                              color: ProductColors.text,
                            ),
                          ),
                        ),
                        if (badge?.trim().isNotEmpty == true) ...[
                          const SizedBox(width: 8),
                          ProductTag(label: badge!.trim(), tone: tone),
                        ],
                      ],
                    ),
                    if (subtitle.trim().isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        subtitle.trim(),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: AppTheme.ts(
                          fontSize: 11,
                          height: 1.35,
                          color: ProductColors.textSecondary,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        actionLabel?.trim().isNotEmpty == true
                            ? actionLabel!.trim()
                            : '进入',
                        style: AppTheme.ts(
                          fontSize: 11,
                          fontWeight: FontWeight.w900,
                          color: style.color,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Icon(
                        Icons.arrow_forward_rounded,
                        size: 15,
                        color: style.color,
                      ),
                    ],
                  ),
                  if (onSecondaryTap != null &&
                      secondaryActionLabel?.trim().isNotEmpty == true) ...[
                    const SizedBox(height: 5),
                    InkWell(
                      borderRadius: BorderRadius.circular(999),
                      onTap: onSecondaryTap,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 4,
                        ),
                        decoration: BoxDecoration(
                          color: ProductColors.surface,
                          borderRadius: BorderRadius.circular(999),
                          border: Border.all(
                            color: style.color.withValues(alpha: 0.18),
                          ),
                        ),
                        child: Text(
                          secondaryActionLabel!.trim(),
                          style: AppTheme.ts(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w900,
                            color: style.color,
                          ),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

Color _scoreColor(int? score) {
  if (score == null) return ProductColors.textMuted;
  if (score >= 80) return ProductColors.primary;
  if (score >= 60) return ProductColors.warning;
  return ProductColors.danger;
}
