import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class GradesScreen extends StatelessWidget {
  const GradesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('درجاتي ونتائجي')),
      body: AsyncView<(List<dynamic>, Map<String, dynamic>)>(
        load: () async {
          final r = await Future.wait([s.api.get('/api/me/grades'), s.api.get('/api/me/academic')]);
          return (r[0] as List<dynamic>, r[1] as Map<String, dynamic>);
        },
        builder: (context, data, _) {
          final (list, a) = data;
          if (list.isEmpty) return ListView(children: const [EmptyView('لا توجد مقررات')]);
          return ListView(padding: const EdgeInsets.all(12), children: [
            _AcademicCard(a),
            for (final g in list)
              SectionCard(
                title: '${g['course']['code']} — ${g['course']['title']} · ${g['course']['credits']} وحدات',
                trailing: g['published'] == true
                    ? StatusChip(StatusStyle(
                        g['letter'] != null ? '${g['letter']} · ${g['label']}' : 'غير مكتملة',
                        g['passed'] == true ? AppColors.success : AppColors.danger))
                    : const StatusChip(StatusStyle('لم تُعتمد بعد', Colors.grey)),
                child: g['published'] != true
                    ? const Text('تظهر النتائج بعد اعتمادها ونشرها رسمياً من إدارة الكلية.',
                        style: TextStyle(color: Colors.grey))
                    : Column(children: [
                        for (final c in g['components'] as List<dynamic>)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            child: Row(children: [
                              Expanded(child: Text(c['name'] as String)),
                              Text('${g['scores']['${c['id']}'] ?? '—'} / ${c['max_score']}'),
                            ]),
                          ),
                        const Divider(),
                        Row(children: [
                          const Expanded(child: Text('المجموع', style: TextStyle(fontWeight: FontWeight.bold))),
                          Text('${g['total']} / ${g['max_total']} (${g['percent']}%)',
                              style: const TextStyle(fontWeight: FontWeight.bold)),
                        ]),
                      ]),
              ),
          ]);
        },
      ),
    );
  }
}


/// This term's courses and credits, and the credits earned so far.
class _AcademicCard extends StatelessWidget {
  const _AcademicCard(this.a);
  final Map<String, dynamic> a;

  @override
  Widget build(BuildContext context) {
    Widget kpi(String label, Object? value, [String? hint]) => Expanded(
          child: Column(children: [
            Text('${value ?? '—'}', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
            Text(label, textAlign: TextAlign.center, style: const TextStyle(fontSize: 12)),
            if (hint != null) Text(hint, style: const TextStyle(fontSize: 11, color: Colors.grey)),
          ]),
        );
    final max = a['max_credits'] as int? ?? 0;
    return SectionCard(
      title: 'المقررات والوحدات',
      child: Column(children: [
        Row(children: [
          kpi('مقررات هذا الفصل', a['current_courses']),
          kpi('وحدات هذا الفصل', a['current_credits'], max > 0 ? 'الحد ${a['min_credits'] ?? 0}–$max' : null),
          kpi('الوحدات المنجزة', a['earned_credits'], '${a['passed_courses']} مقرر ناجح'),
        ]),
        if (a['load_warning'] != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('عبء هذا الفصل ${a['load_warning']}', style: const TextStyle(color: AppColors.warning)),
          ),
      ]),
    );
  }
}
