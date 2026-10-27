import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'results_screen.dart' show resultStatus;

String _pct(Object? v) => v == null ? '—' : '${(v as num) % 1 == 0 ? v.toInt() : v}%';

/// A big number with a caption, coloured green / orange / red by how good it is.
class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value, {this.color = AppColors.primaryText, this.icon});
  final String label;
  final String value;
  final Color color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Card(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
            child: Column(children: [
              if (icon != null) Icon(icon, color: readable(context, color), size: 20),
              Text(value, style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: readable(context, color))),
              Text(label, textAlign: TextAlign.center, style: const TextStyle(fontSize: 12, color: Colors.grey)),
            ]),
          ),
        ),
      );
}

Color _good(num? v, {bool higherIsBetter = true, num ok = 80, num warn = 60}) {
  if (v == null) return Colors.grey;
  final x = higherIsBetter ? v : 100 - v;
  return x >= ok ? AppColors.success : (x >= warn ? AppColors.warning : AppColors.danger);
}

class _Bar extends StatelessWidget {
  const _Bar(this.label, this.value);
  final String label;
  final num? value;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          SizedBox(width: 92, child: Text(label, style: const TextStyle(fontSize: 13))),
          Expanded(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(6),
              child: LinearProgressIndicator(
                value: value == null ? 0 : (value! / 100).clamp(0, 1).toDouble(),
                minHeight: 8,
                color: _good(value),
                backgroundColor: Colors.grey.withValues(alpha: 0.15),
              ),
            ),
          ),
          SizedBox(width: 48, child: Text(_pct(value), textAlign: TextAlign.end, style: const TextStyle(fontSize: 13))),
        ]),
      );
}

