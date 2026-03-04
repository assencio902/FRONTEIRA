import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/plate_result.dart';
import 'auth_storage.dart';

/// API simples centralizada.
/// Usa [AuthStorage] para persistir e ler o token JWT automaticamente.
class Api {
  static const String baseUrl = 'http://104.236.104.79:8000';

  // ─── Headers ─────────────────────────────────────────────────────────────

  static Future<Map<String, String>> headers({bool auth = true}) async {
    final h = <String, String>{'Content-Type': 'application/json'};
    if (auth) {
      final token = await AuthStorage.getToken();
      if (token != null) h['Authorization'] = 'Bearer $token';
    }
    return h;
  }

  // ─── Login ────────────────────────────────────────────────────────────────

  /// POST /api/auth/login — salva o access_token no [AuthStorage].
  static Future<void> login(String username, String password) async {
    final url = Uri.parse('$baseUrl/api/auth/login');
    debugPrint('REQ: POST $url');
    final res = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    );
    debugPrint('RES login: ${res.statusCode} body=${res.body}');
    if (res.statusCode != 200) {
      throw Exception('Login falhou (${res.statusCode}): ${res.body}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final token = data['access_token'] as String;
    await AuthStorage.saveToken(token);
  }

  // ─── Placas ───────────────────────────────────────────────────────────────

  /// GET /api/events?plate=...&limit=10&page=1 — retorna [PlateSearchResult].
  /// Envia automaticamente o token salvo no [AuthStorage].
  static Future<PlateSearchResult> platesSearch(String plate) async {
    final url = Uri.parse('$baseUrl/api/events').replace(
      queryParameters: {'plate': plate, 'limit': '10', 'page': '1'},
    );
    final h = await headers();
    debugPrint('REQ: GET $url token=${h.containsKey("Authorization")}');
    final res = await http.get(url, headers: h);
    debugPrint('RES platesSearch: ${res.statusCode} body=${res.body}');
    if (res.statusCode == 401) {
      throw Exception('Não autenticado (401): ${res.body}');
    }
    if (res.statusCode >= 400) {
      throw Exception('Erro ${res.statusCode}: ${res.body}');
    }
    return PlateSearchResult.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>);
  }

  /// GET /api/v1/cameras — retorna lista de câmeras cadastradas.
  static Future<List<Map<String, dynamic>>> getCameras() async {
    final url = Uri.parse('$baseUrl/api/v1/cameras');
    final h = await headers();
    final res = await http.get(url, headers: h);
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) throw Exception('Erro ${res.statusCode}');
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return List<Map<String, dynamic>>.from(data['items'] as List);
  }

  /// GET /api/v1/stats/overview — estatísticas gerais do sistema.
  static Future<Map<String, dynamic>> getStats() async {
    final url = Uri.parse('$baseUrl/api/v1/stats/overview');
    final h = await headers();
    final res = await http.get(url, headers: h);
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) throw Exception('Erro ${res.statusCode}');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// GET /api/events?limit=N&page=1 — últimas passagens sem filtro de placa.
  static Future<List<Map<String, dynamic>>> getRecentEvents(
      {int limit = 15}) async {
    final url = Uri.parse('$baseUrl/api/events').replace(
      queryParameters: {'limit': '$limit', 'page': '1'},
    );
    final h = await headers();
    final res = await http.get(url, headers: h);
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) throw Exception('Erro ${res.statusCode}');
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return List<Map<String, dynamic>>.from(
        (data['items'] ?? data['events'] ?? []) as List);
  }
}
