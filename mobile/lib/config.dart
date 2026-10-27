import 'package:flutter/material.dart';

/// Server used when the user has not chosen another one on the login screen.
/// Override at build time: flutter build apk --dart-define=SERVER_URL=https://example.ly
const String defaultServerUrl =
    String.fromEnvironment('SERVER_URL', defaultValue: 'https://nalut.abade.ly');

class AppColors {
  static const primary = Color(0xFFD6AA21); // the logo's gold: fills and highlights
  static const onPrimary = Color(0xFF2B1E04); // text on gold
  static const primaryText = Color(0xFF7A5C08); // gold dark enough for text and icons on white
  static const primaryTextDark = Color(0xFFE8C372); // the same gold on the dark theme
  static const deep = Color(0xFF45110A); // splash and dark brand surfaces
  static const accent = Color(0xFFD6AA21); // gold on the dark launch screen
  static const maroon = Color(0xFF6E1A10); // the logo's second color
  static const danger = Color(0xFFB42318);
  static const warning = Color(0xFF9A6700);
  static const success = Color(0xFF17803D);
  static const info = Color(0xFF1D5FA8);
}