/// One person's simplified report: a student, a teacher or a staff member (yourself by default).
class PersonReportScreen extends StatelessWidget {
  const PersonReportScreen({super.key, required this.userId, this.title});
  final int userId;
  final String? title;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: Text(title ?? 'تقريري')),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => await s.api.get('/api/reports/person/$userId') as Map<String, dynamic>,
        builder: (context, r, reload) {
          final sum = r['summary'] as Map<String, dynamic>;
          final who = r['user'] as Map<String, dynamic>;
          return ListView(padding: const EdgeInsets.all(12), children: [
            Card(
              child: ListTile(
                leading: const CircleAvatar(child: Icon(Icons.person)),
                title: Text('${who['full_name']}'),
                subtitle: Text([roleLabels[who['role']] ?? '', if (who['code'] != null) '${who['code']}'].join(' · ')),
              ),
            ),
            ...switch (r['kind']) {
              'student' => _student(sum, r['courses'] as List),
              'teacher' => _teacher(sum, r['courses'] as List),
              _ => _staff(sum),
            },
          ]);
        },
      ),
    );
  }

  List<Widget> _student(Map<String, dynamic> sum, List courses) => [
        Row(children: [
          _Stat('متوسط الغياب', _pct(sum['absence_percent']),
              color: _good(sum['absence_percent'] as num?, higherIsBetter: false, ok: 90, warn: 80), icon: Icons.event_busy),
          _Stat('تسليم المهام', _pct(sum['submission_rate']), color: _good(sum['submission_rate'] as num?), icon: Icons.task_alt),
          _Stat('متوسط الدرجات', _pct(sum['avg_score_percent']),
              color: _good(sum['avg_score_percent'] as num?, ok: 75, warn: 50), icon: Icons.grade_outlined),
        ]),
        if ((sum['alerts'] as num? ?? 0) > 0)
          Card(
            color: AppColors.warning.withValues(alpha: 0.1),
            child: ListTile(
              leading: const Icon(Icons.info_outline, color: AppColors.warning),
              title: Text('${sum['alerts']} ملاحظات تحتاج متابعة'),
              subtitle: const Text('تنبيه للمتابعة فقط، وليس قراراً أو عقوبة'),
            ),
          ),
        if (courses.isEmpty) const EmptyView('لا توجد مقررات'),
        for (final c in courses)
          SectionCard(
            title: '${c['course']['code']} — ${c['course']['title']}',
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              _Bar('الحضور', c['sessions'] == 0 ? null : 100 - (c['absence_percent'] as num)),
              _Bar('تسليم المهام', c['due'] == 0 ? null : 100 * (c['submitted'] as num) / (c['due'] as num)),
              _Bar('درجات المهام', c['avg_score_percent'] as num?),
              const SizedBox(height: 4),
              Text(
                c['grade'] != null
                    ? 'النتيجة النهائية: ${c['grade']['letter'] ?? '—'} ${c['grade']['label'] ?? ''} (${_pct(c['grade']['percent'])})'
                    : (c['running_percent'] != null
                        ? 'المجموع الحالي قبل الاعتماد: ${_pct(c['running_percent'])}'
                        : 'النتيجة النهائية لم تُنشر بعد'),
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              for (final a in c['alerts'] as List)
                Text('• $a', style: const TextStyle(color: AppColors.warning)),
            ]),
          ),
      ];

  List<Widget> _teacher(Map<String, dynamic> sum, List courses) => [
        Row(children: [
          _Stat('المقررات', '${sum['courses']}', icon: Icons.menu_book_outlined),
          _Stat('الطلبة', '${sum['students']}', icon: Icons.groups_outlined),
          _Stat('جلسات (30 يوماً)', '${sum['sessions_30d']}', icon: Icons.qr_code_2),
        ]),
        Row(children: [
          _Stat('متوسط الحضور', _pct(sum['attendance_rate']), color: _good(sum['attendance_rate'] as num?)),
          _Stat('متوسط التسليم', _pct(sum['submission_rate']), color: _good(sum['submission_rate'] as num?)),
          _Stat('بانتظار المراجعة', '${sum['pending_reviews']}',
              color: (sum['pending_reviews'] as num? ?? 0) > 0 ? AppColors.warning : AppColors.success),
        ]),
        for (final c in courses)
          SectionCard(
            title: '${c['course']['code']} — ${c['course']['title']}',
            trailing: StatusChip.of(resultStatus, c['result_status'] as String?),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${c['enrolled']} طالب · ${c['sessions']} جلسة حضور', style: const TextStyle(color: Colors.grey)),
              _Bar('الحضور', c['attendance_rate'] as num?),
              _Bar('التسليم', c['submission_rate'] as num?),
              _Bar('متوسط الدرجات', c['avg_score_percent'] as num?),
            ]),
          ),
      ];

  List<Widget> _staff(Map<String, dynamic> sum) => [
        Row(children: [
          _Stat('أيام الحضور (30 يوماً)', '${sum['days_present_30d']}', icon: Icons.badge_outlined),
          _Stat('مرات التأخير', '${sum['late_30d']}',
              color: (sum['late_30d'] as num? ?? 0) > 3 ? AppColors.warning : AppColors.success, icon: Icons.schedule),
        ]),
        Row(children: [
          _Stat('طلبات عالجها (30 يوماً)', '${sum['requests_handled_30d']}', icon: Icons.task_alt),
          _Stat('طلبات مفتوحة في مكتبه', '${sum['open_requests']}',
              color: (sum['open_requests'] as num? ?? 0) > 10 ? AppColors.warning : AppColors.primaryText,
              icon: Icons.inbox_outlined),
        ]),
      ];
}

/// For administrations and teachers: the overall picture, students needing follow-up, and a
/// search to open anyone's simplified report.
class ReportsScreen extends StatefulWidget {
  const ReportsScreen({super.key});

  @override
  State<ReportsScreen> createState() => _ReportsScreenState();
}

