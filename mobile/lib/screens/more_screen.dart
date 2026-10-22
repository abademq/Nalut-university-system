import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../state/session.dart';
import '../widgets/common.dart';
import 'account_screen.dart';
import 'courses_screen.dart';
import 'grade_entry_screen.dart';
import 'grades_screen.dart';
import 'guide_screen.dart';
import 'messages_screen.dart';
import 'oversight_screens.dart';
import 'publications_screen.dart';
import 'publish_screen.dart';
import 'reports_screen.dart';
import 'requests_screen.dart';
import 'results_screen.dart';
import 'send_notification_screen.dart';

class MoreScreen extends StatelessWidget {
  const MoreScreen({super.key});

  Widget _tile(BuildContext context, IconData icon, String title, Widget page, {String? subtitle}) => ListTile(
        leading: Icon(icon),
        title: Text(title),
        subtitle: subtitle == null ? null : Text(subtitle),
        trailing: const Icon(Icons.chevron_left),
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => page)),
      );

  /// One-time link (60 s) that signs the browser in as this user.
  Future<void> _openDashboard(BuildContext context, Session s) async {
    try {
      final r = await s.api.post('/api/auth/handoff/start') as Map<String, dynamic>;
      await launchUrl(Uri.parse('${s.api.baseUrl}${r['path']}'), mode: LaunchMode.externalApplication);
    } catch (e) {
      if (context.mounted) showMessage(context, e, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<Session>();
    final u = s.user ?? {};
    return ListView(padding: const EdgeInsets.all(12), children: [
      Card(
        child: ListTile(
          leading: const CircleAvatar(child: Icon(Icons.person)),
          title: Text(u['full_name'] as String? ?? ''),
          subtitle: Text([
            roleLabels[u['role']] ?? '',
            if (u['code'] != null) '${u['code']}',
            if (u['faculty'] != null) '${u['faculty']['name']}',
          ].join(' · ')),
        ),
      ),
      Card(
        child: Column(children: [
          _tile(context, Icons.manage_accounts_outlined, 'حسابي', const AccountScreen(),
              subtitle: 'كلمة المرور، التحقق الثنائي، التفضيلات'),
          if (s.isStudent) _tile(context, Icons.grade_outlined, 'درجاتي ونتائجي', const GradesScreen()),
          if (s.isInstructor || s.isAdmin)
            _tile(context, Icons.edit_note, 'رصد الدرجات', const GradeEntryScreen(), subtitle: 'إدخال الدرجات ورفعها للاعتماد'),
          if (s.isAdmin) _tile(context, Icons.fact_check_outlined, 'اعتماد النتائج', const ResultsScreen()),
          if (s.isInstructor || s.isAdmin)
            _tile(context, Icons.event_note_outlined, 'المقررات والمحاضرات', const CoursesScreen(),
                subtitle: s.isAdmin ? 'إضافة مقررات، مواعيد المحاضرات، عناصر التقييم' : 'مواعيد محاضراتك وعناصر التقييم'),
          if (s.isInstructor || s.isAdmin)
            _tile(context, Icons.insights_outlined, 'التقارير والإحصاءات', const ReportsScreen(),
                subtitle: 'تقرير مبسط لكل طالب أو أستاذ أو موظف'),
          if (u['id'] != null && s.role != 'platform_admin')
            _tile(context, Icons.assessment_outlined, 'تقريري', PersonReportScreen(userId: u['id'] as int, title: 'تقريري')),
          if (s.isStudent || s.isInstructor)
            _tile(context, Icons.calendar_view_week_outlined, 'جدولي الأسبوعي', const TimetableScreen()),
          _tile(context, Icons.photo_library_outlined, 'الجداول والإعلانات المصورة', const PublicationsScreen(),
              subtitle: 'جداول المحاضرات المنشورة والإعلانات بالصور'),
          _tile(context, Icons.description_outlined, 'الطلبات والمعاملات', const RequestsScreen(),
              subtitle: s.role == 'staff' || s.isAdmin ? 'طلباتي والوارد إليّ' : 'إفادة قيد، كشف درجات، عذر غياب…'),
          if (s.isAdmin && s.can('banners.manage'))
            _tile(context, Icons.push_pin_outlined, 'الإعلانات المثبتة', const ManageBannersScreen()),
          if (s.can('publications.manage') && (s.isAdmin || s.role == 'staff'))
            _tile(context, Icons.add_photo_alternate_outlined, 'نشر الجداول والإعلانات', const ManagePublicationsScreen(),
                subtitle: 'جدول محاضرات أو إعلان مصور من الكاميرا أو المعرض أو PDF'),
          if (s.isAdmin) _tile(context, Icons.policy_outlined, 'سجل التدقيق', const AuditScreen()),
          if (s.isAdmin) _tile(context, Icons.flag_outlined, 'بلاغات الرسائل', const AbuseReportsScreen()),
          if (canSendNotifications(s.user))
            _tile(context, Icons.campaign_outlined, 'إرسال إشعار', const SendNotificationScreen()),
          _tile(context, Icons.chat_outlined, 'الرسائل', const MessagesScreen()),
          _tile(context, Icons.help_outline, 'دليل الاستخدام', const GuideScreen()),
          if (s.isAdmin || s.role == 'staff' || s.isInstructor)
            ListTile(
              leading: const Icon(Icons.dashboard_outlined),
              title: const Text('لوحة التحكم الكاملة'),
              subtitle: const Text('تفتح لوحة الويب مسجّلاً دون كلمة مرور'),
              trailing: const Icon(Icons.open_in_new),
              onTap: () => _openDashboard(context, s),
            ),
        ]),
      ),
      Card(
        child: ListTile(
          leading: const Icon(Icons.logout, color: Colors.red),
          title: const Text('تسجيل الخروج', style: TextStyle(color: Colors.red)),
          onTap: () async {
            final ok = await showDialog<bool>(
              context: context,
              builder: (ctx) => AlertDialog(
                title: const Text('تسجيل الخروج؟'),
                actions: [
                  TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
                  FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('خروج')),
                ],
              ),
            );
            if (ok == true) await s.logout();
          },
        ),
      ),
      Padding(
        padding: const EdgeInsets.all(12),
        child: Text(s.api.baseUrl, textAlign: TextAlign.center, textDirection: TextDirection.ltr,
            style: const TextStyle(fontSize: 11, color: Colors.grey)),
      ),
    ]);
  }
}
