import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state/session.dart';
import '../widgets/common.dart';
import 'grades_screen.dart';
import 'messages_screen.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final u = s.user ?? {};
    return ListView(padding: const EdgeInsets.all(12), children: [
      Card(
        child: ListTile(
          leading: const CircleAvatar(child: Icon(Icons.person)),
          title: Text(u['full_name'] as String? ?? ''),
          subtitle: Text([
            roleLabels[u['role']] ?? '',
            if (u['code'] != null) '${u['code']}',
            if (u['faculty'] != null) '${u['faculty']['name']}',
          ].join(' · ')),
        ),
      ),
      Card(
        child: Column(children: [
          if (s.isStudent)
            ListTile(
              leading: const Icon(Icons.grade_outlined),
              title: const Text('درجاتي ونتائجي'),
              trailing: const Icon(Icons.chevron_left),
              onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const GradesScreen())),
            ),
          ListTile(
            leading: const Icon(Icons.chat_outlined),
            title: const Text('الرسائل'),
            trailing: const Icon(Icons.chevron_left),
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const MessagesScreen())),
          ),
          ListTile(
            leading: const Icon(Icons.open_in_browser),
            title: const Text('بوابة الويب'),
            subtitle: const Text('الطلبات والمعاملات، كلمة المرور، المصادقة الثنائية، لوحة التحكم'),
            trailing: const Icon(Icons.chevron_left),
            onTap: () => launchUrl(Uri.parse(s.api.baseUrl), mode: LaunchMode.externalApplication),
          ),
        ]),
      ),
      Card(
        child: ListTile(
          leading: const Icon(Icons.logout, color: Colors.red),
          title: const Text('تسجيل الخروج', style: TextStyle(color: Colors.red)),
          onTap: () async {
            final ok = await showDialog<bool>(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('تسجيل الخروج؟'),
                actions: [
                  TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
                  FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('خروج')),
                ],
              ),
            );
            if (ok == true) await s.logout();
          },
        ),
      ),
      Padding(
        padding: const EdgeInsets.all(12),
        child: Text(s.api.baseUrl, textAlign: TextAlign.center, textDirection: TextDirection.ltr,
            style: const TextStyle(fontSize: 11, color: Colors.grey)),
      ),
    ]);
  }
}
