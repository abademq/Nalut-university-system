import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'token_store.dart';

class ApiException implements Exception {
  ApiException(this.status, this.message);

  final int status;
  final String message;

  @override
  String toString() => message;
}

class UploadFile {
  UploadFile(this.field, this.filename, this.bytes);

  final String field;
  final String filename;
  final Uint8List bytes;
}

/// Talks to the platform API. Keeps the short-lived access token in memory and the
/// refresh token in secure storage; a 401 triggers one refresh-and-retry.
class ApiClient {
  ApiClient({required this.store, required this.baseUrl, http.Client? client})
      : _http = client ?? http.Client();

  final TokenStore store;
  final http.Client _http;
  String baseUrl;
  String? _accessToken;
  void Function()? onSessionExpired;

  bool get hasAccessToken => _accessToken != null;

  Uri _uri(String path) => Uri.parse('${baseUrl.replaceAll(RegExp(r'/+$'), '')}$path');

  Map<String, String> _headers({bool json = false, Map<String, String>? extra}) => {
        'Accept': 'application/json',
        'X-Client': 'mobile',
        if (json) 'Content-Type': 'application/json',
        if (_accessToken != null) 'Authorization': 'Bearer $_accessToken',
        ...?extra,
      };

  static String _errorMessage(int status, String body) {
    try {
      final data = jsonDecode(body);
      final detail = data is Map ? data['detail'] : null;
      if (detail is String) return detail;
      if (detail is List) return 'بيانات غير صالحة';
    } catch (_) {}
    if (status == 429) return 'محاولات كثيرة، حاول بعد قليل';
    if (status >= 500) return 'خطأ في الخادم، حاول لاحقاً';
    return 'تعذر إتمام الطلب ($status)';
  }

  Future<http.Response> _send(Future<http.Response> Function() call) async {
    try {
      return await call().timeout(const Duration(seconds: 40));
    } on ApiException {
      rethrow;
    } catch (_) {
      throw ApiException(0, 'تعذر الاتصال بالخادم، تحقق من الإنترنت');
    }
  }

  Future<dynamic> _handle(http.Response res, Future<http.Response> Function() retry, String path) async {
    if (res.statusCode == 401 && !path.startsWith('/api/auth/')) {
      if (await refresh()) {
        res = await _send(retry);
      } else {
        onSessionExpired?.call();
      }
    }
    final body = utf8.decode(res.bodyBytes);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw ApiException(res.statusCode, _errorMessage(res.statusCode, body));
    }
    return body.isEmpty ? null : jsonDecode(body);
  }

  Future<dynamic> get(String path) async {
    call() => _http.get(_uri(path), headers: _headers());
    return _handle(await _send(call), call, path);
  }

  /// Downloads a binary resource (e.g. a submitted file) with the same auth and refresh rules.
  Future<Uint8List> getBytes(String path) async {
    call() => _http.get(_uri(path), headers: _headers());
    var res = await _send(call);
    if (res.statusCode == 401 && await refresh()) res = await _send(call);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw ApiException(res.statusCode, _errorMessage(res.statusCode, utf8.decode(res.bodyBytes)));
    }
    return res.bodyBytes;
  }

  Future<dynamic> patch(String path, Object body) async {
    call() => _http.patch(_uri(path), headers: _headers(json: true), body: jsonEncode(body));
    return _handle(await _send(call), call, path);
  }

  Future<dynamic> post(String path, [Object? body]) async {
    call() => _http.post(_uri(path), headers: _headers(json: true), body: jsonEncode(body ?? {}));
    return _handle(await _send(call), call, path);
  }

  Future<dynamic> put(String path, Object body) async {
    call() => _http.put(_uri(path), headers: _headers(json: true), body: jsonEncode(body));
    return _handle(await _send(call), call, path);
  }

  Future<dynamic> multipart(String path,
      {Map<String, String> fields = const {}, List<UploadFile> files = const [], Map<String, String>? headers}) async {
    Future<http.Response> call() async {
      final req = http.MultipartRequest('POST', _uri(path))
        ..headers.addAll(_headers(extra: headers))
        ..fields.addAll(fields);
      for (final f in files) {
        req.files.add(http.MultipartFile.fromBytes(f.field, f.bytes, filename: f.filename));
      }
      return http.Response.fromStream(await _http.send(req));
    }

    return _handle(await _send(call), call, path);
  }

  // ------------------------------------------------------------------ auth

  /// Returns the server response; on success it contains `user`, otherwise
  /// `mfa_required` or `mfa_setup_required`.
  Future<Map<String, dynamic>> login(String identifier, String password, {String? mfaCode}) async {
    final data = await post('/api/auth/login', {
      'identifier': identifier,
      'password': password,
      if (mfaCode != null && mfaCode.isNotEmpty) 'mfa_code': mfaCode,
    }) as Map<String, dynamic>;
    await _accept(data);
    return data;
  }

  /// Calls a second-factor enrolment endpoint with the short-lived setup token from login.
  /// When enrolment completes the response is a full session, which is kept.
  Future<Map<String, dynamic>> postWithSetupToken(String path, String setupToken, [Object? body]) async {
    call() => _http.post(_uri(path),
        headers: _headers(json: true, extra: {'Authorization': 'Bearer $setupToken'}), body: jsonEncode(body ?? {}));
    final data = (await _handle(await _send(call), call, path) as Map<String, dynamic>?) ?? {};
    await _accept(data);
    return data;
  }

  Future<void> _accept(Map<String, dynamic> data) async {
    if (data['access_token'] != null) {
      _accessToken = data['access_token'] as String;
      final refreshToken = data['refresh_token'] as String?;
      if (refreshToken != null) await store.write(StoreKeys.refreshToken, refreshToken);
    }
  }

  /// Exchanges the stored refresh token for a new pair. Returns the user profile or null.
  Future<Map<String, dynamic>?> restore() async {
    final token = await store.read(StoreKeys.refreshToken);
    if (token == null) return null;
    try {
      final res = await _send(() => _http.post(_uri('/api/auth/refresh'),
          headers: _headers(json: true), body: jsonEncode({'refresh_token': token})));
      if (res.statusCode != 200) {
        if (res.statusCode == 401) await store.write(StoreKeys.refreshToken, null);
        return null;
      }
      final data = jsonDecode(utf8.decode(res.bodyBytes)) as Map<String, dynamic>;
      await _accept(data);
      return data['user'] as Map<String, dynamic>?;
    } on ApiException {
      return null;
    }
  }

  Future<bool> refresh() async => (await restore()) != null;

  Future<void> logout() async {
    final token = await store.read(StoreKeys.refreshToken);
    try {
      if (token != null) await post('/api/auth/logout', {'refresh_token': token});
    } catch (_) {}
    _accessToken = null;
    await store.write(StoreKeys.refreshToken, null);
  }
}
