import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'publications_screen.dart' show PublicationImage, openPublication;
import 'selfie_screen.dart';

const _audiences = {'all': 'الجميع', 'students': 'الطلاب', 'staff': 'الموظفون والأساتذة'};
const _levels = {'info': 'عادي', 'important': 'مهم', 'urgent': 'عاجل'};
const _levelColors = {'info': AppColors.primaryText, 'important': AppColors.warning, 'urgent': AppColors.danger};

/// Picks an optional end date (the item disappears at the end of that day).
Future<DateTime?> _pickEnd(BuildContext context, DateTime? current) async {
  final now = DateTime.now();
  final d = await showDatePicker(
    context: context,
    initialDate: current ?? now.add(const Duration(days: 7)),
    firstDate: now,
    lastDate: now.add(const Duration(days: 730)),
  );
  return d == null ? null : DateTime(d.year, d.month, d.day, 23, 59);
}

String _until(Object? endsAt) => endsAt == null ? 'دون تاريخ انتهاء' : 'حتى ${fmtDate(endsAt, time: false)}';

// --------------------------------------------------------------------------- pinned banners

/// Pinned announcements at the top of the app and dashboard: add, pause, delete.
class ManageBannersScreen extends StatefulWidget {
  const ManageBannersScreen({super.key});

  @override
  State<ManageBannersScreen> createState() => _ManageBannersScreenState();
}

class _ManageBannersScreenState extends State<ManageBannersScreen> {
  int _version = 0;

  Future<void> _run(Future<void> Function() action, String done) async {
    try {
      await action();
      if (!mounted) return;
      showMessage(context, done);
      setState(() => _version++);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('الإعلانات المثبتة')),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add),
        label: const Text('إعلان جديد'),
        onPressed: () async {
          final ok = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => const BannerFormScreen()));
          if (ok == true) setState(() => _version++);
        },
      ),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/banners/manage') as List<dynamic>,
        builder: (context, rows, reload) => ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 88), children: [
          if (rows.isEmpty) const EmptyView('لا توجد إعلانات مثبتة', icon: Icons.push_pin_outlined),
          for (final b in rows)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    StatusChip(StatusStyle(_levels[b['level']] ?? '${b['level']}', _levelColors[b['level']] ?? Colors.grey)),
                    const SizedBox(width: 8),
                    Expanded(child: Text('${b['title']}', style: const TextStyle(fontWeight: FontWeight.bold))),
                    Switch(
                      value: b['is_active'] == true,
                      onChanged: (v) => _run(() => s.api.patch('/api/banners/${b['id']}', {'is_active': v}),
                          v ? 'أُعيد عرض الإعلان' : 'أُوقف الإعلان'),
                    ),
                  ]),
                  if ((b['body'] as String?)?.isNotEmpty == true) Text('${b['body']}'),
                  const SizedBox(height: 4),
                  Text(
                    [_audiences[b['audience']], b['faculty_name'] ?? 'كل الجامعة', _until(b['ends_at'])].join(' · '),
                    style: const TextStyle(fontSize: 12, color: Colors.grey),
                  ),
                  Align(
                    alignment: AlignmentDirectional.centerEnd,
                    child: TextButton.icon(
                      icon: const Icon(Icons.delete_outline, size: 18),
                      label: const Text('حذف'),
                      style: TextButton.styleFrom(foregroundColor: AppColors.danger),
                      onPressed: () async {
                        if (await _confirm(context, 'حذف الإعلان «${b['title']}»؟')) {
                          await _run(() => s.api.delete('/api/banners/${b['id']}'), 'حُذف الإعلان');
                        }
                      },
                    ),
                  ),
                ]),
              ),
            ),
        ]),
      ),
    );
  }
}

Future<bool> _confirm(BuildContext context, String title) async =>
    await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(title),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('تأكيد')),
        ],
      ),
    ) ==
    true;

class BannerFormScreen extends StatefulWidget {
  const BannerFormScreen({super.key});

  @override
  State<BannerFormScreen> createState() => _BannerFormScreenState();
}

