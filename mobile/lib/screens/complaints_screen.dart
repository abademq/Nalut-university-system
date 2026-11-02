import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../links.dart';
import '../state/session.dart';
import '../widgets/common.dart';

const _colors = {
  'new': AppColors.info,
  'in_review': AppColors.warning,
  'resolved': AppColors.success,
  'rejected': Colors.grey,
};
const _statusLabels = {'in_review': 'قيد المعالجة', 'resolved': 'تمت المعالجة', 'rejected': 'مرفوضة'};

/// The complaints and suggestions box: send one (optionally anonymous) and follow it; the faculty or
/// university administration (complaints.manage) answers the ones it receives.
class ComplaintsScreen extends StatelessWidget {
  const ComplaintsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final handler = context.read<Session>().can('complaints.manage');
    const mine = _ComplaintList(box: 'mine', key: ValueKey('mine'));
    return DefaultTabController(
      length: handler ? 2 : 1,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('الشكاوى والمقترحات'),
          bottom: handler ? const TabBar(tabs: [Tab(text: 'الوارد'), Tab(text: 'شكاواي')]) : null,
        ),
        floatingActionButton: Builder(
          builder: (context) => FloatingActionButton.extended(
            icon: const Icon(Icons.add),
            label: const Text('شكوى أو اقتراح'),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const NewComplaintScreen())),
          ),
        ),
        body: handler ? const TabBarView(children: [_ComplaintList(box: 'inbox', key: ValueKey('inbox')), mine]) : mine,
      ),
    );
  }
}

class _ComplaintList extends StatelessWidget {
  const _ComplaintList({super.key, required this.box});
  final String box;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return AsyncView<List<dynamic>>(
      load: () async => await s.api.get('/api/complaints?box=$box') as List<dynamic>,
      builder: (context, items, reload) => ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 88), children: [
        if (items.isEmpty) EmptyView(box == 'mine' ? 'لم ترسل أي شكوى بعد' : 'لا توجد شكاوى واردة'),
        for (final c in items)
          Card(
            child: ListTile(
              title: Text(c['subject'] as String),
              subtitle: Text([
                c['ref'],
                (c['category_label'] as String).split(' (').first,
                if (box == 'inbox') c['author'] == null ? 'مجهول' : c['author']['full_name'],
                if (box == 'mine') 'إلى ${c['to']}',
                fmtRelative(c['updated_at'], past: true),
              ].join(' · ')),
              trailing: StatusChip(StatusStyle(c['status_label'] as String, _colors[c['status']] ?? Colors.grey)),
              onTap: () async {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => ComplaintDetailScreen(id: c['id'] as int)));
                reload();
              },
            ),
          ),
      ]),
    );
  }
}

class NewComplaintScreen extends StatefulWidget {
  const NewComplaintScreen({super.key});

  @override
  State<NewComplaintScreen> createState() => _NewComplaintScreenState();
}

class _NewComplaintScreenState extends State<NewComplaintScreen> {
  Map<String, dynamic>? _meta;
  String _category = 'services';
  final _subject = TextEditingController();
  final _body = TextEditingController();
  bool _anonymous = false;
  bool _toUniversity = false;
  UploadFile? _file;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/complaints/categories').then((m) {
      if (mounted) setState(() => _meta = m as Map<String, dynamic>);
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _subject.dispose();
    _body.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final picked = await FilePicker.pickFiles(
        type: FileType.custom, allowedExtensions: ['pdf', 'jpg', 'jpeg', 'png', 'docx', 'mp3', 'm4a']);
    if (picked.isEmpty) return;
    final f = picked.first;
    final bytes = await f.xFile.readAsBytes();
    if (!mounted) return;
    if (bytes.length > 20 * 1024 * 1024) return showMessage(context, 'الملف أكبر من 20 ميغابايت', error: true);
    setState(() => _file = UploadFile('upload', f.name, bytes));
  }

  Future<void> _send() async {
    if (_subject.text.trim().length < 3 || _body.text.trim().length < 10) {
      return showMessage(context, 'اكتب موضوعاً وتفاصيل كافية (10 أحرف على الأقل)', error: true);
    }
    setState(() => _busy = true);
    try {
      final c = await context.read<Session>().api.multipart('/api/complaints', fields: {
        'category': _category,
        'subject': _subject.text.trim(),
        'body': _body.text.trim(),
        'anonymous': '$_anonymous',
        'to_university': '$_toUniversity',
      }, files: [?_file]) as Map<String, dynamic>;
      if (!mounted) return;
      showMessage(context, 'أُرسلت الشكوى، رقمها ${c['ref']}');
      Navigator.pop(context);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cats = (_meta?['categories'] as Map<String, dynamic>?) ?? {};
    final sensitive = ((_meta?['university_only'] as List<dynamic>?) ?? []).contains(_category);
    return Scaffold(
      appBar: AppBar(title: const Text('شكوى أو اقتراح جديد')),
      body: _meta == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(16), children: [
              DropdownButtonFormField<String>(
                initialValue: _category,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'النوع'),
                items: [for (final e in cats.entries) DropdownMenuItem(value: e.key, child: Text(e.value as String))],
                onChanged: (v) => setState(() => _category = v!),
              ),
              const SizedBox(height: 12),
              TextField(controller: _subject, maxLength: 200, decoration: const InputDecoration(labelText: 'الموضوع')),
              TextField(
                controller: _body,
                minLines: 4,
                maxLines: 10,
                maxLength: 5000,
                decoration: const InputDecoration(labelText: 'التفاصيل', hintText: 'ماذا حدث، أين ومتى، وما الذي تقترحه'),
              ),
              OutlinedButton.icon(
                onPressed: _pick,
                icon: const Icon(Icons.attach_file),
                label: Text(_file?.filename ?? 'مرفق (اختياري)'),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _anonymous,
                onChanged: (v) => setState(() => _anonymous = v),
                title: const Text('إخفاء اسمي عن الإدارة (شكوى مجهولة)'),
                subtitle: _anonymous
                    ? const Text('لن يظهر اسمك لمن يعالجها ولا في سجل التدقيق، وتتابع الردود من حسابك.')
                    : null,
              ),
              if (sensitive)
                const Text('هذا النوع يصل مباشرة إلى إدارة الجامعة.', style: TextStyle(color: Colors.grey))
              else
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  value: _toUniversity,
                  onChanged: (v) => setState(() => _toUniversity = v),
                  title: const Text('إرسالها إلى إدارة الجامعة بدل إدارة الكلية'),
                ),
              const SizedBox(height: 12),
              FilledButton(onPressed: _busy ? null : _send, child: Text(_busy ? 'جارٍ الإرسال…' : 'إرسال')),
            ]),
    );
  }
}

