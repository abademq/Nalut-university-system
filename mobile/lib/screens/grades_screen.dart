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
      body: AsyncView<List<dynamic>>(
        load: () async => await s.api.get('/api/me/grades') as List<dynamic>,
        builder: (context, list, _) {
          if (list.isEmpty) return ListView(children: const [EmptyView('لا توجد مقررات')]);
          return ListView(padding: const EdgeInsets.all(12), children: [
            for (final g in list)
              SectionCard(
                title: '${g['course']['code']} — ${g['course']['title']}',
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
