import 'package:flutter/material.dart';

import '../config.dart';

/// Shown while the saved session is restored. Same colors and logo as the native splash,
/// so the hand-over from Android's launch screen is seamless.
class SplashView extends StatelessWidget {
  const SplashView({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.deep,
      body: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Image.asset('assets/logo_on_dark.png', width: 112, height: 112),
          const SizedBox(height: 20),
          const Text('منصة الجامعة الذكية',
              style: TextStyle(color: Color(0xFFF7F4EC), fontSize: 24, fontWeight: FontWeight.bold)),
          const SizedBox(height: 6),
          const Text('جامعة نالوت', style: TextStyle(color: AppColors.accent, fontSize: 16)),
          const SizedBox(height: 36),
          const SizedBox(
            width: 28,
            height: 28,
            child: CircularProgressIndicator(strokeWidth: 2.5, color: AppColors.accent),
          ),
        ]),
      ),
    );
  }
}