class _BannerFormScreenState extends State<BannerFormScreen> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  String _level = 'info';
  String _audience = 'all';
  int? _facultyId;
  DateTime? _ends;
  bool _busy = false;

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final s = context.read<Session>();
    setState(() => _busy = true);
    try {
      await s.api.post('/api/banners', {
        'title': _title.text.trim(),
        'body': _body.text.trim(),
        'level': _level,
        'audience': _audience,
        'faculty_id': _facultyId,
        'ends_at': _ends?.toUtc().toIso8601String(),
      });
      if (!mounted) return;
      showMessage(context, 'نُشر الإعلان');
      Navigator.pop(context, true);
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
      appBar: AppBar(title: const Text('إعلان مثبت جديد')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        TextField(controller: _title, decoration: const InputDecoration(labelText: 'العنوان')),
        const SizedBox(height: 8),
        TextField(controller: _body, maxLines: 4, decoration: const InputDecoration(labelText: 'النص (اختياري)')),
        const SizedBox(height: 16),
        const Text('الأهمية'),
        SegmentedButton<String>(
          segments: [for (final e in _levels.entries) ButtonSegment(value: e.key, label: Text(e.value))],
          selected: {_level},
          onSelectionChanged: (v) => setState(() => _level = v.first),
        ),
        const SizedBox(height: 12),
        _AudienceField(value: _audience, onChanged: (v) => setState(() => _audience = v)),
        if (s.role == 'university_admin') ...[
          const SizedBox(height: 8),
          _ScopePicker(onChanged: (f, _) => _facultyId = f, departments: false),
        ],
        const SizedBox(height: 8),
        _EndField(value: _ends, onChanged: (v) => setState(() => _ends = v)),
        const SizedBox(height: 24),
        FilledButton.icon(
          icon: const Icon(Icons.push_pin),
          label: const Text('نشر الإعلان الآن'),
          onPressed: _busy ? null : _save,
        ),
      ]),
    );
  }
}

class _AudienceField extends StatelessWidget {
  const _AudienceField({required this.value, required this.onChanged});
  final String value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) => DropdownButtonFormField<String>(
        initialValue: value,
        decoration: const InputDecoration(labelText: 'يظهر لـ'),
        items: [for (final e in _audiences.entries) DropdownMenuItem(value: e.key, child: Text(e.value))],
        onChanged: (v) => onChanged(v ?? 'all'),
      );
}

class _EndField extends StatelessWidget {
  const _EndField({required this.value, required this.onChanged});
  final DateTime? value;
  final ValueChanged<DateTime?> onChanged;

  @override
  Widget build(BuildContext context) => ListTile(
        contentPadding: EdgeInsets.zero,
        leading: const Icon(Icons.event_busy_outlined),
        title: Text(value == null ? 'يبقى حتى يُوقف يدوياً' : 'يختفي بعد ${fmtDate(value!.toIso8601String(), time: false)}'),
        trailing: value == null
            ? TextButton(onPressed: () async => onChanged(await _pickEnd(context, null)), child: const Text('تحديد تاريخ'))
            : IconButton(icon: const Icon(Icons.close), onPressed: () => onChanged(null)),
      );
}

/// Faculty (and optionally department) targeting from the organisation structure.
/// University administrators pick any faculty; others are already limited to their own.
class _ScopePicker extends StatefulWidget {
  const _ScopePicker({required this.onChanged, this.departments = true});
  final void Function(int? faculty, int? department) onChanged;
  final bool departments;

  @override
  State<_ScopePicker> createState() => _ScopePickerState();
}

class _ScopePickerState extends State<_ScopePicker> {
  List<dynamic> _faculties = const [];
  int? _faculty;
  int? _department;
  late final bool _pickFaculty;

  @override
  void initState() {
    super.initState();
    final s = context.read<Session>();
    _pickFaculty = s.role == 'university_admin';
    _faculty = _pickFaculty ? null : (s.user?['faculty'] as Map?)?['id'] as int?;
    s.api.get('/api/org/structure').then((d) {
      if (mounted) setState(() => _faculties = (d as Map)['faculties'] as List);
    }).catchError((_) {});
  }

  List<dynamic> get _departments =>
      (_faculties.where((f) => f['id'] == _faculty).firstOrNull?['departments'] as List?) ?? const [];

  @override
  Widget build(BuildContext context) => Column(children: [
        if (_pickFaculty)
          DropdownButtonFormField<int?>(
            initialValue: _faculty,
            decoration: const InputDecoration(labelText: 'الكلية'),
            items: [
              const DropdownMenuItem<int?>(value: null, child: Text('كل الجامعة')),
              for (final f in _faculties) DropdownMenuItem<int?>(value: f['id'] as int, child: Text('${f['name']}')),
            ],
            onChanged: (v) {
              setState(() {
                _faculty = v;
                _department = null;
              });
              widget.onChanged(_faculty, _department);
            },
          ),
        if (widget.departments && _faculty != null) ...[
          const SizedBox(height: 8),
          DropdownButtonFormField<int?>(
            key: ValueKey(_faculty),
            initialValue: _department,
            decoration: const InputDecoration(labelText: 'القسم'),
            items: [
              const DropdownMenuItem<int?>(value: null, child: Text('كل الأقسام')),
              for (final d in _departments) DropdownMenuItem<int?>(value: d['id'] as int, child: Text('${d['name']}')),
            ],
            onChanged: (v) {
              setState(() => _department = v);
              widget.onChanged(_faculty, _department);
            },
          ),
        ],
      ]);
}

