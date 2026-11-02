import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// Opens a document's printable page in the phone's browser, through a ten-minute signed link
/// (from there it can be printed or saved as PDF).
Future<void> openDocument(BuildContext context, Session s, int id) async {
  try {
    final r = await s.api.post('/api/documents/$id/link') as Map<String, dynamic>;
    final base = s.api.baseUrl.replaceAll(RegExp(r'/+$'), '');
    await launchUrl(Uri.parse('$base${r['url']}'), mode: LaunchMode.externalApplication);
  } catch (e) {
    if (context.mounted) showMessage(context, e, error: true);
  }
}

/// Official documents with a QR to check them. [studentId] null: my own documents (a student);
/// otherwise a student's, for those who issue documents (documents.issue).
class DocumentsScreen extends StatefulWidget {
  const DocumentsScreen({super.key, this.studentId, this.studentName});
  final int? studentId;
  final String? studentName;

  @override
  State<DocumentsScreen> createState() => _DocumentsScreenState();
}

class _DocumentsScreenState extends State<DocumentsScreen> {
  int _version = 0;

  Future<void> _issue(String kind) async {
    final s = context.read<Session>();
    final to = TextEditingController(text: 'إلى من يهمه الأمر');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(kind == 'transcript' ? 'كشف درجات' : 'إفادة قيد'),
        content: TextField(controller: to, decoration: const InputDecoration(labelText: 'موجهة إلى')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('إصدار')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final d = await s.api.post('/api/documents', {
        'student_id': ?widget.studentId,
        'kind': kind,
        'addressee': to.text.trim().length < 3 ? 'إلى من يهمه الأمر' : to.text.trim(),
      }) as Map<String, dynamic>;
      setState(() => _version++);
      if (mounted) await openDocument(context, s, d['id'] as int);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  Future<void> _revoke(int id) async {
    final reason = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('إلغاء الوثيقة'),
        content: TextField(controller: reason, decoration: const InputDecoration(labelText: 'السبب (يظهر لمن يتحقق منها)')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('رجوع')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('إلغاء الوثيقة')),
        ],
      ),
    );
    if (ok != true || reason.text.trim().length < 3 || !mounted) return;
    try {
      await context.read<Session>().api.post('/api/documents/$id/revoke', {'reason': reason.text.trim()});
      setState(() => _version++);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    final manage = widget.studentId != null && s.can('documents.issue');
    return Scaffold(
      appBar: AppBar(title: Text(widget.studentName == null ? 'وثائقي الرسمية' : 'وثائق ${widget.studentName}')),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get(
            widget.studentId == null ? '/api/documents' : '/api/documents?student_id=${widget.studentId}') as List<dynamic>,
        builder: (context, items, reload) => ListView(padding: const EdgeInsets.all(12), children: [
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton.tonalIcon(
                onPressed: () => _issue('enrollment'), icon: const Icon(Icons.badge_outlined), label: const Text('إفادة قيد')),
            if (manage)
              FilledButton.tonalIcon(
                  onPressed: () => _issue('transcript'), icon: const Icon(Icons.grading), label: const Text('كشف درجات')),
          ]),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text('كل وثيقة تحمل رمز QR يفتح صفحة تحقق عامة تبيّن صحتها. تُفتح في المتصفح للطباعة أو الحفظ PDF.',
                style: TextStyle(fontSize: 12, color: Colors.grey)),
          ),
          if (items.isEmpty) const EmptyView('لا توجد وثائق صادرة'),
          for (final d in items)
            Card(
              child: ListTile(
                title: Text('${d['kind_label']} — ${d['addressee']}'),
                subtitle: Text([
                  fmtDate(d['issued_at']),
                  d['self_issued'] == true ? 'بطلب الطالب' : d['issuer'],
                  d['code'],
                ].join(' · ')),
                trailing: d['revoked_at'] != null
                    ? const StatusChip(StatusStyle('ملغاة', AppColors.danger))
                    : manage
                        ? IconButton(
                            icon: const Icon(Icons.block), tooltip: 'إلغاء', onPressed: () => _revoke(d['id'] as int))
                        : const StatusChip(StatusStyle('سارية', AppColors.success)),
                onTap: () => openDocument(context, s, d['id'] as int),
              ),
            ),
        ]),
      ),
    );
  }
}
