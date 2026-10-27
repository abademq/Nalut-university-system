import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'api/api_client.dart';
import 'api/token_store.dart';
import 'config.dart';
import 'launch.dart';
import 'push.dart';
import 'screens/home_shell.dart';
import 'screens/login_screen.dart';
import 'widgets/splash.dart';
import 'state/session.dart';

Future<void> main() async {
  // Plugins (secure storage, Firebase) talk to the OS through platform channels,
  // which need the binding before any call is made.
  WidgetsFlutterBinding.ensureInitialized();
  final launch = await LaunchStore.load();
  final store = SecureTokenStore();
  final session = Session(
    api: ApiClient(store: store, baseUrl: defaultServerUrl),
    store: store,
    push: FirebasePushService(),
  );
  session.start();
  runApp(UniversityApp(session: session, launch: launch));
  // refresh the launch screen for the next start; once signed in, for the user's university
  var refreshedFor = launch.universityId;
  LaunchStore.refresh(session.api, launch);
  session.addListener(() {
    final uni = (session.user?['university'] as Map?)?['id'] as int?;
    if (uni != null && uni != refreshedFor) {
      refreshedFor = uni;
      LaunchStore.refresh(session.api, launch, universityId: uni);
    }
  });
}

final messengerKey = GlobalKey<ScaffoldMessengerState>();

class UniversityApp extends StatelessWidget {
  const UniversityApp({super.key, required this.session, this.launch});
  final Session session;

  /// The launch screen chosen by the platform administrator; null shows the default one
  /// only while the session is restored (tests).
  final LaunchConfig? launch;

  @override
  Widget build(BuildContext context) {
    session.onForegroundMessage = (m) => messengerKey.currentState?.showSnackBar(SnackBar(
          content: Text((m.body ?? '').isEmpty ? m.title ?? '' : '${m.title}\n${m.body}'),
          duration: const Duration(seconds: 6),
          action: m.link == null
              ? null
              : SnackBarAction(label: 'فتح', onPressed: () => session.openLater(m)),
        ));
    return ChangeNotifierProvider.value(
      value: session,
      child: ValueListenableBuilder<ThemeMode>(
        valueListenable: session.themeMode,
        builder: (context, mode, home) => MaterialApp(
          scaffoldMessengerKey: messengerKey,
          title: 'منصة الجامعة',
          debugShowCheckedModeBanner: false,
          locale: const Locale('ar'),
          supportedLocales: const [Locale('ar')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          themeMode: mode,
          theme: _theme(Brightness.light),
          darkTheme: _theme(Brightness.dark),
          home: home,
        ),
        child: Consumer<Session>(builder: (context, s, _) {
          final page = switch (s.status) {
            SessionStatus.loading => const SplashView(),
            SessionStatus.signedOut => const LoginScreen(),
            SessionStatus.signedIn => const HomeShell(),
          };
          final cfg = launch;
          if (cfg == null) return page;
          return LaunchGate(
            config: cfg,
            loading: s.status == SessionStatus.loading,
            playSound: NativeNotifications.playLaunchSound,
            child: page,
          );
        }),
      ),
    );
  }
}

/// Light and dark themes in the university's gold: gold fills with dark text on them, and a
/// gold dark enough (light theme) or light enough (dark theme) for text-only buttons and links.
ThemeData _theme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: AppColors.primary,
    brightness: brightness,
    primary: dark ? const Color(0xFFD9AD4F) : AppColors.primary,
    onPrimary: AppColors.onPrimary,
    surface: dark ? const Color(0xFF1D1716) : null,
  );
  final linkGold = ButtonStyle(
      foregroundColor: WidgetStateProperty.all(dark ? AppColors.primaryTextDark : AppColors.primaryText));
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    scaffoldBackgroundColor: dark ? const Color(0xFF141010) : const Color(0xFFF7F5F2),
    cardTheme: CardThemeData(
      elevation: 0,
      color: dark ? const Color(0xFF1D1716) : Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: dark ? const Color(0xFF3B2F2B) : const Color(0xFFE8E0DB)),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
    textButtonTheme: TextButtonThemeData(style: linkGold),
    outlinedButtonTheme: OutlinedButtonThemeData(style: linkGold),
  );
}
