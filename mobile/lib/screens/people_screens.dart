import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../links.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'messages_screen.dart';
import 'reports_screen.dart';

/// The students the account may follow (administration, supervisors, offices): search and open one.
class StudentsScreen extends StatefulWidget {
  const StudentsScreen({super.key});

  @override
  State<StudentsScreen> createState() => _StudentsScreenState();
}

class _StudentsScreenState extends State<StudentsScreen> {
  final _q = TextEditingController();
  String _query = '';

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('الطلبة')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: TextField(
            controller: _q,
            textInputAction: TextInputAction.search,
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'الاسم أو رقم القيد أو الهاتف'),
            onSubmitted: (v) => setState(() => _query = v.trim()),
          ),
        ),
        Expanded(
          child: AsyncView<Map<String, dynamic>>(
            key: ValueKey(_query),
            load: () async => await s.api.get('/api/students?limit=100&q=${Uri.encodeQueryComponent(_query)}')
                as Map<String, dynamic>,
            builder: (context, r, _) {
              final items = (r['items'] as List?) ?? const [];
              if (items.isEmpty) return ListView(children: const [EmptyView('لا يوجد طلبة')]);
              return ListView(children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  child: Text('${r['total']} طالب', style: const TextStyle(color: Colors.grey)),
                ),
                for (final st in items)
                  ListTile(
                    leading: const CircleAvatar(child: Icon(Icons.person_outline)),
                    title: Text('${st['full_name']}'),
                    subtitle: Text([st['code'], st['department'], if (st['cohort'] != null) 'دفعة ${st['cohort']}']
                        .whereType<String>()
                        .join(' · ')),
                    trailing: const Icon(Icons.chevron_left),
                    onTap: () => Navigator.push(context, MaterialPageRoute(
                        builder: (_) => StudentDetailScreen(id: st['id'] as int, name: st['full_name'] as String))),
                  ),
              ]);
            },
          ),
        ),
      ]),
    );
  }
}

/// One student: how to reach them, then their record (results, courses, plan).
class StudentDetailScreen extends StatelessWidget {
  const StudentDetailScreen({super.key, required this.id, required this.name});
  final int id;
  final String name;

  Future<void> _open(BuildContext context, String url) async {
    if (!await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication) && context.mounted) {
      showMessage(context, 'تعذر فتح التطبيق المناسب على الهاتف', error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: Text(name)),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => await s.api.get('/api/reports/person/$id') as Map<String, dynamic>,
        builder: (context, r, _) {
          final c = (r['contact'] as Map?) ?? const {};
          final who = r['user'] as Map;
          final tr = r['transcript'] as Map?;
          final ac = r['academic'] as Map?;
          return ListView(padding: const EdgeInsets.all(12), children: [
            SectionCard(
              title: 'التواصل',
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Text([who['code'], c['faculty'], c['department'], if (c['cohort'] != null) 'دفعة ${c['cohort']}']
                    .whereType<String>()
                    .join(' · ')),
                const SizedBox(height: 8),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  if (c['can_message'] == true)
                    FilledButton.icon(
                      icon: const Icon(Icons.chat_outlined),
                      label: const Text('مراسلة'),
                      onPressed: () async {
                        final cid = await Navigator.push<int>(context, MaterialPageRoute(
                            builder: (_) => NewConversationScreen(to: {'id': id, 'full_name': name})));
                        if (cid != null && context.mounted) {
                          Navigator.push(context, MaterialPageRoute(builder: (_) => ThreadScreen(id: cid)));
                        }
                      },
                    ),
                  if (c['phone'] != null) ...[
                    OutlinedButton.icon(
                        icon: const Icon(Icons.call_outlined),
                        label: Text('${c['phone']}', textDirection: TextDirection.ltr),
                        onPressed: () => _open(context, 'tel:${c['phone']}')),
                    OutlinedButton.icon(
                        icon: const Icon(Icons.sms_outlined),
                        label: const Text('رسالة نصية'),
                        onPressed: () => _open(context, 'sms:${c['phone']}')),
                  ],
                  if (c['email'] != null)
                    OutlinedButton.icon(
                        icon: const Icon(Icons.email_outlined),
                        label: const Text('بريد'),
                        onPressed: () => _open(context, 'mailto:${c['email']}')),
                ]),
                if (c['guardian_phone'] != null) ...[
                  const SizedBox(height: 8),
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.family_restroom),
                    title: Text('ولي الأمر: ${c['guardian_name'] ?? ''}${c['guardian_relation'] != null ? ' (${c['guardian_relation']})' : ''}'),
                    subtitle: Text('${c['guardian_phone']}', textDirection: TextDirection.ltr),
                    trailing: IconButton(
                        icon: const Icon(Icons.call_outlined), onPressed: () => _open(context, 'tel:${c['guardian_phone']}')),
                  ),
                ],
              ]),
            ),
            if (tr != null)
              SectionCard(
                title: 'النتائج والمعدل',
                child: Text('المعدل التراكمي: ${tr['cumulative_average'] ?? '—'}${tr['cumulative_average'] != null ? '%' : ''}'
                    '${tr['cumulative_label'] != null ? ' (${tr['cumulative_label']})' : ''} · الوحدات المنجزة: ${tr['earned_credits']}'),
              ),
            if (ac != null)
              SectionCard(
                title: 'هذا الفصل',
                child: Text('${ac['current_courses']} مقررات · ${ac['current_credits']} وحدة'
                    '${ac['load_warning'] != null ? '\n${ac['load_warning']}' : ''}'),
              ),
            ListTile(
              leading: const Icon(Icons.insights_outlined),
              title: const Text('المتابعة في كل مقرر'),
              subtitle: const Text('الحضور والمهام والدرجات'),
              trailing: const Icon(Icons.chevron_left),
              onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => PersonReportScreen(userId: id, title: name))),
            ),
            if (tr != null)
              for (final t in (tr['advice'] as List? ?? const []))
                Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2), child: Text('• ${t['text']}')),
          ]);
        },
      ),
    );
  }
}

/// Regulations and the rules the platform applies.
class RegulationsScreen extends StatelessWidget {
  const RegulationsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('اللوائح والقواعد')),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => await s.api.get('/api/regulations') as Map<String, dynamic>,
        builder: (context, d, _) => ListView(padding: const EdgeInsets.all(12), children: [
          SectionCard(
            title: 'القواعد المطبقة في المنصة',
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final a in (d['applied'] as List)) ...[
                Padding(
                  padding: const EdgeInsets.only(top: 8, bottom: 2),
                  child: Text('${a['title']}', style: const TextStyle(fontWeight: FontWeight.bold)),
                ),
                for (final i in (a['items'] as List)) Text('• $i'),
              ],
            ]),
          ),
          if ((d['items'] as List).isEmpty) const EmptyView('لم تُنشر لوائح بعد'),
          for (final r in (d['items'] as List))
            Card(
              child: ExpansionTile(
                title: Text('${r['title']}'),
                subtitle: Text([r['category_label'], r['faculty']].whereType<String>().join(' · ')),
                childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if ((r['body'] as String).isNotEmpty) Text('${r['body']}'),
                  if (r['file'] != null)
                    TextButton.icon(
                      icon: const Icon(Icons.download_outlined),
                      label: Text('${r['file']['name']}'),
                      onPressed: () => downloadAndOpen(context, s, '/api/files/${r['file']['id']}', r['file']['name'] as String),
                    ),
                ],
              ),
            ),
        ]),
      ),
    );
  }
}
