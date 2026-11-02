import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../links.dart';
import '../state/session.dart';
import '../widgets/common.dart';

/// Course materials repository: the faculty's courses, then each course's files by term.
class MaterialsScreen extends StatefulWidget {
  const MaterialsScreen({super.key});

  @override
  State<MaterialsScreen> createState() => _MaterialsScreenState();
}

class _MaterialsScreenState extends State<MaterialsScreen> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('مستودع المواد'), actions: [
        if (!s.isStudent)
          IconButton(
            icon: const Icon(Icons.rule),
            tooltip: 'للمراجعة',
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const _ReviewScreen())),
          ),
      ]),
      body: AsyncView<List<dynamic>>(
        load: () async => await s.api.get('/api/materials/courses') as List<dynamic>,
        builder: (context, items, reload) {
          final shown = items.where((c) => _q.isEmpty || '${c['code']} ${c['title']}'.contains(_q)).toList();
          return ListView(padding: const EdgeInsets.all(12), children: [
            TextField(
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'بحث برمز المقرر أو اسمه'),
              onChanged: (v) => setState(() => _q = v.trim()),
            ),
            const SizedBox(height: 8),
            if (shown.isEmpty) const EmptyView('لا توجد مقررات'),
            for (final c in shown)
              Card(
                child: ListTile(
                  leading: Icon(c['mine'] == true ? Icons.star : Icons.folder_outlined,
                      color: c['mine'] == true ? AppColors.warning : null),
                  title: Text('${c['code']} — ${c['title']}'),
                  subtitle: Text([
                    '${c['files']} ملف',
                    if ((c['pending'] ?? 0) > 0) '${c['pending']} للمراجعة',
                  ].join(' · ')),
                  onTap: () async {
                    await Navigator.push(context,
                        MaterialPageRoute(builder: (_) => CourseMaterialsScreen(code: c['code'] as String, title: c['title'] as String)));
                    reload();
                  },
                ),
              ),
          ]);
        },
      ),
    );
  }
}

class CourseMaterialsScreen extends StatefulWidget {
  const CourseMaterialsScreen({super.key, required this.code, required this.title});
  final String code;
  final String title;

  @override
  State<CourseMaterialsScreen> createState() => _CourseMaterialsScreenState();
}

class _CourseMaterialsScreenState extends State<CourseMaterialsScreen> {
  int _version = 0;

  Future<void> _upload() async {
    final done = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => _UploadScreen(code: widget.code)));
    if (done == true) setState(() => _version++);
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _upload,
        icon: const Icon(Icons.upload_file),
        label: Text(s.isStudent ? 'مشاركة ملف' : 'رفع ملف'),
      ),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/materials?code=${Uri.encodeComponent(widget.code)}') as List<dynamic>,
        builder: (context, items, reload) => ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 88), children: [
          if (items.isEmpty) const EmptyView('لا توجد ملفات بعد'),
          for (final m in items) MaterialTile(m: Map<String, dynamic>.from(m as Map), reload: reload),
        ]),
      ),
    );
  }
}

class MaterialTile extends StatelessWidget {
  const MaterialTile({super.key, required this.m, required this.reload, this.showCourse = false});
  final Map<String, dynamic> m;
  final Future<void> Function() reload;
  final bool showCourse;

  Future<void> _decide(BuildContext context, bool approve) async {
    String? reason;
    if (!approve) {
      final ctrl = TextEditingController();
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('سبب عدم النشر'),
          content: TextField(controller: ctrl, autofocus: true),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('رجوع')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('حفظ')),
          ],
        ),
      );
      if (ok != true || ctrl.text.trim().isEmpty) return;
      reason = ctrl.text.trim();
    }
    if (!context.mounted) return;
    try {
      await context.read<Session>().api.post('/api/materials/${m['id']}/review', {'approve': approve, 'reason': ?reason});
      await reload();
    } catch (e) {
      if (context.mounted) showMessage(context, e, error: true);
    }
  }

  Future<void> _delete(BuildContext context) async {
    try {
      await context.read<Session>().api.delete('/api/materials/${m['id']}');
      await reload();
    } catch (e) {
      if (context.mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    final review = m['can_review'] == true;
    return Card(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        ListTile(
          leading: const Icon(Icons.description_outlined),
          title: Text(m['title'] as String),
          subtitle: Text([
            if (showCourse) '${m['course_code']}',
            m['category_label'],
            if (m['term'] != null) m['term'],
            m['by_student'] == true ? 'بإعداد ${m['uploader']}' : m['uploader'],
            '${m['downloads']} تنزيل',
            if (m['status'] == 'pending') 'قيد المراجعة',
            if (m['status'] == 'rejected') 'لم يُنشر: ${m['reject_reason']}',
          ].join(' · ')),
          onTap: () => downloadAndOpen(context, s, '/api/materials/${m['id']}/download',
              (m['file']?['name'] as String?) ?? 'file'),
        ),
        if (review || (m['mine'] == true && m['status'] != 'published'))
          OverflowBar(alignment: MainAxisAlignment.end, children: [
            if (review && m['status'] != 'published')
              TextButton(onPressed: () => _decide(context, true), child: const Text('نشر')),
            if (review && m['status'] != 'rejected')
              TextButton(
                  onPressed: () => _decide(context, false), child: Text(m['status'] == 'published' ? 'سحب' : 'رفض')),
            TextButton(onPressed: () => _delete(context), child: const Text('حذف')),
          ]),
      ]),
    );
  }
}

