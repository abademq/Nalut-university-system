import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../links.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _statusColors = {
  'submitted': AppColors.info,
  'in_review': AppColors.warning,
  'needs_documents': AppColors.danger,
  'forwarded': AppColors.info,
  'approved': AppColors.success,
  'rejected': AppColors.danger,
};

bool _handles(String role) => role == 'staff' || role == 'faculty_admin' || role == 'university_admin';

/// Service requests (enrolment certificate, transcript, absence excuse, appeal…): file one,
/// follow it, add documents; staff offices and administrations also process the requests they receive.
class RequestsScreen extends StatelessWidget {
  const RequestsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final handler = _handles(context.read<Session>().role);
    final mine = _RequestList(scope: 'mine', key: const ValueKey('mine'));
    return DefaultTabController(
      length: handler ? 2 : 1,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('الطلبات والمعاملات'),
          bottom: handler ? const TabBar(tabs: [Tab(text: 'الوارد'), Tab(text: 'طلباتي')]) : null,
        ),
        floatingActionButton: FloatingActionButton.extended(
          icon: const Icon(Icons.add),
          label: const Text('طلب جديد'),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const NewRequestScreen())),
        ),
        body: handler ? TabBarView(children: [const _RequestList(scope: 'inbox', key: ValueKey('inbox')), mine]) : mine,
      ),
    );
  }
}

class _RequestList extends StatelessWidget {
  const _RequestList({super.key, required this.scope});
  final String scope;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return AsyncView<List<dynamic>>(
      load: () async => await s.api.get('/api/requests?scope=$scope') as List<dynamic>,
      builder: (context, items, reload) => ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 88), children: [
        if (items.isEmpty) EmptyView(scope == 'mine' ? 'لم تقدّم أي طلب بعد' : 'لا توجد طلبات واردة'),
        for (final r in items)
          Card(
            child: ListTile(
              title: Text(r['subject'] as String),
              subtitle: Text([
                r['type_label'],
                if (scope != 'mine') r['requester']['full_name'],
                fmtRelative(r['updated_at']),
              ].join(' · ')),
              trailing: StatusChip(StatusStyle(r['status_label'] as String, _statusColors[r['status']] ?? Colors.grey)),
              onTap: () async {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => RequestDetailScreen(id: r['id'] as int)));
                reload();
              },
            ),
          ),
      ]),
    );
  }
}

Future<List<UploadFile>> _pickOne(BuildContext context) async {
  final picked = await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png', 'docx']);
  if (picked.isEmpty) return [];
  final f = picked.first;
  final bytes = await f.xFile.readAsBytes();
  if (bytes.length > 20 * 1024 * 1024) {
    if (context.mounted) showMessage(context, 'الملف أكبر من 20 ميغابايت', error: true);
    return [];
  }
  return [UploadFile('upload', f.name, bytes)];
}

class NewRequestScreen extends StatefulWidget {
  const NewRequestScreen({super.key});

  @override
  State<NewRequestScreen> createState() => _NewRequestScreenState();
}

class _NewRequestScreenState extends State<NewRequestScreen> {
  String? _type;
  final _subject = TextEditingController();
  final _details = TextEditingController();
  List<UploadFile> _file = [];
  bool _busy = false;

  @override
  void dispose() {
    _subject.dispose();
    _details.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_type == null || _subject.text.trim().length < 2) {
      showMessage(context, 'اختر نوع الطلب واكتب موضوعه', error: true);
      return;
    }
    setState(() => _busy = true);
    final s = context.read<Session>();
    try {
      await s.api.multipart('/api/requests',
          fields: {'type': _type!, 'subject': _subject.text.trim(), 'details': _details.text.trim()}, files: _file);
      if (!mounted) return;
      showMessage(context, 'قُدّم الطلب، وسيصلك إشعار بكل تحديث');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('طلب جديد')),
      body: AsyncView<Map<String, dynamic>>(
        load: () async => await s.api.get('/api/requests/types') as Map<String, dynamic>,
        builder: (context, d, _) {
          final types = (d['types'] as Map).cast<String, dynamic>();
          return ListView(padding: const EdgeInsets.all(16), children: [
            DropdownButtonFormField<String>(
              initialValue: _type,
              decoration: const InputDecoration(labelText: 'نوع الطلب'),
              items: [
                for (final e in types.entries) DropdownMenuItem(value: e.key, child: Text(e.value['label'] as String)),
              ],
              onChanged: (v) => setState(() => _type = v),
            ),
            const SizedBox(height: 12),
            TextField(controller: _subject, decoration: const InputDecoration(labelText: 'الموضوع')),
            const SizedBox(height: 12),
            TextField(
              controller: _details,
              maxLines: 5,
              decoration: const InputDecoration(labelText: 'التفاصيل (اختياري)', alignLabelWithHint: true),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              icon: const Icon(Icons.attach_file),
              label: Text(_file.isEmpty ? 'إرفاق مستند (اختياري)' : _file.first.filename),
              onPressed: () async {
                final f = await _pickOne(context);
                if (f.isNotEmpty) setState(() => _file = f);
              },
            ),
            const SizedBox(height: 16),
            FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'جارٍ الإرسال…' : 'تقديم الطلب')),
          ]);
        },
      ),
    );
  }
}

