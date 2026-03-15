import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Armazenamento seguro e persistente dos tokens JWT.
/// Usa [FlutterSecureStorage] (Keychain no iOS, EncryptedSharedPreferences no Android).
class AuthStorage {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
  );

  static const _keyAccessToken  = 'jwt_access_token';
  static const _keyRefreshToken = 'jwt_refresh_token';

  // ─── Access Token ─────────────────────────────────────────────────────────────────────────

  static Future<void> saveToken(String token) async {
    await _storage.write(key: _keyAccessToken, value: token);
  }

  static Future<String?> getToken() async {
    return _storage.read(key: _keyAccessToken);
  }

  // ─── Refresh Token ───────────────────────────────────────────────────────────────────

  static Future<void> saveRefreshToken(String token) async {
    await _storage.write(key: _keyRefreshToken, value: token);
  }

  static Future<String?> getRefreshToken() async {
    return _storage.read(key: _keyRefreshToken);
  }

  // ─── Limpeza ────────────────────────────────────────────────────────────────────────────

  static Future<void> clear() async {
    await _storage.delete(key: _keyAccessToken);
    await _storage.delete(key: _keyRefreshToken);
  }

  // ─── Verificação de expiração ────────────────────────────────────────────────────────

  /// Retorna true se o access_token está expirado ou ausente.
  static Future<bool> isTokenExpired() async {
    final token = await getToken();
    if (token == null || token.isEmpty) return true;
    try {
      final parts = token.split('.');
      if (parts.length != 3) return true;
      final normalized = base64Url.normalize(parts[1]);
      final decoded    = utf8.decode(base64Url.decode(normalized));
      final data = jsonDecode(decoded) as Map<String, dynamic>;
      final exp  = data['exp'] as int?;
      if (exp == null) return true;
      final expDate = DateTime.fromMillisecondsSinceEpoch(exp * 1000, isUtc: true);
      // Considera expirado se faltam menos de 30 s
      return DateTime.now().toUtc().isAfter(
        expDate.subtract(const Duration(seconds: 30)),
      );
    } catch (_) {
      return true;
    }
  }
}
