import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// The student's study plan: what must be passed this term, next term's courses, the whole plan.
class PlanScreen extends StatelessWidget {
  const PlanScreen({super.key});

  static const _state = {
    'passed': ('ناجح', AppColors.success),
    'failed': ('راسب', AppColors.danger),
    'in_progress': ('قيد الدراسة', AppColors.warning),
    'remaining': ('لم يُدرس', Colors.grey),
  };
  static const _next = {
    'open': ('متاح', AppColors.success),
    'pending': ('متاح إذا نجحت في متطلبه', AppColors.warning),
    'closed': ('مغلق: متطلب لم يُنجز', AppColors.danger),
  };

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('خطتي الدراسية')),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => await s.api.get('/api/me/plan') as Map<String, dynamic>,
        builder: (context, p, _) {
          if (p['program'] == null) {
            return ListView(children: const [EmptyView('لم تُربط بتخصص بعد. تواصل مع إدارة الكلية.')]);
          }
          final must = (p['must_pass'] as List?) ?? const [];
          final next = (p['next_courses'] as List?) ?? const [];
          final semesters = ((p['semesters'] as List?) ?? const []).where((x) => (x['courses'] as List).isNotEmpty);
          return ListView(padding: const EdgeInsets.all(12), children: [
            SectionCard(
              title: p['program']['name'] as String,
              child: Text('الفصل الدراسي ${p['level']}${p['semester_set_manually'] == true ? ' (حددته الإدارة)' : ''} · وحدات الخطة ${p['plan_credits']} · '
                  'المنجز ${p['earned_credits']} · المتبقي ${p['remaining_credits']}'),
            ),
            if (must.isNotEmpty)
              SectionCard(
                title: 'لازم تنجح فيها هذا الفصل',
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  for (final m in must)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text('${m['title']} (${m['code']})'),
                      subtitle: Text('تفتح لك: ${(m['unlocks'] as List).join('، ')}'),
                    ),
                ]),
              ),
            SectionCard(
              title: 'مقررات الفصل القادم (${p['next_semester']})',
              child: Column(children: [
                if (next.isEmpty) const Text('لا توجد مقررات متبقية حتى هذا الفصل'),
                for (final c in next)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text('${c['code']} ${c['title']} · ${c['credits']} وحدات'),
                    subtitle: Text('من الفصل ${c['semester']}${c['overdue'] == true ? ' (متأخر عن خطته)' : ''}'),
                    trailing: StatusChip(StatusStyle(_next[c['status']]!.$1, _next[c['status']]!.$2)),
                  ),
              ]),
            ),
            for (final sem in semesters)
              SectionCard(
                title: 'الفصل ${sem['semester']} · ${sem['credits']} وحدة',
                child: Column(children: [
                  for (final c in sem['courses'] as List)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text('${c['code']} ${c['title']}'),
                      subtitle: Text('${c['credits']} وحدات'
                          '${(c['prerequisites'] as List).isEmpty ? '' : ' · يتطلب ${(c['prerequisites'] as List).map((x) => x['code']).join('، ')}'}'),
                      trailing: StatusChip(StatusStyle(
                          c['source'] == 'transfer' ? 'معادلة' : c['source'] == 'prior' ? 'ناجح (سابق)' : _state[c['state']]!.$1,
                          _state[c['state']]!.$2)),
                    ),
                ]),
              ),
          ]);
        },
      ),
    );
  }
}