class RequestDetailScreen extends StatefulWidget {
  const RequestDetailScreen({super.key, required this.id});
  final int id;

  @override
  State<RequestDetailScreen> createState() => _RequestDetailScreenState();
}

class _RequestDetailScreenState extends State<RequestDetailScreen> {
  int _version = 0;

  static const _actions = [
    ('in_review', 'قيد المراجعة', false),
    ('needs_documents', 'طلب مستندات', true),
    ('forwarded', 'إحالة لمكتب آخر', false),
    ('approved', 'اعتماد', false),
    ('rejected', 'رفض', true),
    ('comment', 'ملاحظة', true),
  ];

  Future<void> _act(String action, String label, bool needsText, Map<String, dynamic> types) async {
    final s = context.read<Session>();
    final comment = TextEditingController();
    String? office;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) => AlertDialog(
          title: Text(label),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            if (action == 'forwarded')
              DropdownButtonFormField<String>(
                initialValue: office,
                decoration: const InputDecoration(labelText: 'الجهة'),
                items: [
                  for (final e in (types['offices'] as Map).entries)
                    DropdownMenuItem(value: e.key as String, child: Text(e.value as String)),
                ],
                onChanged: (v) => setD(() => office = v),
              ),
            TextField(
              controller: comment,
              maxLines: 3,
              decoration: InputDecoration(labelText: needsText ? 'السبب / المطلوب' : 'ملاحظة (اختياري)'),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('تأكيد')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await s.api.post('/api/requests/${widget.id}/actions',
          {'action': action, 'comment': comment.text.trim(), 'office': ?office});
      if (mounted) setState(() => _version++);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  Future<void> _addDocument() async {
    final s = context.read<Session>();
    final f = await _pickOne(context);
    if (f.isEmpty) return;
    try {
      await s.api.multipart('/api/requests/${widget.id}/documents', files: f);
      if (mounted) setState(() => _version++);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('تفاصيل الطلب')),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => [
          await s.api.get('/api/requests/${widget.id}'),
          await s.api.get('/api/requests/types'),
        ],
        builder: (context, both, reload) {
          final r = both[0] as Map<String, dynamic>;
          final types = both[1] as Map<String, dynamic>;
          final mine = r['requester']['id'] == s.user?['id'];
          final open = r['status'] != 'approved' && r['status'] != 'rejected';
          return ListView(padding: const EdgeInsets.all(12), children: [
            SectionCard(
              title: r['subject'] as String,
              trailing: StatusChip(StatusStyle(r['status_label'] as String, _statusColors[r['status']] ?? Colors.grey)),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${r['type_label']} · ${r['office_label']}'),
                Text('مقدم الطلب: ${r['requester']['full_name']}${r['requester']['code'] != null ? ' (${r['requester']['code']})' : ''}',
                    style: const TextStyle(color: Colors.grey)),
                if ((r['details'] as String?)?.isNotEmpty == true) ...[
                  const SizedBox(height: 8),
                  Text(r['details'] as String),
                ],
              ]),
            ),
            if (mine && open)
              OutlinedButton.icon(
                icon: const Icon(Icons.upload_file),
                label: Text(r['status'] == 'needs_documents' ? 'إرفاق المستندات المطلوبة' : 'إرفاق مستند'),
                onPressed: _addDocument,
              ),
            if (!mine && _handles(s.role))
              SectionCard(
                title: 'إجراءات',
                child: Wrap(spacing: 8, runSpacing: 8, children: [
                  for (final a in _actions)
                    if (open || a.$1 == 'comment')
                      OutlinedButton(onPressed: () => _act(a.$1, a.$2, a.$3, types), child: Text(a.$2)),
                ]),
              ),
            SectionCard(
              title: 'سجل الطلب',
              child: Column(children: [
                for (final e in (r['events'] as List).reversed)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.history, size: 20),
                    title: Text('${types['statuses'][e['status']] ?? e['status']}${e['actor'] != null ? ' — ${e['actor']}' : ''}'),
                    subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      if (e['comment'] != null) Text(e['comment'] as String),
                      Text(fmtDate(e['created_at']), style: const TextStyle(fontSize: 12)),
                    ]),
                    trailing: e['file'] == null
                        ? null
                        : IconButton(
                            icon: const Icon(Icons.attach_file),
                            tooltip: e['file']['name'] as String,
                            onPressed: () => downloadAndOpen(
                                context, s, '/api/files/${e['file']['id']}', e['file']['name'] as String),
                          ),
                  ),
              ]),
            ),
          ]);
        },
      ),
    );
  }
}
