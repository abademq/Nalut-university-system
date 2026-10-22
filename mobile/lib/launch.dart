import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import 'api/api_client.dart';

/// The launch screen and start-up sound, chosen by the platform administrator.
///
/// The app shows it before anyone signs in, so the last answer from GET /api/app/launch is kept
/// on the phone (with the picture) and refreshed in the background for the next start.
class LaunchConfig {
  const LaunchConfig({
    this.universityId,
    this.enabled = true,
    this.durationMs = 1800,
    this.title = 'منصة الجامعة الذكية',
    this.subtitle = 'جامعة نالوت',
    this.background = const Color(0xFF0B3B32),
    this.foreground = const Color(0xFFF7F4EC),
    this.accent = const Color(0xFFC8A24A),
    this.showLoader = true,
    this.sound = 'welcome',
    this.imageVersion,
    this.image,
  });

  final int? universityId;
  final bool enabled;
  final int durationMs;
  final String title;
  final String subtitle;
  final Color background;
  final Color foreground;
  final Color accent;
  final bool showLoader;
  final String sound;
  final String? imageVersion;
  final Uint8List? image; // null: the bundled logo

  static Color _color(Object? hex, Color fallback) {
    final m = RegExp(r'^#([0-9A-Fa-f]{6})$').firstMatch('${hex ?? ''}');
    return m == null ? fallback : Color(0xFF000000 | int.parse(m.group(1)!, radix: 16));
  }

  factory LaunchConfig.fromJson(Map<String, dynamic> j, {Uint8List? image}) {
    const d = LaunchConfig();
    final l = (j['launch'] as Map?) ?? const {};
    return LaunchConfig(
      universityId: j['university_id'] as int?,
      enabled: l['enabled'] as bool? ?? d.enabled,
      durationMs: (l['duration_ms'] as num?)?.toInt() ?? d.durationMs,
      title: l['title'] as String? ?? d.title,
      subtitle: l['subtitle'] as String? ?? d.subtitle,
      background: _color(l['background'], d.background),
      foreground: _color(l['foreground'], d.foreground),
      accent: _color(l['accent'], d.accent),
      showLoader: l['show_loader'] as bool? ?? d.showLoader,
      sound: l['sound'] as String? ?? d.sound,
      imageVersion: j['image_version'] as String?,
      image: j['image_version'] == null ? null : image,
    );
  }
}

class LaunchStore {
  static Future<Directory> _dir() async => getApplicationSupportDirectory();

  /// The saved configuration, or the defaults on a first start (never throws).
  static Future<LaunchConfig> load() async {
    try {
      final dir = await _dir();
      final f = File('${dir.path}/launch.json');
      if (!await f.exists()) return const LaunchConfig();
      final j = jsonDecode(await f.readAsString()) as Map<String, dynamic>;
      final img = File('${dir.path}/launch_image');
      return LaunchConfig.fromJson(j, image: await img.exists() ? await img.readAsBytes() : null);
    } catch (_) {
      return const LaunchConfig();
    }
  }

  /// Fetches the current configuration for next time; failures keep what is saved.
  static Future<LaunchConfig?> refresh(ApiClient api, LaunchConfig current, {int? universityId}) async {
    try {
      final u = universityId ?? current.universityId;
      final query = u == null ? '' : '?u=$u';
      final j = await api.get('/api/app/launch$query') as Map<String, dynamic>;
      final dir = await _dir();
      final img = File('${dir.path}/launch_image');
      Uint8List? bytes = current.image;
      if (j['image_version'] == null) {
        if (await img.exists()) await img.delete();
        bytes = null;
      } else if (j['image_version'] != current.imageVersion || bytes == null) {
        bytes = await api.getBytes('/api/app/launch/image$query');
        await img.writeAsBytes(bytes, flush: true);
      }
      await File('${dir.path}/launch.json').writeAsString(jsonEncode(j), flush: true);
      return LaunchConfig.fromJson(j, image: bytes);
    } catch (_) {
      return null;
    }
  }
}
