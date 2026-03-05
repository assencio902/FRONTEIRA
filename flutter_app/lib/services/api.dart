import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/plate_result.dart';
import 'auth_storage.dart';

/// API simples centralizada.
/// Usa [AuthStorage] para persistir e ler o token JWT automaticamente.
/// Base URL:
///   - Produção: http://104.236.104.79:8000
///   - Local (emulador): http://10.0.2.2:8000
///   - Local (dispositivo): http://192.168.x.x:8000 (IP da máquina host)
class Api {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://104.236.104.79:8000',
  );

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
    ).timeout(const Duration(seconds: 10));
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
  static Future<PlateSearchResult> platesSearch(
    String plate, {
    DateTime? dtFrom,
    DateTime? dtTo,
  }) async {
    final params = <String, String>{
      'plate': plate,
      'limit': '10',
      'page': '1',
    };
    if (dtFrom != null) params['dt_from'] = dtFrom.toIso8601String();
    if (dtTo != null) params['dt_to'] = dtTo.toIso8601String();

    final url = Uri.parse('$baseUrl/api/events').replace(
      queryParameters: params,
    );
    final h = await headers();
    debugPrint('REQ: GET $url token=${h.containsKey("Authorization")}');
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 10));
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
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 10));
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) throw Exception('Erro ${res.statusCode}');
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return List<Map<String, dynamic>>.from(data['items'] as List);
  }

  /// GET /api/v1/stats/overview — estatísticas gerais do sistema.
  static Future<Map<String, dynamic>> getStats() async {
    final url = Uri.parse('$baseUrl/api/v1/stats/overview');
    final h = await headers();
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 10));
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) throw Exception('Erro ${res.statusCode}');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// GET /api/batedor/trajeto/{plate} — veículos que fizeram o mesmo percurso.
  static Future<Map<String, dynamic>> getBatedorTrajeto({
    required String plate,
    String window = '24h',
    int coWindow = 600,
    int minCameras = 2,
    int limit = 30,
    // Filtros do suspeito
    String? direcao,
    String? vehicleType,
    String? vehicleColor,
    String? platePrefix,
  }) async {
    final params = <String, String>{
      'window':      window,
      'co_window':   '$coWindow',
      'min_cameras': '$minCameras',
      'limit':       '$limit',
    };
    if (direcao     != null && direcao.isNotEmpty)     params['direcao']       = direcao;
    if (vehicleType != null && vehicleType.isNotEmpty) params['vehicle_type']  = vehicleType;
    if (vehicleColor!= null && vehicleColor.isNotEmpty)params['vehicle_color'] = vehicleColor;
    if (platePrefix != null && platePrefix.isNotEmpty) params['plate_prefix']  = platePrefix;

    final url = Uri.parse('$baseUrl/api/batedor/trajeto/$plate').replace(queryParameters: params);
    final h = await headers();
    debugPrint('REQ: GET $url');
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 15));
    debugPrint('RES getBatedorTrajeto: ${res.statusCode}');
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) throw Exception('Erro ${res.statusCode}: ${res.body}');
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// GET /api/batedor/plate/{plate} — passagens de uma placa na janela de tempo.
  static Future<Map<String, dynamic>> getBatedorPlate({
    required String plate,
    String windowMinutes = '180',
    int limit = 50,
  }) async {
    final url =
        Uri.parse('$baseUrl/api/batedor/plate/$plate').replace(queryParameters: {
      'window_minutes': windowMinutes,
      'limit': '$limit',
    });
    final h = await headers();
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 10));
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
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 10));
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) throw Exception('Erro ${res.statusCode}');
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return List<Map<String, dynamic>>.from(
        (data['items'] ?? data['events'] ?? []) as List);
  }

  /// GET /api/batedor/grupos_comboio — detecta grupos de veículos em comboio.
  /// Retorna grupos de 2+ veículos que andaram juntos em 2+ câmaras distintas.
  static Future<Map<String, dynamic>> getGruposComboio({
    String window = '24h',
    int coWindow = 300,
    String groupSizes = '2',
    int minCameras = 2,
    int maxTripGap = 3600,
    String orderMode = 'any',
    double leaderRatio = 0.7,
    double maxFrontRatioOther = 0.3,
    int payloadMaxFront = 0,
    String plate = '',
    int limit = 100,
  }) async {
    final params = <String, String>{
      'window': window,
      'co_window': '$coWindow',
      'group_sizes': groupSizes,
      'min_cameras': '$minCameras',
      'max_trip_gap': '$maxTripGap',
      'order_mode': orderMode,
      'leader_ratio': '$leaderRatio',
      'max_front_ratio_other': '$maxFrontRatioOther',
      'payload_max_front': '$payloadMaxFront',
      'limit': '$limit',
    };
    if (plate.isNotEmpty) {
      params['plate'] = plate;
    }
    final url = Uri.parse('$baseUrl/api/batedor/grupos_comboio')
        .replace(queryParameters: params);
    final h = await headers();
    debugPrint('REQ: GET $url');
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 15));
    debugPrint('RES getGruposComboio: ${res.statusCode}');
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) {
      throw Exception('Erro ${res.statusCode}: ${res.body}');
    }
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// GET /api/batedor/central — Central de Ameaças unificada.
  /// Retorna passagens com detecção de parceiros, grupos e comboios.
  static Future<Map<String, dynamic>> getBatedorCentral({
    String? plate,
    String? camera,
    DateTime? dtFrom,
    DateTime? dtTo,
    int limit = 100,
  }) async {
    final params = <String, String>{
      'limit': '$limit',
    };
    if (plate != null && plate.isNotEmpty) params['plate'] = plate;
    if (camera != null && camera.isNotEmpty) params['camera'] = camera;
    if (dtFrom != null) params['dt_from'] = dtFrom.toIso8601String();
    if (dtTo != null) params['dt_to'] = dtTo.toIso8601String();

    final url = Uri.parse('$baseUrl/api/batedor/central')
        .replace(queryParameters: params);
    final h = await headers();
    debugPrint('REQ: GET $url');
    final res = await http.get(url, headers: h).timeout(const Duration(seconds: 15));
    debugPrint('RES getBatedorCentral: ${res.statusCode}');
    if (res.statusCode == 401) throw Exception('Não autenticado (401)');
    if (res.statusCode >= 400) {
      throw Exception('Erro ${res.statusCode}: ${res.body}');
    }
    return jsonDecode(res.body) as Map<String, dynamic>;
  }
}
