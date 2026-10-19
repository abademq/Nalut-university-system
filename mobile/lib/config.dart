import 'package:flutter/material.dart';

/// Server used when the user has not chosen another one on the login screen.
/// Override at build time: flutter build apk --dart-define=SERVER_URL=https://example.ly
const String defaultServerUrl =
    String.fromEnvironment('SERVER_URL', defaultValue: 'https://nalut.abade.ly');

class AppColors {
  static const primary = Color(0xFF0F5C4D);
  static const accent = Color(0xFFC8A24A);
  static const danger = Color(0xFFB42318);
  static const warning = Color(0xFF9A6700);
  static const success = Color(0xFF17803D);
  static const info = Color(0xFF1D5FA8);
}
