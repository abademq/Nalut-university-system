import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'api/api_client.dart';
import 'api/token_store.dart';
import 'config.dart';
import 'push.dart';
import 'screens/home_shell.dart';
import 'screens/login_screen.dart';
import 'widgets/splash.dart';
import 'state/session.dart';

void main() {
  // Plugins (secure storage, Firebase) talk to the OS through platform channels,
  // which need the binding before any call is made.
  WidgetsFlutterBinding.ensureInitialized();
  final store = SecureTokenStore();
  final session = Session(
    api: ApiClient(store: store, baseUrl: defaultServerUrl),
    store: store,
    push: FirebasePushService(),
  );
  session.start();
  runApp(UniversityApp(session: session));
}

final messengerKey = GlobalKey<ScaffoldMessengerState>();

class UniversityApp extends StatelessWidget {
  const UniversityApp({super.key, required this.session});
  final Session session;

  @override
  Widget build(BuildContext context) {
    session.onForegroundMessage = (m) => messengerKey.currentState?.showSnackBar(SnackBar(
          content: Text((m.body ?? '').isEmpty ? m.title ?? '' : '${m.title}\n${m.body}'),
          duration: const Duration(seconds: 6),
          action: m.link == null
              ? null
              : SnackBarAction(label: 'فتح', onPressed: () => session.openLater(m)),
        ));
    final scheme = ColorScheme.fromSeed(seedColor: AppColors.primary, primary: AppColors.primary);
    return ChangeNotifierProvider.value(
      value: session,
      child: MaterialApp(
        scaffoldMessengerKey: messengerKey,
        title: 'منصة الجامعة',
        debugShowCheckedModeBanner: false,
        locale: const Locale('ar'),
        supportedLocales: const [Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        theme: ThemeData(
          colorScheme: scheme,
          useMaterial3: true,
          scaffoldBackgroundColor: const Color(0xFFF4F6F5),
          cardTheme: CardThemeData(
            elevation: 0,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
              side: const BorderSide(color: Color(0xFFDDE4E1)),
            ),
          ),
          inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
        ),
        darkTheme: ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: AppColors.primary, brightness: Brightness.dark),
          useMaterial3: true,
        ),
        home: Consumer<Session>(
          builder: (context, s, _) => switch (s.status) {
            SessionStatus.loading => const SplashView(),
            SessionStatus.signedOut => const LoginScreen(),
            SessionStatus.signedIn => const HomeShell(),
          },
        ),
      ),
    );
  }
}