// --------------------------------------------------------------------------- timetables and posters

/// Published lecture timetables and image announcements: publish, pause, delete.
class ManagePublicationsScreen extends StatefulWidget {
  const ManagePublicationsScreen({super.key});

  @override
  State<ManagePublicationsScreen> createState() => _ManagePublicationsScreenState();
}

class _ManagePublicationsScreenState extends State<ManagePublicationsScreen> {
  int _version = 0;

  Future<void> _run(Future<void> Function() action, String done) async {
    try {
      await action();
      if (!mounted) return;
      showMessage(context, done);
      setState(() => _version++);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Scaffold(
      appBar: AppBar(title: const Text('نشر الجداول والإعلانات')),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.add_photo_alternate_outlined),
        label: const Text('نشر جديد'),
        onPressed: () async {
          final ok = await Navigator.push<bool>(context, MaterialPageRoute(builder: (_) => const PublicationFormScreen()));
          if (ok == true) setState(() => _version++);
        },
      ),
      body: AsyncView<List<dynamic>>(
        key: ValueKey(_version),
        load: () async => await s.api.get('/api/publications/manage') as List<dynamic>,
        builder: (context, rows, reload) => ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 88), children: [
          if (rows.isEmpty) const EmptyView('لم يُنشر شيء بعد', icon: Icons.photo_library_outlined),
          for (final p in rows)
            Card(
              clipBehavior: Clip.antiAlias,
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                InkWell(
                  onTap: () => openPublication(context, Map<String, dynamic>.from(p as Map)),
                  child: SizedBox(
                    height: 140,
                    child: p['is_image'] == true
                        ? PublicationImage(fileId: p['file']['id'] as int)
                        : Container(
                            color: AppColors.primary.withValues(alpha: 0.06),
                            child: const Center(child: Icon(Icons.picture_as_pdf_outlined, size: 48, color: AppColors.primaryText)),
                          ),
                  ),
                ),
                ListTile(
                  title: Text('${p['title']}'),
                  subtitle: Text([
                    p['kind_label'],
                    _audiences[p['audience']],
                    p['department_name'] ?? p['faculty_name'] ?? 'كل الجامعة',
                    if (p['cohort'] != null) 'دفعة ${p['cohort']}',
                    _until(p['ends_at']),
                  ].whereType<String>().join(' · ')),
                  trailing: Switch(
                    value: p['is_active'] == true,
                    onChanged: (v) => _run(() => s.api.patch('/api/publications/${p['id']}', {'is_active': v}),
                        v ? 'أُعيد العرض' : 'أُوقف العرض'),
                  ),
                ),
                Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: TextButton.icon(
                    icon: const Icon(Icons.delete_outline, size: 18),
                    label: const Text('حذف'),
                    style: TextButton.styleFrom(foregroundColor: AppColors.danger),
                    onPressed: () async {
                      if (await _confirm(context, 'حذف «${p['title']}»؟')) {
                        await _run(() => s.api.delete('/api/publications/${p['id']}'), 'حُذف');
                      }
                    },
                  ),
                ),
              ]),
            ),
        ]),
      ),
    );
  }
}

class PublicationFormScreen extends StatefulWidget {
  const PublicationFormScreen({super.key});

  @override
  State<PublicationFormScreen> createState() => _PublicationFormScreenState();
}

