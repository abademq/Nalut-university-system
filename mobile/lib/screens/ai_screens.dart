import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _aiNote = 'تحليل آلي بالذكاء الاصطناعي (Claude) للتوجيه فقط، وليس قراراً. تُرسل الأرقام دون اسمك أو رقم قيدك.';

/// Questions about the platform and the institution's rules.
class AssistantScreen extends StatefulWidget {
  const AssistantScreen({super.key});

  @override
  State<AssistantScreen> createState() => _AssistantScreenState();
}

class _AssistantScreenState extends State<AssistantScreen> {
  final _q = TextEditingController();
  final _items = <(String, String)>[];
  bool _busy = false;

  Future<void> _ask(String question) async {
    if (question.trim().length < 3 || _busy) return;
    setState(() => _busy = true);
    try {
      final r = await context.read<Session>().api.post('/api/ai/ask', {'question': question.trim()}) as Map;
      setState(() => _items.add((question.trim(), r['answer'] as String)));
      _q.clear();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('المساعد الذكي')),
        body: Column(children: [
          Expanded(
            child: ListView(padding: const EdgeInsets.all(12), children: [
              const Text('اسأل عن استخدام المنصة ولوائح الحضور والدرجات والتسجيل والطلبات.',
                  style: TextStyle(color: Colors.grey)),
              for (final (q, a) in _items)
                SectionCard(title: q, child: Text(a)),
              Wrap(spacing: 6, children: [
                for (final s in ['كم نسبة الغياب المسموحة؟', 'كيف أطلب عذر غياب؟', 'متى تظهر نتيجتي؟'])
                  ActionChip(label: Text(s), onPressed: () => _ask(s)),
              ]),
            ]),
          ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(8),
              child: Row(children: [
                Expanded(
                  child: TextField(controller: _q, maxLength: 600, decoration: const InputDecoration(hintText: 'سؤالك…')),
                ),
                IconButton.filled(
                    onPressed: _busy ? null : () => _ask(_q.text),
                    icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.send)),
              ]),
            ),
          ),
        ]),
      );
}

/// The study advisor and this term's outlook, after the student agrees.
class AdvisorCard extends StatefulWidget {
  const AdvisorCard({super.key});

  @override
  State<AdvisorCard> createState() => _AdvisorCardState();
}

class _AdvisorCardState extends State<AdvisorCard> {
  Map<String, dynamic>? _status;
  Map<String, dynamic>? _r;
  bool _busy = false;

  static const _outlook = {
    'good': ('جيد', AppColors.success),
    'watch': ('يحتاج متابعة', AppColors.warning),
    'at_risk': ('في خطر', AppColors.danger),
    'unknown': ('بيانات غير كافية', Colors.grey),
  };

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/ai/status').then((s) {
      if (mounted) setState(() => _status = s as Map<String, dynamic>);
    }).catchError((_) {});
  }

  Future<void> _run(Future<dynamic> Function() call) async {
    setState(() => _busy = true);
    try {
      await call();
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<Session>().api;
    final s = _status;
    if (s == null || s['students'] != true) return const SizedBox.shrink();
    if (s['consent'] != true) {
      return SectionCard(
        title: 'المرشد الدراسي الذكي',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('يحلل نتائجك وحضورك ومهامك، ويقترح ما تركز عليه، ويتوقع وضعك في مقررات هذا الفصل، ويضع خطة مذاكرة.'),
          const SizedBox(height: 6),
          const Text('تُرسل أرقامك الدراسية وأسماء المقررات فقط، دون اسمك أو رقم قيدك.', style: TextStyle(color: Colors.grey)),
          const SizedBox(height: 8),
          FilledButton(
            onPressed: _busy ? null : () => _run(() async {
              await api.post('/api/ai/me/consent');
              setState(() => _status = {...s, 'consent': true});
            }),
            child: const Text('أوافق، وأريد التحليل'),
          ),
        ]),
      );
    }
    final r = _r;
    return SectionCard(
      title: 'المرشد الدراسي الذكي',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        FilledButton.tonal(
          onPressed: _busy ? null : () => _run(() async {
            final x = await api.post('/api/ai/me/analysis${r != null ? '?fresh=true' : ''}') as Map<String, dynamic>;
            setState(() => _r = x);
          }),
          child: Text(_busy ? 'جارٍ التحليل…' : r == null ? 'حلّل مستواي' : 'تحديث التحليل'),
        ),
        if (r != null) ...[
          const SizedBox(height: 8),
          Text(r['summary'] as String),
          for (final f in (r['focus'] as List))
            Padding(padding: const EdgeInsets.only(top: 6), child: Text('• ${f['course']}: ${f['why']} — ${f['action']}')),
          const SizedBox(height: 8),
          const Text('توقع هذا الفصل (تقدير):', style: TextStyle(fontWeight: FontWeight.bold)),
          for (final o in (r['outlook'] as List))
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('${o['course_code']}'),
              subtitle: Text('${o['reason']}'),
              trailing: StatusChip(StatusStyle(
                  (_outlook[o['outlook']] ?? ('—', Colors.grey)).$1, (_outlook[o['outlook']] ?? ('—', Colors.grey)).$2)),
            ),
          const Text('خطة مذاكرة أسبوعية:', style: TextStyle(fontWeight: FontWeight.bold)),
          for (final d in (r['weekly_plan'] as List)) Text('• ${d['day']}: ${d['plan']}'),
          if ((r['tip'] as String?)?.isNotEmpty == true)
            Padding(padding: const EdgeInsets.only(top: 6), child: Text('${r['tip']}')),
        ],
        const SizedBox(height: 6),
        const Text(_aiNote, style: TextStyle(fontSize: 11, color: Colors.grey)),
        TextButton(
          onPressed: _busy ? null : () => _run(() async {
            await api.delete('/api/ai/me/consent');
            setState(() {
              _status = {...s, 'consent': false};
              _r = null;
            });
          }),
          child: const Text('سحب الموافقة'),
        ),
      ]),
    );
  }
}
