import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'results_screen.dart' show resultStatus;

/// Grade entry for the courses the user teaches: one card per student, a field per
/// assessment component, then "submit for approval" to the faculty administration.
class GradeEntryScreen extends StatelessWidget {
  const GradeEntryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('رصد الدرجات')),
      body: AsyncView<List<dynamic>>(
        load: () async => await s.api.get('/api/courses') as List<dynamic>,
        builder: (context, courses, _) => ListView(padding: const EdgeInsets.all(12), children: [
          if (courses.isEmpty) const EmptyView('لا توجد مقررات مسندة إليك'),
          for (final c in courses)
            Card(
              child: ListTile(
                leading: const Icon(Icons.menu_book_outlined, color: AppColors.primaryText),
                title: Text('${c['code']} — ${c['title']}'),
                trailing: const Icon(Icons.chevron_left),
                onTap: () => Navigator.push(
                    context, MaterialPageRoute(builder: (_) => CourseGradesScreen(courseId: c['id'] as int))),
              ),
            ),
        ]),
      ),
    );
  }
}

class CourseGradesScreen extends StatefulWidget {
  const CourseGradesScreen({super.key, required this.courseId});
  final int courseId;

  @override
  State<CourseGradesScreen> createState() => _CourseGradesScreenState();
}

class _CourseGradesScreenState extends State<CourseGradesScreen> {
  int _version = 0;
  final Map<String, TextEditingController> _fields = {}; // "<student>:<component>"
  final _search = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    for (final c in _fields.values) {
      c.dispose();
    }
    _search.dispose();
    super.dispose();
  }

  TextEditingController _field(int student, int component, Object? score) => _fields.putIfAbsent(
      '$student:$component', () => TextEditingController(text: score == null ? '' : _fmt(score)));

  static String _fmt(Object? v) {
    final n = (v as num?)?.toDouble();
    if (n == null) return '';
    return n == n.roundToDouble() ? n.toInt().toString() : n.toString();
  }

  /// Entries whose field differs from the saved score.
  List<Map<String, dynamic>> _changes(Map<String, dynamic> d) {
    final out = <Map<String, dynamic>>[];
    for (final st in d['students'] as List) {
      for (final c in d['components'] as List) {
        final ctrl = _fields['${st['id']}:${c['id']}'];
        if (ctrl == null) continue;
        final text = ctrl.text.trim().replaceAll('٫', '.');
        final saved = st['scores']['${c['id']}'];
        final value = text.isEmpty ? null : double.tryParse(text);
        if (text.isNotEmpty && value == null) throw 'قيمة غير صحيحة عند ${st['full_name']}';
        if (value != (saved as num?)?.toDouble()) {
          out.add({'student_id': st['id'], 'component_id': c['id'], 'score': value, 'had': saved != null});
        }
      }
    }
    return out;
  }

  Future<void> _save(Map<String, dynamic> d) async {
    final s = context.read<Session>();
    List<Map<String, dynamic>> changes;
    try {
      changes = _changes(d);
    } catch (e) {
      showMessage(context, e, error: true);
      return;
    }
    if (changes.isEmpty) {
      showMessage(context, 'لا توجد تغييرات');
      return;
    }
    var reason = '';
    if (changes.any((c) => c['had'] == true)) {
      final ctrl = TextEditingController();
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('سبب تعديل درجات مسجلة'),
          content: TextField(controller: ctrl, decoration: const InputDecoration(hintText: 'مثال: تصحيح خطأ إدخال')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('حفظ')),
          ],
        ),
      );
      if (ok != true) return;
      reason = ctrl.text.trim();
    }
    setState(() => _busy = true);
    try {
      final r = await s.api.put('/api/courses/${widget.courseId}/grades', {
        'reason': reason,
        'entries': [for (final c in changes) {'student_id': c['student_id'], 'component_id': c['component_id'], 'score': c['score']}],
      }) as Map<String, dynamic>;
      if (!mounted) return;
      showMessage(context, 'حُفظت ${r['changed']} درجة');
      _reset();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _reset() => setState(() {
        for (final c in _fields.values) {
          c.dispose();
        }
        _fields.clear();
        _version++;
      });

  Future<void> _submit() async {
    final s = context.read<Session>();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('رفع النتائج للاعتماد؟'),
        content: const Text('بعد الرفع لا يمكن تعديل الدرجات إلا إذا أعادتها إدارة الكلية إلى المسودة.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('رفع')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await s.api.post('/api/courses/${widget.courseId}/results/submit', {'note': ''});
      if (mounted) showMessage(context, 'رُفعت النتائج إلى إدارة الكلية');
      _reset();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return AsyncView<Map<String, dynamic>>(
      key: ValueKey(_version),
      load: () async => await s.api.get('/api/courses/${widget.courseId}/grades') as Map<String, dynamic>,
      builder: (context, d, reload) {
        final status = d['result']['status'] as String;
        final editable = status == 'draft';
        final comps = d['components'] as List;
        final q = _search.text.trim();
        final students = (d['students'] as List)
            .where((st) => q.isEmpty || '${st['full_name']} ${st['code'] ?? ''}'.contains(q))
            .toList();
        return Scaffold(
          appBar: AppBar(title: Text('${d['course']['code']} — الدرجات'), actions: [
            IconButton(
              tooltip: 'سجل التعديلات',
              icon: const Icon(Icons.history),
              onPressed: () => Navigator.push(
                  context, MaterialPageRoute(builder: (_) => GradeHistoryScreen(courseId: widget.courseId))),
            ),
          ]),
          bottomNavigationBar: editable
              ? SafeArea(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(children: [
                      Expanded(
                        child: FilledButton.icon(
                          icon: const Icon(Icons.save_outlined),
                          label: const Text('حفظ'),
                          onPressed: _busy ? null : () => _save(d),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: OutlinedButton.icon(
                          icon: const Icon(Icons.send_outlined),
                          label: const Text('رفع للاعتماد'),
                          onPressed: _busy ? null : _submit,
                        ),
                      ),
                    ]),
                  ),
                )
              : null,
          body: ListView(padding: const EdgeInsets.all(12), children: [
            Card(
              child: ListTile(
                title: Text('حالة النتائج: ${resultStatus[status]?.label ?? status}'),
                subtitle: Text(editable
                    ? 'اكتب الدرجات ثم «حفظ». ترك الحقل فارغاً يعني لم تُرصد بعد.'
                    : 'النتائج ${resultStatus[status]?.label ?? status}؛ التعديل يحتاج إرجاعها إلى المسودة من إدارة الكلية.'),
              ),
            ),
            if (d['result']['note'] != null && status == 'draft')
              Card(
                color: AppColors.warning.withValues(alpha: 0.1),
                child: ListTile(title: Text('ملاحظة الإرجاع: ${d['result']['note']}')),
              ),
            if (comps.isEmpty) const EmptyView('لا توجد عناصر تقييم. أضفها من «عناصر التقييم» في لوحة الويب أو من صفحة المقرر.'),
            if (comps.isNotEmpty)
              TextField(
                controller: _search,
                decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'بحث بالاسم أو رقم القيد'),
                onChanged: (_) => setState(() {}),
              ),
            const SizedBox(height: 8),
            if (comps.isNotEmpty)
              for (final st in students)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Row(children: [
                        Expanded(child: Text('${st['full_name']}', style: const TextStyle(fontWeight: FontWeight.bold))),
                        Text('${_fmt(st['total'])} / ${_fmt(st['max_total'])}${st['letter'] != null ? ' · ${st['letter']}' : ''}'),
                      ]),
                      if (st['code'] != null) Text('${st['code']}', style: const TextStyle(color: Colors.grey, fontSize: 12)),
                      const SizedBox(height: 8),
                      Wrap(spacing: 8, runSpacing: 8, children: [
                        for (final c in comps)
                          SizedBox(
                            width: 104,
                            child: TextField(
                              controller: _field(st['id'] as int, c['id'] as int, st['scores']['${c['id']}']),
                              enabled: editable,
                              keyboardType: const TextInputType.numberWithOptions(decimal: true),
                              textAlign: TextAlign.center,
                              decoration: InputDecoration(
                                labelText: '${c['name']}',
                                helperText: 'من ${_fmt(c['max_score'])}',
                                isDense: true,
                              ),
                            ),
                          ),
                      ]),
                    ]),
                  ),
                ),
          ]),
        );
      },
    );
  }
}