class _ReviewScreen extends StatelessWidget {
  const _ReviewScreen();

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('ملفات الطلبة للمراجعة')),
      body: AsyncView<List<dynamic>>(
        load: () async => await s.api.get('/api/materials/pending') as List<dynamic>,
        builder: (context, items, reload) => ListView(padding: const EdgeInsets.all(12), children: [
          if (items.isEmpty) const EmptyView('لا توجد ملفات تنتظر المراجعة'),
          for (final m in items) MaterialTile(m: Map<String, dynamic>.from(m as Map), reload: reload, showCourse: true),
        ]),
      ),
    );
  }
}

class _UploadScreen extends StatefulWidget {
  const _UploadScreen({required this.code});
  final String code;

  @override
  State<_UploadScreen> createState() => _UploadScreenState();
}

class _UploadScreenState extends State<_UploadScreen> {
  Map<String, dynamic>? _cats;
  late String _category = context.read<Session>().isStudent ? 'summary' : 'lecture';
  final _title = TextEditingController();
  final _desc = TextEditingController();
  UploadFile? _file;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    context.read<Session>().api.get('/api/materials/categories').then((c) {
      if (mounted) setState(() => _cats = c as Map<String, dynamic>);
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _title.dispose();
    _desc.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final picked = await FilePicker.pickFiles(type: FileType.custom,
        allowedExtensions: ['pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'txt', 'png', 'jpg', 'jpeg', 'zip']);
    if (picked.isEmpty) return;
    final f = picked.first;
    final bytes = await f.xFile.readAsBytes();
    if (!mounted) return;
    if (bytes.length > 20 * 1024 * 1024) return showMessage(context, 'الملف أكبر من 20 ميغابايت', error: true);
    setState(() {
      _file = UploadFile('file', f.name, bytes);
      if (_title.text.isEmpty) _title.text = f.name.replaceAll(RegExp(r'\.[^.]+$'), '');
    });
  }

  Future<void> _send() async {
    if (_file == null || _title.text.trim().length < 3) {
      return showMessage(context, 'اختر الملف واكتب عنواناً', error: true);
    }
    setState(() => _busy = true);
    try {
      final m = await context.read<Session>().api.multipart('/api/materials', fields: {
        'code': widget.code,
        'category': _category,
        'title': _title.text.trim(),
        'description': _desc.text.trim(),
      }, files: [_file!]) as Map<String, dynamic>;
      if (!mounted) return;
      showMessage(context, m['status'] == 'pending' ? 'أُرسل الملف للمراجعة، ويظهر للجميع بعد اعتماده' : 'نُشر الملف');
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final student = context.read<Session>().isStudent;
    return Scaffold(
      appBar: AppBar(title: Text(student ? 'مشاركة ملف' : 'رفع ملف')),
      body: _cats == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(16), children: [
              OutlinedButton.icon(onPressed: _pick, icon: const Icon(Icons.attach_file), label: Text(_file?.filename ?? 'اختيار الملف')),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _category,
                decoration: const InputDecoration(labelText: 'التصنيف'),
                items: [for (final e in _cats!.entries) DropdownMenuItem(value: e.key, child: Text(e.value as String))],
                onChanged: (v) => setState(() => _category = v!),
              ),
              TextField(controller: _title, maxLength: 200, decoration: const InputDecoration(labelText: 'العنوان')),
              TextField(controller: _desc, maxLength: 1000, decoration: const InputDecoration(labelText: 'وصف (اختياري)')),
              if (student)
                const Text('يراجع أستاذ المقرر أو الإدارة الملف قبل ظهوره، ويُنسب إليك عند نشره.',
                    style: TextStyle(fontSize: 12, color: Colors.grey)),
              const SizedBox(height: 12),
              FilledButton(onPressed: _busy ? null : _send, child: Text(student ? 'إرسال للمراجعة' : 'نشر')),
            ]),
    );
  }
}
