import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'publications_screen.dart';
import 'assignments_screen.dart';
import 'scan_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    // current image announcements on top, then the role's dashboard
    return Column(children: [
      const PosterCarousel(),
      Expanded(child: s.isStudent ? const _StudentHome() : const _StaffHome()),
    ]);
  }
}

class _ScanButton extends StatelessWidget {
  const _ScanButton({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: FilledButton.icon(
          style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
          icon: const Icon(Icons.qr_code_scanner),
          label: Text(label, style: const TextStyle(fontSize: 16)),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ScanScreen())),
        ),
      );
}

class _Kpi extends StatelessWidget {
  const _Kpi(this.label, this.value);
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) => Expanded(
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey)),
              const SizedBox(height: 4),
              Text(value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
            ]),
          ),
        ),
      );
}

class _StudentHome extends StatelessWidget {
  const _StudentHome();

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return AsyncView<List<dynamic>>(
      load: () => Future.wait([
        s.api.get('/api/me/insights'),
        s.api.get('/api/me/schedule'),
        s.api.get('/api/notifications?limit=5'),
        s.api.get('/api/me/attendance'),
        s.api.get('/api/assignments'),
      ]),
      builder: (context, data, reload) {
        final insights = data[0] as Map<String, dynamic>;
        final schedule = data[1] as List<dynamic>;
        final notes = data[2] as Map<String, dynamic>;
        final att = data[3] as Map<String, dynamic>;
        final assignments = data[4] as List<dynamic>;
        final open = assignments.where((a) => ['not_started', 'in_progress'].contains(a['my_status'])).length;
        final courses = (att['courses'] as List<dynamic>);
        final worst = courses.fold<num>(0, (m, c) => (c['absence_percent'] as num) > m ? c['absence_percent'] as num : m);
        final attention = insights['attention'] as List<dynamic>;
        final dueSoon = insights['due_soon'] as List<dynamic>;
        final today = (DateTime.now().weekday + 1) % 7; // Saturday = 0
        final todaySlots = schedule.where((x) => x['day'] == today).toList();
        return ListView(padding: const EdgeInsets.all(16), children: [
          Text('مرحباً، ${s.firstName}', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          const _ScanButton(label: 'تسجيل الحضور بمسح الرمز'),
          Row(children: [
            _Kpi('إشعارات غير مقروءة', '${notes['unread']}'),
            _Kpi('مهام مفتوحة', '$open'),
            _Kpi('أعلى نسبة غياب', pct(worst)),
          ]),
          const SizedBox(height: 8),
          if (attention.isNotEmpty)
            SectionCard(
              title: 'تحتاج إلى اهتمامك',
              child: Column(children: [
                for (final t in attention)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.warning_amber, color: AppColors.warning),
                    title: Text(t['course']['title'] as String),
                    subtitle: Text((t['reasons'] as List).join(' · ')),
                  ),
              ]),
            ),
          SectionCard(
            title: 'مواعيد تسليم قريبة',
            child: dueSoon.isEmpty
                ? const Text('لا توجد مهام مستحقة هذا الأسبوع', style: TextStyle(color: Colors.grey))
                : Column(children: [
                    for (final a in dueSoon)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.assignment_late_outlined),
                        title: Text(a['title'] as String),
                        subtitle: Text('${a['course']} · ${fmtRelative(a['due_at'])}'),
                        onTap: () => Navigator.push(context,
                            MaterialPageRoute(builder: (_) => AssignmentDetailScreen(id: a['id'] as int))),
                      ),
                  ]),
          ),
          SectionCard(
            title: 'محاضرات اليوم (${dayNames[today]})',
            child: todaySlots.isEmpty
                ? const Text('لا توجد محاضرات اليوم', style: TextStyle(color: Colors.grey))
                : Column(children: [
                    for (final x in todaySlots)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.schedule),
                        title: Text(x['title'] as String),
                        subtitle: Text('${x['start']}–${x['end']} · ${x['room']}', textDirection: TextDirection.ltr,
                            textAlign: TextAlign.right),
                      ),
                  ]),
          ),
          SectionCard(
            title: 'الحضور حسب المقرر',
            child: Column(children: [
              for (final c in courses)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Row(children: [
                      Expanded(child: Text(c['course']['title'] as String)),
                      Text('${pct(c['absence_percent'])} غياب'),
                    ]),
                    const SizedBox(height: 4),
                    LinearProgressIndicator(
                      value: ((c['absence_percent'] as num) / 100).clamp(0, 1).toDouble(),
                      color: (c['absence_percent'] as num) >= 25
                          ? AppColors.danger
                          : (c['absence_percent'] as num) >= 15
                              ? AppColors.warning
                              : AppColors.primary,
                      minHeight: 6,
                      borderRadius: BorderRadius.circular(6),
                    ),
                  ]),
                ),
            ]),
          ),
        ]);
      },
    );
  }
}

class _StaffHome extends StatelessWidget {
  const _StaffHome();

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    final role = s.role;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('مرحباً، ${s.firstName}', style: Theme.of(context).textTheme.titleLarge),
      Text('${roleLabels[role] ?? role}${s.user?['faculty'] != null ? ' — ${s.user!['faculty']['name']}' : ''}',
          style: const TextStyle(color: Colors.grey)),
      const SizedBox(height: 16),
      if (s.canCheckIn) const _ScanButton(label: 'تسجيل الدوام (دخول / انصراف)'),
      if (s.isInstructor)
        AsyncView<List<dynamic>>(
          load: () async => await s.api.get('/api/assignments') as List<dynamic>,
          builder: (context, list, _) {
            final toReview = list.fold<num>(0, (n, a) => n + (a['stats']['submitted'] as num) - (a['stats']['reviewed'] as num));
            return SectionCard(
              title: 'المهام',
              child: Text('$toReview تسليم بانتظار التقييم في ${list.length} مهمة'),
            );
          },
        ),
      SectionCard(
        title: 'لوحة التحكم',
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('إدارة المقررات والدرجات وجلسات الحضور والتقارير متاحة من لوحة التحكم على الويب، '
              'وهي تعمل أيضاً من متصفح الهاتف.'),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            icon: const Icon(Icons.open_in_new),
            label: const Text('فتح لوحة التحكم'),
            onPressed: () => launchUrl(Uri.parse(s.api.baseUrl), mode: LaunchMode.externalApplication),
          ),
        ]),
      ),
    ]);
  }
}