/// Every change to the course's grades: who, when, from what to what, and why.
class GradeHistoryScreen extends StatelessWidget {
  const GradeHistoryScreen({super.key, required this.courseId});
  final int courseId;

  static String _v(Object? v) => v == null ? '—' : _CourseGradesScreenState._fmt(v);

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('سجل تعديلات الدرجات')),
      body: AsyncView<List<dynamic>>(
        load: () async => await s.api.get('/api/courses/$courseId/grades/history') as List<dynamic>,
        builder: (context, rows, reload) => ListView.separated(
          padding: const EdgeInsets.all(12),
          itemCount: rows.isEmpty ? 1 : rows.length,
          separatorBuilder: (_, _) => const Divider(height: 1),
          itemBuilder: (context, i) {
            if (rows.isEmpty) return const EmptyView('لا توجد تعديلات بعد', icon: Icons.history);
            final r = rows[i] as Map<String, dynamic>;
            return ListTile(
              contentPadding: EdgeInsets.zero,
              title: Text('${r['student']} — ${r['component']}'),
              subtitle: Text('${r['reason']}\n${r['actor']} · ${fmtDate(r['created_at'])}'
                  '${r['source'] == 'import' ? ' · استيراد' : ''}'),
              isThreeLine: true,
              trailing: Text('${_v(r['old'])} ← ${_v(r['new'])}',
                  textDirection: TextDirection.rtl, style: const TextStyle(fontWeight: FontWeight.bold)),
            );
          },
        ),
      ),
    );
  }
}
