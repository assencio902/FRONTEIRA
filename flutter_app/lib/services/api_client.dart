import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config.dart';
import '../models/auth_token.dart';
import '../models/plate_result.dart';
import 'auth_service.dart';

/// Exceção lançada quando a API retorna um erro HTTP.
class ApiException implements Exception {
  final int statusCode;
  final String message;

  const ApiException(this.statusCode, this.message);

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// Cliente HTTP centralizado.
/// • Lê o token salvo no SharedPreferences e injeta em cada requisição.
/// • Lança [ApiException] para respostas ≥ 400.
class ApiClient {
  ApiClient._();
  static final ApiClient instance = ApiClient._();

  // ─── helpers internos ───────────────────────────────────────────────────────

  Map<String, String> _baseHeaders({String? token}) => {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('${AppConfig.baseUrl}$path')
          .replace(queryParameters: query ?? const {});

  void _checkResponse(http.Response res) {
    if (res.statusCode == 401) {
      throw ApiException(401, 'Unauthorized: ${res.body}');
    }
    if (res.statusCode >= 400) {
      String msg;
      try {
        final body = jsonDecode(res.body) as Map;
        msg = (body['detail'] ?? body['message'] ?? res.body).toString();
      } catch (_) {
        msg = res.body.isNotEmpty ? res.body : 'Erro HTTP ${res.statusCode}';
      }
      throw ApiException(res.statusCode, msg);
    }
  }

  // ─── Auth ───────────────────────────────────────────────────────────────────

  /// POST /auth/login  →  salva e retorna [AuthToken].
  Future<AuthToken> login(String email, String password) async {
    final res = await http.post(
      _uri('/auth/login'),
      headers: _baseHeaders(),
      body: jsonEncode({'username': email, 'password': password}),
    );
    _checkResponse(res);
    final token = AuthToken.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('jwt_token', token.accessToken);
    return token;
  }

  /// Remove o token localmente (logout).
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('jwt_token');
  }

  // ─── Placas ─────────────────────────────────────────────────────────────────

  /// GET /api/events?plate=...&limit=10&page=1
  Future<PlateSearchResult> searchPlate(String plate) async {
    final token = await AuthService.instance.getToken();
    final url = _uri('/api/events', {'plate': plate, 'limit': '10', 'page': '1'});
    debugPrint('REQ: GET $url token=${token != null}');
    final res = await http.get(
      url,
      headers: _baseHeaders(token: token),
    );
    debugPrint('RES: ${res.statusCode} body=${res.body}');
    _checkResponse(res);
    return PlateSearchResult.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>);
  }
}
