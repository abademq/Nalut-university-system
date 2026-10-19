import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config.dart';
import '../state/session.dart';
import '../widgets/common.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  String _category = '';
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final s = context.read<Session>();
    return Column(children: [
      SizedBox(
        height: 52,
        child: ListView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          children: [
            for (final e in {'': 'الكل', ...categoryLabels}.entries)
              Padding(
                padding: const EdgeInsets.only(left: 6),
                child: ChoiceChip(
                  label: Text(e.value),
                  selected: _category == e.key,
                  onSelected: (_) => setState(() => _category = e.key),
                ),
              ),
          ],
        ),
      ),
      Expanded(
        child: AsyncView<Map<String, dynamic>>(
          key: ValueKey('$_category$_version'),
          load: () async => await s.api.get('/api/notifications?limit=100${_category.isEmpty ? '' : '&category=$_category'}')
              as Map<String, dynamic>,
          builder: (context, d, reload) {
            final items = d['items'] as List<dynamic>;
            return ListView(padding: const EdgeInsets.symmetric(horizontal: 12), children: [
              if (d['unread'] as int > 0)
                Align(
                  alignment: AlignmentDirectional.centerEnd,
                  child: TextButton(
                    onPressed: () async {
                      await s.api.post('/api/notifications/read-all');
                      await s.refreshUnread();
                      setState(() => _version++);
                    },
                    child: const Text('تعليم الكل كمقروء'),
                  ),
                ),
              if (items.isEmpty) const EmptyView('لا توجد إشعارات', icon: Icons.notifications_none),
              for (final n in items) _NotificationTile(n: n as Map<String, dynamic>, onRead: () => setState(() => _version++)),
            ]);
          },
        ),
      ),
    ]);
  }
}

class _NotificationTile extends StatelessWidget {
  const _NotificationTile({required this.n, required this.onRead});
  final Map<String, dynamic> n;
  final VoidCallback onRead;

  @override
  Widget build(BuildContext context) {
    final unread = n['read_at'] == null;
    final priority = n['priority'] as String?;
    final edge = priority == 'urgent'
        ? AppColors.danger
        : priority == 'important'
            ? AppColors.warning
            : Colors.transparent;
    return Card(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: edge == Colors.transparent ? const Color(0xFFDDE4E1) : edge, width: edge == Colors.transparent ? 1 : 1.5),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () async {
          final s = context.read<Session>();
          if (unread) {
            try {
              await s.api.post('/api/notifications/${n['delivery_id']}/read');
              await s.refreshUnread();
              onRead();
            } catch (_) {}
          }
        },
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.only(top: 6, left: 8),
              child: CircleAvatar(radius: 5, backgroundColor: unread ? AppColors.primary : Colors.transparent),
            ),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text(n['title'] as String, style: const TextStyle(fontWeight: FontWeight.bold))),
                  Text(fmtRelative(n['created_at']), style: const TextStyle(fontSize: 11, color: Colors.grey)),
                ]),
                const SizedBox(height: 4),
                Text(n['body'] as String),
                const SizedBox(height: 6),
                Wrap(spacing: 6, children: [
                  StatusChip(StatusStyle(categoryLabels[n['category']] ?? '',
                      n['category'] == 'official_warning' ? AppColors.danger : AppColors.primary)),
                  if (priority == 'urgent') const StatusChip(StatusStyle('عاجل', AppColors.danger)),
                  if (priority == 'important') const StatusChip(StatusStyle('مهم', AppColors.warning)),
                  if (n['sender'] != null) Text(n['sender'] as String, style: const TextStyle(fontSize: 12, color: Colors.grey)),
                ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}