class _PublicationFormScreenState extends State<PublicationFormScreen> {
  static const _maxBytes = 10 * 1024 * 1024;
  final _title = TextEditingController();
  final _body = TextEditingController();
  final _cohort = TextEditingController();
  String _kind = 'schedule';
  String _audience = 'all';
  int? _facultyId;
  int? _departmentId;
  DateTime? _ends;
  bool _notify = true;
  bool _busy = false;
  UploadFile? _file;

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    _cohort.dispose();
    super.dispose();
  }

  void _setFile(String name, Uint8List bytes) {
    if (bytes.length > _maxBytes) {
      showMessage(context, 'الملف أكبر من 10 ميغابايت', error: true);
      return;
    }
    setState(() => _file = UploadFile('upload', name, bytes));
  }

  Future<void> _camera() async {
    final bytes = await Navigator.push<Uint8List>(
        context, MaterialPageRoute(builder: (_) => const SelfieScreen(document: true)));
    if (bytes != null && mounted) _setFile('photo-${DateTime.now().millisecondsSinceEpoch}.jpg', bytes);
  }

  Future<void> _pick({required bool pdf}) async {
    final picked = pdf
        ? await FilePicker.pickFiles(type: FileType.custom, allowedExtensions: ['pdf'])
        : await FilePicker.pickFiles(type: FileType.image);
    if (picked.isEmpty) return;
    final f = picked.first;
    final bytes = await f.xFile.readAsBytes();
    if (mounted) _setFile(f.name, bytes);
  }

  Future<void> _save() async {
    final s = context.read<Session>();
    if (_file == null) {
      showMessage(context, 'اختر صورة أو ملف PDF أولاً', error: true);
      return;
    }
    setState(() => _busy = true);
    try {
      final r = await s.api.multipart('/api/publications', fields: {
        'kind': _kind,
        'title': _title.text.trim(),
        'body': _body.text.trim(),
        'audience': _audience,
        if (_facultyId != null) 'faculty_id': '$_facultyId',
        if (_departmentId != null) 'department_id': '$_departmentId',
        if (_cohort.text.trim().isNotEmpty) 'cohort': _cohort.text.trim(),
        if (_ends != null) 'ends_at': _ends!.toUtc().toIso8601String(),
        'notify': '$_notify',
      }, files: [_file!]) as Map<String, dynamic>;
      if (!mounted) return;
      showMessage(context, r['notified'] == false ? 'نُشر، لكن تعذر إرسال الإشعار لهذا النطاق' : 'نُشر بنجاح');
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted) showMessage(context, e, error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final f = _file;
    final isImage = f != null && !f.filename.toLowerCase().endsWith('.pdf');
    return Scaffold(
      appBar: AppBar(title: const Text('نشر جدول أو إعلان مصور')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'schedule', icon: Icon(Icons.calendar_month_outlined), label: Text('جدول محاضرات')),
            ButtonSegment(value: 'poster', icon: Icon(Icons.image_outlined), label: Text('إعلان مصور')),
          ],
          selected: {_kind},
          onSelectionChanged: (v) => setState(() => _kind = v.first),
        ),
        const SizedBox(height: 12),
        Card(
          clipBehavior: Clip.antiAlias,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (f != null)
              SizedBox(
                height: 200,
                child: isImage
                    ? Image.memory(f.bytes, fit: BoxFit.contain)
                    : Center(
                        child: Column(mainAxisSize: MainAxisSize.min, children: [
                          const Icon(Icons.picture_as_pdf_outlined, size: 56, color: AppColors.primaryText),
                          Text(f.filename),
                        ]),
                      ),
              ),
            Padding(
              padding: const EdgeInsets.all(8),
              child: Wrap(alignment: WrapAlignment.center, spacing: 8, runSpacing: 8, children: [
                OutlinedButton.icon(onPressed: _camera, icon: const Icon(Icons.photo_camera_outlined), label: const Text('تصوير')),
                OutlinedButton.icon(
                    onPressed: () => _pick(pdf: false), icon: const Icon(Icons.photo_outlined), label: const Text('من المعرض')),
                OutlinedButton.icon(
                    onPressed: () => _pick(pdf: true), icon: const Icon(Icons.picture_as_pdf_outlined), label: const Text('ملف PDF')),
              ]),
            ),
          ]),
        ),
        const SizedBox(height: 8),
        TextField(controller: _title, decoration: const InputDecoration(labelText: 'العنوان (مثل: جدول الفصل الخريفي)')),
        const SizedBox(height: 8),
        TextField(controller: _body, maxLines: 3, decoration: const InputDecoration(labelText: 'وصف (اختياري)')),
        const SizedBox(height: 8),
        _AudienceField(value: _audience, onChanged: (v) => setState(() => _audience = v)),
        const SizedBox(height: 8),
        _ScopePicker(onChanged: (fac, dep) {
          _facultyId = fac;
          _departmentId = dep;
        }),
        const SizedBox(height: 8),
        TextField(controller: _cohort, decoration: const InputDecoration(labelText: 'الدفعة (اختياري، مثل 2023)')),
        const SizedBox(height: 8),
        _EndField(value: _ends, onChanged: (v) => setState(() => _ends = v)),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: _notify,
          onChanged: (v) => setState(() => _notify = v),
          title: const Text('إرسال إشعار للمعنيين'),
        ),
        const SizedBox(height: 16),
        FilledButton.icon(
          icon: const Icon(Icons.publish),
          label: Text(_busy ? 'جارٍ الرفع…' : 'نشر'),
          onPressed: _busy ? null : _save,
        ),
      ]),
    );
  }
}