class _ReportsScreenState extends State<ReportsScreen> {
  final _q = TextEditingController();
  List<dynamic> _found = [];

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    final q = _q.text.trim();
    if (q.length < 2) return setState(() => _found = []);
    try {
      final r = await context.read<Session>().api.get('/api/users?limit=20&q=${Uri.encodeQueryComponent(q)}');
      final items = (r is Map ? r['items'] : r) as List<dynamic>;
      if (mounted) setState(() => _found = items);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  void _open(Map p) => Navigator.push(context,
      MaterialPageRoute(builder: (_) => PersonReportScreen(userId: p['id'] as int, title: p['full_name'] as String)));

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('التقارير والإحصاءات')),
      body: AsyncView<List<dynamic>>(
        load: () => Future.wait([s.api.get('/api/reports/overview'), s.api.get('/api/reports/at-risk')]),
        builder: (context, data, reload) {
          final o = data[0] as Map<String, dynamic>;
          final risk = data[1] as List<dynamic>;
          final t = o['totals'] as Map<String, dynamic>;
          final people = o['people'] as Map<String, dynamic>;
          return ListView(padding: const EdgeInsets.all(12), children: [
            TextField(
              controller: _q,
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => _search(),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: 'ابحث عن طالب أو أستاذ أو موظف لعرض تقريره',
                suffixIcon: IconButton(icon: const Icon(Icons.arrow_back), onPressed: _search),
              ),
            ),
            for (final p in _found)
              ListTile(
                leading: const Icon(Icons.person_outline),
                title: Text('${p['full_name']}'),
                subtitle: Text([roleLabels[p['role']] ?? '', if (p['code'] != null) '${p['code']}'].join(' · ')),
                trailing: const Icon(Icons.chevron_left),
                onTap: () => _open(p as Map),
              ),
            const SizedBox(height: 8),
            if (s.isAdmin)
              Row(children: [
                _Stat('الطلبة', '${people['students']}', icon: Icons.school_outlined),
                _Stat('هيئة التدريس', '${people['teaching']}', icon: Icons.co_present_outlined),
                _Stat('الموظفون', '${people['staff']}', icon: Icons.badge_outlined),
              ]),
            Row(children: [
              _Stat('الحضور (30 يوماً)', _pct(t['attendance_rate']), color: _good(t['attendance_rate'] as num?)),
              _Stat('تسليم المهام', _pct(t['submission_rate']), color: _good(t['submission_rate'] as num?)),
              _Stat('متوسط الدرجات', _pct(t['avg_score_percent']), color: _good(t['avg_score_percent'] as num?, ok: 75, warn: 50)),
            ]),
            Row(children: [
              _Stat('مراجعات حضور', '${o['pending_attendance_reviews']}', color: AppColors.warning),
              _Stat('نتائج بانتظار الاعتماد', '${o['results_awaiting_approval']}', color: AppColors.info),
              if (o['open_requests'] != null) _Stat('طلبات مفتوحة', '${o['open_requests']}', color: goldText(context)),
            ]),
            if ((o['breakdown'] as List).isNotEmpty)
              SectionCard(
                title: s.role == 'university_admin' ? 'مقارنة الكليات' : 'مقارنة الأقسام',
                child: Column(children: [
                  for (final b in o['breakdown'] as List)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Text('${b['name']} · ${b['students']} طالب', style: const TextStyle(fontWeight: FontWeight.w600)),
                        _Bar('الحضور', b['attendance_rate'] as num?),
                        _Bar('التسليم', b['submission_rate'] as num?),
                      ]),
                    ),
                ]),
              ),
            SectionCard(
              title: 'طلبة يحتاجون متابعة (${risk.length})',
              child: risk.isEmpty
                  ? const Text('لا يوجد حالياً')
                  : Column(children: [
                      for (final x in risk.take(30))
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          title: Text('${x['student']['full_name']}'),
                          subtitle: Text('${x['course']['code']}: ${(x['reasons'] as List).join('، ')}'),
                          trailing: const Icon(Icons.chevron_left),
                          onTap: () => _open(x['student'] as Map),
                        ),
                    ]),
            ),
          ]);
        },
      ),
    );
  }
}
