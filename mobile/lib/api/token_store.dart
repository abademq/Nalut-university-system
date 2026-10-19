import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Values kept in the OS secure storage (Android Keystore / iOS Keychain).
abstract class TokenStore {
  Future<String?> read(String key);
  Future<void> write(String key, String? value);
}

class SecureTokenStore implements TokenStore {
  final _storage = const FlutterSecureStorage();

  @override
  Future<String?> read(String key) async {
    try {
      return await _storage.read(key: key);
    } catch (_) {
      // Keystore entries can become unreadable (e.g. after an OS restore). Start clean.
      await _storage.deleteAll().catchError((Object _) {});
      return null;
    }
  }

  @override
  Future<void> write(String key, String? value) =>
      value == null ? _storage.delete(key: key) : _storage.write(key: key, value: value);
}

class MemoryTokenStore implements TokenStore {
  final Map<String, String> values = {};

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String? value) async =>
      value == null ? values.remove(key) : values[key] = value;
}

class StoreKeys {
  static const refreshToken = 'refresh_token';
  static const serverUrl = 'server_url';
  static const deviceId = 'device_id';
}

/// Random per-install identifier (not a hardware id), sent with check-ins as a risk signal.
Future<String> deviceIdFrom(TokenStore store) async {
  var id = await store.read(StoreKeys.deviceId);
  if (id == null || id.isEmpty) {
    final rnd = Random.secure();
    id = List.generate(16, (_) => rnd.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
    await store.write(StoreKeys.deviceId, id);
  }
  return id;
}

String newNonce() {
  final rnd = Random.secure();
  return List.generate(16, (_) => rnd.nextInt(256).toRadixString(16).padLeft(2, '0')).join();
}
