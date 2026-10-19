import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/session.dart';
import 'assignments_screen.dart';
import 'attendance_screen.dart';
import 'home_screen.dart';
import 'more_screen.dart';
import 'notifications_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> with WidgetsBindingObserver {
  int _index = 0;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _poll = Timer.periodic(const Duration(seconds: 60), (_) => context.read<Session>().refreshUnread());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _poll?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) context.read<Session>().refreshUnread();
  }

  @override
  Widget build(BuildContext context) {
    final session = context.watch<Session>();
    final tabs = <(String, IconData, Widget)>[
      ('الرئيسية', Icons.home_outlined, const HomeScreen()),
      if (session.isStudent || session.isInstructor) ('المهام', Icons.assignment_outlined, const AssignmentsScreen()),
      if (session.canCheckIn) ('الحضور', Icons.qr_code_scanner, const AttendanceScreen()),
      ('الإشعارات', Icons.notifications_outlined, const NotificationsScreen()),
      ('المزيد', Icons.menu, const MoreScreen()),
    ];
    final index = _index.clamp(0, tabs.length - 1);
    return Scaffold(
      appBar: AppBar(title: Text(tabs[index].$1)),
      body: IndexedStack(index: index, children: [for (final t in tabs) t.$3]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: [
          for (final t in tabs)
            NavigationDestination(
              icon: t.$1 == 'الإشعارات' && session.unread > 0
                  ? Badge(label: Text('${session.unread}'), child: Icon(t.$2))
                  : Icon(t.$2),
              label: t.$1,
            ),
        ],
      ),
    );
  }
}
