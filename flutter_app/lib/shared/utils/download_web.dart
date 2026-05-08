// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use

import 'dart:html' as html;

void openDownloadUrl(String url) {
  html.AnchorElement(href: url)
    ..target = '_blank'
    ..rel = 'noopener'
    ..click();
}
