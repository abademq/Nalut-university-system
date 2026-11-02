import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'ai_screens.dart';

class GradesScreen extends StatelessWidget {
  const GradesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('درجاتي ونتائجي')),
      body: AsyncView<(List<dynamic>, Map<String, dynamic>, Map<String, dynamic>)>(
        load: () async {
          final r = await Future.wait(
              [s.api.get('/api/me/grades'), s.api.get('/api/me/academic'), s.api.get('/api/me/transcript')]);
          return (r[0] as List<dynamic>, r[1] as Map<String, dynamic>, r[2] as Map<String, dynamic>);
        },
        builder: (context, data, _) {
          final (list, a, t) = data;
          if (list.isEmpty) return ListView(children: const [EmptyView('لا توجد مقررات')]);
          return ListView(padding: const EdgeInsets.all(12), children: [
            const AdvisorCard(),
            _TranscriptCard(t),
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


/// The cumulative average, the latest term's average and the study advice.
class _TranscriptCard extends StatelessWidget {
  const _TranscriptCard(this.t);
  final Map<String, dynamic> t;

  @override
  Widget build(BuildContext context) {
    final terms = (t['terms'] as List?) ?? const [];
    final last = terms.isEmpty ? null : terms.last as Map;
    final advice = (t['advice'] as List?) ?? const [];
    String pct(Object? v) => v == null ? '—' : '$v%';
    Color color(String? level) => switch (level) {
          'danger' => AppColors.danger,
          'success' => AppColors.success,
          _ => AppColors.warning,
        };
    return SectionCard(
      title: 'نتيجتي والمعدل',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Expanded(child: _Figure('المعدل التراكمي', pct(t['cumulative_average']), t['cumulative_label'] as String?)),
          Expanded(child: _Figure('آخر معدل فصلي', pct(last?['average']), last?['term'] as String?)),
          Expanded(child: _Figure('الوحدات المنجزة', '${t['earned_credits'] ?? 0}', null)),
        ]),
        if (terms.isEmpty)
          const Padding(padding: EdgeInsets.only(top: 8), child: Text('يظهر المعدل بعد نشر أول نتيجة.',
              style: TextStyle(color: Colors.grey))),
        for (final a in advice)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('• ${a['text']}', style: TextStyle(color: color(a['level'] as String?))),
          ),
      ]),
    );
  }
}

class _Figure extends StatelessWidget {
  const _Figure(this.label, this.value, this.hint);
  final String label;
  final String value;
  final String? hint;

  @override
  Widget build(BuildContext context) => Column(children: [
        Text(value, style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.bold)),
        Text(label, textAlign: TextAlign.center, style: const TextStyle(fontSize: 12)),
        if (hint != null) Text(hint!, style: const TextStyle(fontSize: 11, color: Colors.grey)),
      ]);
}
