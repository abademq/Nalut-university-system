import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nalut_university/launch.dart';
import 'package:nalut_university/widgets/splash.dart';

void main() {
  test('launch config reads the server answer and falls back on bad values', () {
    final c = LaunchConfig.fromJson({
      'university_id': 3,
      'launch': {'title': 'جامعة نالوت', 'duration_ms': 2500, 'background': '#112233', 'accent': 'bad', 'sound': 'harp'},
      'image_version': null,
    });
    expect(c.universityId, 3);
    expect(c.durationMs, 2500);
    expect(c.background, const Color(0xFF112233));
    expect(c.accent, const LaunchConfig().accent);
    expect(c.sound, 'harp');
    expect(c.image, isNull);
  });

  testWidgets('launch screen stays for the chosen time, plays the sound once, then shows the app', (tester) async {
    final played = <String>[];
    Widget app(bool loading) => MaterialApp(
          home: LaunchGate(
            config: const LaunchConfig(durationMs: 1500, title: 'شاشة البداية', sound: 'welcome'),
            loading: loading,
            playSound: (s) async => played.add(s),
            child: const Text('التطبيق'),
          ),
        );
    await tester.pumpWidget(app(false));
    expect(find.text('شاشة البداية'), findsOneWidget);
    await tester.pump(const Duration(milliseconds: 1000));
    expect(find.text('التطبيق'), findsNothing);
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pumpAndSettle();
    expect(find.text('التطبيق'), findsOneWidget);
    expect(find.byType(SplashView), findsNothing);
    await tester.pumpWidget(app(false));
    expect(played, ['welcome']);
  });
}
