import 'package:flutter/material.dart';

/// Server used when the user has not chosen another one on the login screen.
/// Override at build time: flutter build apk --dart-define=SERVER_URL=https://example.ly
const String defaultServerUrl =
    String.fromEnvironment('SERVER_URL', defaultValue: 'https://nalut.abade.ly');

class AppColors {
  static const primary = Color(0xFFC9A646); // soft gold of the logo: fills and highlights
  static const onPrimary = Color(0xFF231B05); // text on gold
  static const primaryText = Color(0xFF7A5D0E); // gold dark enough for text and icons on white
  static const primaryTextDark = Color(0xFFDDBE6E); // the same gold on dark surfaces
  static const deep = Color(0xFF2B2622); // charcoal: headers, splash and the dashboard's sidebar
  static const accent = Color(0xFFC9A646); // gold on the dark launch screen
  static const maroon = Color(0xFF6E1A10); // the logo's second color
  static const danger = Color(0xFFB42318);
  static const warning = Color(0xFF9A6700);
  static const success = Color(0xFF17803D);
  static const info = Color(0xFF1D5FA8);
}