class ComplaintDetailScreen extends StatefulWidget {
  const ComplaintDetailScreen({super.key, required this.id});
  final int id;

  @override
  State<ComplaintDetailScreen> createState() => _ComplaintDetailScreenState();
}

class _ComplaintDetailScreenState extends State<ComplaintDetailScreen> {
  final _reply = TextEditingController();
  String? _status;
  bool _busy = false;
  int _version = 0;

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    if (_reply.text.trim().length < 2) return;
    setState(() => _busy = true);
    try {
      await context.read<Session>().api.post('/api/complaints/${widget.id}/replies', {
        'body': _reply.text.trim(),
        'status': ?_status,
      });
      _reply.clear();
      setState(() {
        _status = null;
        _version++;
      });
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
      appBar: AppBar(title: const Text('الشكوى')),
      body: AsyncView<Map<String, dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/complaints/${widget.id}') as Map<String, dynamic>,
        builder: (context, c, reload) {
          final handler = c['can_handle'] == true && c['mine'] != true;
          final closed = c['status'] == 'resolved' || c['status'] == 'rejected';
          return ListView(padding: const EdgeInsets.all(16), children: [
            Text(c['subject'] as String, style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text('${c['ref']} · ${c['category_label']} · إلى ${c['to']}', style: const TextStyle(color: Colors.grey)),
            const SizedBox(height: 8),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: StatusChip(StatusStyle(c['status_label'] as String, _colors[c['status']] ?? Colors.grey)),
            ),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(c['author'] == null ? 'مرسل مجهول' : c['author']['full_name'] as String,
                      style: const TextStyle(color: Colors.grey, fontSize: 12)),
                  const SizedBox(height: 6),
                  Text(c['body'] as String),
                  if (c['file'] != null)
                    TextButton.icon(
                      onPressed: () => downloadAndOpen(context, s, '/api/files/${c['file']['id']}', c['file']['name'] as String),
                      icon: const Icon(Icons.attach_file),
                      label: Text(c['file']['name'] as String),
                    ),
                ]),
              ),
            ),
            for (final r in (c['replies'] as List<dynamic>))
              Card(
                color: r['from_handler'] == true ? null : Theme.of(context).colorScheme.surfaceContainerHighest,
                child: ListTile(
                  title: Text(r['body'] as String),
                  subtitle: Text([
                    r['author'],
                    fmtDate(r['created_at']),
                    if (r['status'] != null) _statusLabels[r['status']] ?? '',
                  ].join(' · ')),
                ),
              ),
            if (handler || !closed) ...[
              const SizedBox(height: 8),
              TextField(
                controller: _reply,
                minLines: 2,
                maxLines: 6,
                decoration: InputDecoration(labelText: handler ? 'الرد' : 'إضافة توضيح'),
              ),
              if (handler)
                DropdownButtonFormField<String?>(
                  initialValue: _status,
                  decoration: const InputDecoration(labelText: 'الحالة'),
                  items: [
                    DropdownMenuItem(value: null, child: Text(c['status'] == 'new' ? 'قيد المعالجة' : 'دون تغيير')),
                    for (final e in _statusLabels.entries) DropdownMenuItem(value: e.key, child: Text(e.value)),
                  ],
                  onChanged: (v) => setState(() => _status = v),
                ),
              const SizedBox(height: 8),
              FilledButton(onPressed: _busy ? null : _send, child: const Text('إرسال')),
            ],
          ]);
        },
      ),
    );
  }
}
