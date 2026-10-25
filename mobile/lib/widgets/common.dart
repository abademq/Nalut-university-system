import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../config.dart';

// ------------------------------------------------------------------ labels

const roleLabels = {
  'platform_admin': 'مشرف المنصة',
  'university_admin': 'إدارة الجامعة',
  'faculty_admin': 'إدارة الكلية',
  'staff': 'موظف إداري',
  'teacher': 'عضو هيئة تدريس',
  'assistant': 'معيد',
  'student': 'طالب',
};

const kindLabels = {'homework': 'واجب', 'research': 'بحث', 'project': 'مشروع', 'quiz': 'اختبار', 'activity': 'نشاط'};

const categoryLabels = {
  'announcement': 'إعلان',
  'academic_note': 'ملاحظة أكاديمية',
  'official_warning': 'تحذير رسمي',
  'admin_notice': 'إشعار إداري',
  'system': 'تنبيه النظام',
};

const dayNames = ['السبت', 'الأحد', 'الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة'];

class StatusStyle {
  const StatusStyle(this.label, this.color);
  final String label;
  final Color color;
}

const assignmentStatus = {
  'not_started': StatusStyle('لم يبدأ', Colors.grey),
  'in_progress': StatusStyle('قيد العمل', AppColors.info),
  'submitted': StatusStyle('تم التسليم', AppColors.primaryText),
  'late': StatusStyle('متأخر', AppColors.danger),
  'reviewed': StatusStyle('تمت المراجعة', AppColors.success),
};

const attendanceStatus = {
  'present': StatusStyle('حاضر', AppColors.success),
  'late': StatusStyle('متأخر', AppColors.warning),
  'absent': StatusStyle('غائب', AppColors.danger),
  'excused': StatusStyle('بعذر', AppColors.info),
  'pending_review': StatusStyle('قيد المراجعة', AppColors.warning),
  'rejected': StatusStyle('مرفوض', AppColors.danger),
};

// ------------------------------------------------------------------ formatting

const _months = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];

DateTime? parseDate(Object? v) => v is String ? DateTime.tryParse(v)?.toLocal() : null;

String fmtDate(Object? v, {bool time = true}) {
  final d = parseDate(v);
  if (d == null) return '—';
  final date = '${d.day} ${_months[d.month - 1]} ${d.year}';
  if (!time) return date;
  return '$date، ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

String fmtRelative(Object? v) {
  final d = parseDate(v);
  if (d == null) return '';
  final diff = d.difference(DateTime.now());
  final future = !diff.isNegative;
  final a = diff.abs();
  String amount;
  if (a.inMinutes < 1) {
    return 'الآن';
  } else if (a.inHours < 1) {
    amount = '${a.inMinutes} دقيقة';
  } else if (a.inDays < 1) {
    amount = '${a.inHours} ساعة';
  } else {
    amount = '${a.inDays} يوم';
  }
  return future ? 'خلال $amount' : 'قبل $amount';
}

String pct(Object? v) => v == null ? '—' : '$v%';

// ------------------------------------------------------------------ widgets

class StatusChip extends StatelessWidget {
  const StatusChip(this.style, {super.key});
  StatusChip.of(Map<String, StatusStyle> map, String? value, {super.key})
      : style = map[value] ?? StatusStyle(value ?? '—', Colors.grey);

  final StatusStyle style;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
        decoration: BoxDecoration(
          color: style.color.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Text(style.label,
            style: TextStyle(color: style.color, fontSize: 12, fontWeight: FontWeight.w600)),
      );
}

class EmptyView extends StatelessWidget {
  const EmptyView(this.message, {super.key, this.icon = Icons.inbox_outlined});
  final String message;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 48, color: Colors.grey),
          const SizedBox(height: 8),
          Text(message, textAlign: TextAlign.center, style: const TextStyle(color: Colors.grey)),
        ]),
      );
}

class SectionCard extends StatelessWidget {
  const SectionCard({super.key, this.title, this.trailing, required this.child});
  final String? title;
  final Widget? trailing;
  final Widget child;

  @override
  Widget build(BuildContext context) => Card(
        margin: const EdgeInsets.only(bottom: 12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            if (title != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(children: [
                  Expanded(child: Text(title!, style: Theme.of(context).textTheme.titleMedium)),
                  ?trailing,
                ]),
              ),
            child,
          ]),
        ),
      );
}

/// Loads data with [load], shows loading / error / content, supports pull-to-refresh.
class AsyncView<T> extends StatefulWidget {
  const AsyncView({super.key, required this.load, required this.builder});
  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;

  @override
  State<AsyncView<T>> createState() => _AsyncViewState<T>();
}

class _AsyncViewState<T> extends State<AsyncView<T>> {
  T? _data;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final d = await widget.load();
      if (!mounted) return;
      setState(() {
        _data = d;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading && _data == null) return const Center(child: CircularProgressIndicator());
    if (_error != null && _data == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.cloud_off, size: 48, color: Colors.grey),
            const SizedBox(height: 8),
            Text('$_error', textAlign: TextAlign.center),
            const SizedBox(height: 12),
            FilledButton(onPressed: _reload, child: const Text('إعادة المحاولة')),
          ]),
        ),
      );
    }
    return RefreshIndicator(onRefresh: _reload, child: widget.builder(context, _data as T, _reload));
  }
}

void showMessage(BuildContext context, Object message, {bool error = false}) {
  final text = message is ApiException ? message.message : message.toString();
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
    content: Text(text),
    backgroundColor: error ? AppColors.danger : null,
  ));
}
