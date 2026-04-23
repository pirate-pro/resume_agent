import 'package:flutter/material.dart';

// 设计令牌：将Tailwind的类名翻译成Flutter的常量
class AppTokens {
  // 颜色 (对应Tailwind的 gray, green等色系)
  static const Color shellBg = Color(0xFF171717);      // gray-900
  static const Color canvasBg = Color(0xFF212121);     // gray-800
  static const Color hoverBg = Color(0xFF2F2F2F);      // gray-700
  static const Color textMain = Color(0xFFECECEC);     // gray-100
  static const Color textSub = Color(0xFFB4B4B4);      // gray-400
  static const Color accent = Color(0xFF19C37D);       // emerald-500
  static const Color danger = Color(0xFFEF4444);       // red-500
  static const Color success = Color(0xFF22C55E);      // green-500

  // 间距 (对应Tailwind的 p-, m-, space- 等)
  static const double spacingXs = 4.0;    // p-1
  static const double spacingSm = 8.0;   // p-2
  static const double spacingMd = 16.0;  // p-4
  static const double spacingLg = 24.0;  // p-6
  static const double spacingXl = 32.0;  // p-8

  // 圆角 (对应Tailwind的 rounded-lg 等)
  static const double radiusXs = 4.0;    // rounded
  static const double radiusSm = 6.0;   // rounded-md
  static const double radiusMd = 8.0;   // rounded-lg
  static const double radiusLg = 12.0;  // rounded-xl
  static const double radiusXl = 16.0;  // rounded-2xl

  // 阴影 (对应Tailwind的 shadow 类)
  static const BoxShadow shadowMd = BoxShadow(
    color: Color(0x29000000),
    blurRadius: 8.0,
    offset: Offset(0, 4),
  );
  static const BoxShadow shadowLg = BoxShadow(
    color: Color(0x3D000000),
    blurRadius: 16.0,
    offset: Offset(0, 8),
  );
  static const BoxShadow shadowXl = BoxShadow(
    color: Color(0x4D000000),
    blurRadius: 24.0,
    offset: Offset(0, 12),
  );

  // 字体大小
  static const double fontSizeXs = 10.0;  // text-xs
  static const double fontSizeSm = 12.0;  // text-sm
  static const double fontSizeBase = 14.0; // text-base
  static const double fontSizeLg = 16.0;  // text-lg
  static const double fontSizeXl = 18.0;  // text-xl
  static const double fontSize2Xl = 20.0; // text-2xl

  // 字体权重
  static const FontWeight fontWeightLight = FontWeight.w300;
  static const FontWeight fontWeightNormal = FontWeight.w400;
  static const FontWeight fontWeightMedium = FontWeight.w500;
  static const FontWeight fontWeightSemibold = FontWeight.w600;
  static const FontWeight fontWeightBold = FontWeight.w700;
}

// 消息气泡颜色
class MessageColors {
  static const Color userBubble = Color(0xFF2C2C2C);
  static const Color botBubble = Color(0xFF171717);
  static const Color errorBubble = Color(0xFF3B1B1B);
}