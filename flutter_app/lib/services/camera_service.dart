import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/camera.dart';
import 'api_client.dart';
import 'auth_service.dart';

/// Serviço para consumir endpoints de câmeras da API
class CameraService {
  CameraService._();
  static final CameraService instance = CameraService._();

  /// Busca todas as câmeras (incluindo inativas se solicitado)
  /// 
  /// Consome: GET /api/cameras?include_inactive={true|false}
  /// 
  /// Retorna lista de câmeras com coordenadas GPS, status, eventos, etc.
  Future<CameraListResponse> getCameras({bool includeInactive = true}) async {
    try {
      final token = await AuthService.instance.getToken();
      final url = Uri.parse('${AppConfig.baseUrl}/api/cameras')
          .replace(queryParameters: {'include_inactive': includeInactive.toString()});
      
      debugPrint('[CameraService] GET $url');
      
      final res = await http.get(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          if (token != null) 'Authorization': 'Bearer $token',
        },
      );

      debugPrint('[CameraService] Response: ${res.statusCode}');

      if (res.statusCode == 401) {
        throw ApiException(401, 'Não autorizado. Faça login novamente.');
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

      final json = jsonDecode(res.body) as Map<String, dynamic>;
      final response = CameraListResponse.fromJson(json);
      
      debugPrint('[CameraService] Loaded ${response.total} cameras (${response.withGps.length} with GPS)');
      
      return response;
    } catch (e) {
      debugPrint('[CameraService] Error: $e');
      rethrow;
    }
  }

  /// Busca status das câmeras (último evento por camera_id)
  /// 
  /// Consome: GET /api/cameras/status
  /// 
  /// Retorna: Map<String, String?> onde key=camera_id e value=last_seen ISO timestamp
  Future<Map<String, String?>> getCameraStatus() async {
    try {
      final token = await AuthService.instance.getToken();
      final url = Uri.parse('${AppConfig.baseUrl}/api/cameras/status');
      
      debugPrint('[CameraService] GET $url');
      
      final res = await http.get(
        url,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json',
          if (token != null) 'Authorization': 'Bearer $token',
        },
      );

      debugPrint('[CameraService] Response: ${res.statusCode}');

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

      final json = jsonDecode(res.body) as Map<String, dynamic>;
      final statusMap = json['status'] as Map<String, dynamic>? ?? {};
      
      return statusMap.map((k, v) => MapEntry(k, v as String?));
    } catch (e) {
      debugPrint('[CameraService] Error getting status: $e');
      rethrow;
    }
  }

  /// Busca câmeras com GPS válido
  Future<List<Camera>> getCamerasWithGps() async {
    final response = await getCameras(includeInactive: true);
    return response.withGps;
  }
}
