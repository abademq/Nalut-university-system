import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'scan_screen.dart';

class AttendanceScreen extends StatefulWidget {
  const AttendanceScreen({super.key});

  @override
  State<AttendanceScreen> createState() => _AttendanceScreenState();
}

class _AttendanceScreenState extends State<AttendanceScreen> {
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return AsyncView<Map<String, dynamic>>(
      key: ValueKey(_version),
      load: () async => await s.api.get('/api/me/attendance') as Map<String, dynamic>,
      builder: (context, d, reload) {
        final courses = d['courses'] as List<dynamic>;
        final records = d['records'] as List<dynamic>;
        return ListView(padding: const EdgeInsets.all(16), children: [
          FilledButton.icon(
            style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
            icon: const Icon(Icons.qr_code_scanner),
            label: Text(s.isStudent ? 'مسح رمز الحضور' : 'تسجيل الدخول / الانصراف', style: const TextStyle(fontSize: 16)),
            onPressed: () async {
              await Navigator.push(context, MaterialPageRoute(builder: (_) => const ScanScreen()));
              if (mounted) setState(() => _version++);
            },
          ),
          const SizedBox(height: 12),
          if (courses.isNotEmpty)
            SectionCard(
              title: 'نسب الحضور',
              child: Column(children: [
                for (final c in courses)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(c['course']['title'] as String, style: const TextStyle(fontWeight: FontWeight.w600)),
                      Text('محاضرات ${c['sessions']} · حضور ${c['present']} · تأخير ${c['late']} · غياب ${c['absent']}',
                          style: const TextStyle(fontSize: 12, color: Colors.grey)),
                      const SizedBox(height: 4),
                      Row(children: [
                        Expanded(
                          child: LinearProgressIndicator(
                            value: ((c['absence_percent'] as num) / 100).clamp(0, 1).toDouble(),
                            minHeight: 6,
                            borderRadius: BorderRadius.circular(6),
                            color: (c['absence_percent'] as num) >= 25
                                ? AppColors.danger
                                : (c['absence_percent'] as num) >= 15
                                    ? AppColors.warning
                                    : goldText(context),
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text('${pct(c['absence_percent'])} غياب', style: const TextStyle(fontSize: 12)),
                      ]),
                    ]),
                  ),
              ]),
            ),
          SectionCard(
            title: 'السجل',
            child: records.isEmpty
                ? const Text('لا توجد سجلات بعد', style: TextStyle(color: Colors.grey))
                : Column(children: [
                    for (final r in records)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(r['session'] as String),
                        subtitle: Text('${fmtDate(r['starts_at'])}'
                            '${r['check_out_at'] != null ? ' · انصراف ${fmtDate(r['check_out_at'])}' : ''}'),
                        trailing: StatusChip.of(attendanceStatus, r['status'] as String?),
                      ),
                  ]),
          ),
        ]);
      },
    );
  }
}
