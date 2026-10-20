import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const resultStatus = {
  'draft': StatusStyle('مسودة', Colors.grey),
  'submitted': StatusStyle('بانتظار الاعتماد', AppColors.warning),
  'approved': StatusStyle('معتمدة', AppColors.info),
  'published': StatusStyle('منشورة', AppColors.success),
};

/// Faculty / university administration: approve, publish or return course results.
class ResultsScreen extends StatefulWidget {
  const ResultsScreen({super.key});

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

class _ResultsScreenState extends State<ResultsScreen> {
  int _version = 0;

  Future<void> _act(int courseId, String action, {bool needNote = false}) async {
    final s = context.read<Session>();
    var note = '';
    if (needNote) {
      final ctrl = TextEditingController();
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('السبب'),
          content: TextField(controller: ctrl, decoration: const InputDecoration(labelText: 'اذكر سبب الإرجاع')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('تأكيد')),
          ],
        ),
      );
      if (ok != true || ctrl.text.trim().length < 3) return;
      note = ctrl.text.trim();
    }
    try {
      await s.api.post('/api/courses/$courseId/results/$action', {'note': note});
      if (mounted) {
        showMessage(context, 'تم');
        setState(() => _version++);
      }
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('اعتماد ونشر النتائج')),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/results/pending') as List<dynamic>,
        builder: (context, rows, _) => ListView(padding: const EdgeInsets.all(12), children: [
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text('لا تظهر النتائج للطلبة إلا بعد: رفع الأستاذ ← اعتماد الإدارة ← النشر.',
                style: TextStyle(color: Colors.grey)),
          ),
          for (final r in rows)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(
                      child: Text('${r['course']['code']} — ${r['course']['title']}',
                          style: const TextStyle(fontWeight: FontWeight.bold)),
                    ),
                    StatusChip.of(resultStatus, r['status'] as String?),
                  ]),
                  if (r['note'] != null) Text('ملاحظة: ${r['note']}', style: const TextStyle(fontSize: 12)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 8, children: [
                    if (r['status'] == 'submitted')
                      FilledButton(onPressed: () => _act(r['course']['id'] as int, 'approve'), child: const Text('اعتماد')),
                    if (r['status'] == 'approved')
                      FilledButton(onPressed: () => _act(r['course']['id'] as int, 'publish'), child: const Text('نشر للطلبة')),
                    if (r['status'] != 'draft')
                      OutlinedButton(
                        onPressed: () => _act(r['course']['id'] as int, 'return', needNote: true),
                        child: Text(r['status'] == 'published' ? 'إعادة فتح' : 'إرجاع للأستاذ'),
                      ),
                  ]),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}
