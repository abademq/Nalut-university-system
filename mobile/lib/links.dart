import 'dart:io';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'screens/assignments_screen.dart';
import 'screens/attendance_screen.dart';
import 'screens/grades_screen.dart';
import 'screens/messages_screen.dart';
import 'screens/publications_screen.dart';
import 'screens/results_screen.dart';
import 'state/session.dart';
import 'widgets/common.dart';

/// Where an in-app link (the same `#/...` links the web dashboard uses) leads.
sealed class LinkTarget {
  const LinkTarget();
}

class AppPage extends LinkTarget {
  const AppPage(this.name, [this.id]);
  final String name;
  final int? id;

  @override
  bool operator ==(Object other) => other is AppPage && other.name == name && other.id == id;

  @override
  int get hashCode => Object.hash(name, id);

  @override
  String toString() => 'AppPage($name, $id)';
}

class WebPage extends LinkTarget {
  const WebPage(this.url);
  final String url;
}

class NoTarget extends LinkTarget {
  const NoTarget();
}

/// Pure mapping, unit-tested: `#/messages/12` -> AppPage('thread', 12), and so on.
LinkTarget resolveLink(String? link, {required String baseUrl, required String role}) {
  if (link == null || link.trim().isEmpty) return const NoTarget();
  final l = link.trim();
  if (l.startsWith('https://') || l.startsWith('http://')) return WebPage(l);
  if (!l.startsWith('#/')) return const NoTarget();
  final parts = l.substring(2).split('?').first.split('/').where((p) => p.isNotEmpty).toList();
  final id = parts.length > 1 ? int.tryParse(parts[1]) : null;
  final isStudent = role == 'student';
  final isAdmin = role == 'faculty_admin' || role == 'university_admin';
  switch (parts.isEmpty ? '' : parts[0]) {
    case 'assignments':
      return id != null ? AppPage('assignment', id) : const AppPage('assignments');
    case 'messages':
      return id != null ? AppPage('thread', id) : const AppPage('messages');
    case 'grades':
      return isStudent ? const AppPage('grades') : WebPage('$baseUrl/$l');
    case 'results':
      return isAdmin ? const AppPage('results') : WebPage('$baseUrl/$l');
    case 'attendance':
      return const AppPage('attendance');
    case 'publications':
      return AppPage('publication', id);
    case 'notifications':
    case '':
      return const NoTarget();
  }
  return WebPage('$baseUrl/$l');
}

/// Opens the page for a link. Falls back to showing [title]/[body] when the link has no page.
Future<void> openLink(BuildContext context, Session session, String? link, {String? title, String? body}) async {
  final target = resolveLink(link, baseUrl: session.api.baseUrl, role: session.role);
  Widget? page;
  switch (target) {
    case AppPage(name: 'assignment', :final id):
      page = AssignmentDetailScreen(id: id!);
    case AppPage(name: 'assignments'):
      page = Scaffold(appBar: AppBar(title: const Text('المهام')), body: const AssignmentsScreen());
    case AppPage(name: 'thread', :final id):
      page = ThreadScreen(id: id!);
    case AppPage(name: 'messages'):
      page = const MessagesScreen();
    case AppPage(name: 'grades'):
      page = const GradesScreen();
    case AppPage(name: 'results'):
      page = const ResultsScreen();
    case AppPage(name: 'publication', :final id):
      page = PublicationsScreen(openId: id);
    case AppPage(name: 'attendance'):
      page = Scaffold(appBar: AppBar(title: const Text('الحضور')), body: const AttendanceScreen());
    case WebPage(:final url):
      await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
      return;
    case AppPage():
    case NoTarget():
      page = null;
  }
  if (!context.mounted) return;
  if (page != null) {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => page!));
  } else if (title != null) {
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        content: SingleChildScrollView(child: Text(body ?? '')),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('حسناً'))],
      ),
    );
  }
}

/// Downloads a file through the API and opens it with the phone's default viewer.
Future<void> downloadAndOpen(BuildContext context, Session session, String path, String filename) async {
  try {
    final bytes = await session.api.getBytes(path);
    final dir = await getTemporaryDirectory();
    final safe = filename.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final file = File('${dir.path}/$safe');
    await file.writeAsBytes(bytes, flush: true);
    final res = await OpenFilex.open(file.path);
    if (res.type != ResultType.done && context.mounted) {
      showMessage(context, 'لا يوجد تطبيق لفتح هذا النوع من الملفات (${res.message})', error: true);
    }
  } catch (e) {
    if (context.mounted) showMessage(context, e, error: true);
  }
}
