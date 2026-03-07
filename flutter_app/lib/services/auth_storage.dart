import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

/// Armazenamento persistente do token JWT.
class AuthStorage {
  static const _key = 'jwt_token';

  static Future<void> saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_key, token);
  }

  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_key);
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_key);
  }

  /// Verifica se o token JWT salvo está expirado (decodifica payload base64).
  /// Retorna true se expirado ou ausente.
  static Future<bool> isTokenExpired() async {
    final token = await getToken();
    if (token == null || token.isEmpty) return true;
    try {
      final parts = token.split('.');
      if (parts.length != 3) return true;
      final payload = parts[1];
      final normalized = base64Url.normalize(payload);
      final decoded = utf8.decode(base64Url.decode(normalized));
      final data = jsonDecode(decoded) as Map<String, dynamic>;
      final exp = data['exp'] as int?;
      if (exp == null) return true;
      final expDate = DateTime.fromMillisecondsSinceEpoch(exp * 1000, isUtc: true);
      // Considerar expirado se falta menos de 30 segundos
      return DateTime.now().toUtc().isAfter(expDate.subtract(const Duration(seconds: 30)));
    } catch (_) {
      return true;
    }
  }
}
