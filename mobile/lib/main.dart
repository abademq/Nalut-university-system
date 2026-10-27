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

/// Light and dark themes, formal and calm like the dashboard: a charcoal header, soft gold fills
/// with dark text on them, and a gold dark enough (light theme) or light enough (dark theme) for
/// text-only buttons and links.
ThemeData _theme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final border = dark ? const Color(0xFF35302C) : const Color(0xFFE5E1DA);
  final surface = dark ? const Color(0xFF1E1B19) : Colors.white;
  final scheme = ColorScheme.fromSeed(
    seedColor: AppColors.primary,
    brightness: brightness,
    primary: dark ? const Color(0xFFD1B05A) : AppColors.primary,
    onPrimary: AppColors.onPrimary,
    surface: dark ? const Color(0xFF1E1B19) : null,
    outlineVariant: border,
  );
  final linkGold = ButtonStyle(
      foregroundColor: WidgetStateProperty.all(dark ? AppColors.primaryTextDark : AppColors.primaryText));
  const header = Colors.white;
  return ThemeData(
    colorScheme: scheme,
    useMaterial3: true,
    fontFamily: 'IBM Plex Sans Arabic',
    scaffoldBackgroundColor: dark ? const Color(0xFF151311) : const Color(0xFFF5F4F1),
    appBarTheme: AppBarTheme(
      backgroundColor: dark ? const Color(0xFF0F0D0C) : AppColors.deep,
      foregroundColor: header,
      surfaceTintColor: Colors.transparent,
      centerTitle: false,
      titleTextStyle: const TextStyle(
          fontFamily: 'IBM Plex Sans Arabic', fontSize: 18, fontWeight: FontWeight.w600, color: header),
    ),
    tabBarTheme: const TabBarThemeData(
      labelColor: Color(0xFFEAD59C),
      unselectedLabelColor: Color(0xD9FFFFFF),
      indicatorColor: AppColors.primary,
      dividerColor: Colors.transparent,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: surface,
      indicatorColor: dark ? const Color(0xFF2E281C) : const Color(0xFFF5EEDC),
      surfaceTintColor: Colors.transparent,
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      color: surface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12), side: BorderSide(color: border)),
    ),
    dividerTheme: DividerThemeData(color: border),
    inputDecorationTheme: InputDecorationTheme(
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: border)),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          textStyle: const TextStyle(fontFamily: 'IBM Plex Sans Arabic', fontWeight: FontWeight.w600)),
    ),
    textButtonTheme: TextButtonThemeData(style: linkGold),
    outlinedButtonTheme: OutlinedButtonThemeData(style: linkGold),
  );
}
