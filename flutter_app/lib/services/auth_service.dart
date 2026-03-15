import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../config.dart';
import '../models/auth_token.dart';
import 'api_client.dart';
import 'auth_storage.dart';

/// Serviço de autenticação — fachada sobre [ApiClient] + [AuthStorage].
class AuthService {
  AuthService._();
  static final AuthService instance = AuthService._();

  /// Faz login e retorna o token. Lança [ApiException] em falha.
  Future<AuthToken> login(String username, String password) =>
      ApiClient.instance.login(username, password);

  /// Remove os tokens e encerra a sessão.
  Future<void> logout() => ApiClient.instance.logout();

  /// Retorna o access_token JWT salvo, ou `null` se não houver sessão ativa.
  Future<String?> getToken() => AuthStorage.getToken();

  /// Retorna `true` se há um access_token válido e não expirado.
  Future<bool> isLoggedIn() async {
    final token = await AuthStorage.getToken();
    if (token == null || token.isEmpty) return false;
    return !(await AuthStorage.isTokenExpired());
  }

  /// Tenta restaurar a sessão ao abrir o app:
  ///   1. access_token ainda válido  → retorna true sem chamadas de rede
  ///   2. access_token expirado      → tenta [refreshToken]
  ///   3. refresh falha              → limpa storage e retorna false
  Future<bool> restoreSession() async {
    final token = await AuthStorage.getToken();
    if (token == null || token.isEmpty) {
      debugPrint('[AuthService] restoreSession: sem access_token → login necessário');
      return false;
    }
    final expired = await AuthStorage.isTokenExpired();
    if (!expired) {
      debugPrint('[AuthService] restoreSession: access_token válido');
      return true;
    }
    debugPrint('[AuthService] restoreSession: access_token expirado → tentando refresh');
    return refreshToken();
  }

  /// Usa o refresh_token armazenado para obter novos tokens.
  ///
  /// - Sucesso: salva novos tokens e retorna true.
  /// - Refresh inválido/expirado (4xx backend): limpa storage, retorna false.
  /// - Erro de rede/timeout: NÃO limpa storage (pode ser problem. temporário), retorna false.
  Future<bool> refreshToken() async {
    final refreshTk = await AuthStorage.getRefreshToken();
    if (refreshTk == null || refreshTk.isEmpty) {
      debugPrint('[AuthService] refreshToken: sem refresh_token salvo → login necessário');
      await AuthStorage.clear();
      return false;
    }
    try {
      final url = Uri.parse('\${AppConfig.baseUrl}/api/auth/refresh');
      debugPrint('[AuthService] refreshToken: POST \$url');
      final res = await http.post(
        url,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': refreshTk}),
      ).timeout(const Duration(seconds: 15));

      if (res.statusCode == 200) {
        final data       = jsonDecode(res.body) as Map<String, dynamic>;
        final newAccess  = (data['access_token']  ?? '').toString();
        final newRefresh = (data['refresh_token'] ?? '').toString();
        if (newAccess.isEmpty) {
          debugPrint('[AuthService] refreshToken: 200 OK mas sem access_token');
          await AuthStorage.clear();
          return false;
        }
        await AuthStorage.saveToken(newAccess);
        if (newRefresh.isNotEmpty) {
          await AuthStorage.saveRefreshToken(newRefresh);
        }
        debugPrint('[AuthService] refreshToken: tokens renovados com sucesso');
        return true;
      } else {
        // 401/403: refresh inválido ou expirado → precisa relogar
        debugPrint('[AuthService] refreshToken: falhou HTTP \${res.statusCode} → limpando storage');
        await AuthStorage.clear();
        return false;
      }
    } catch (e) {
      // Erro de rede → não descarta a sessão (pode ser conexão temporária)
      debugPrint('[AuthService] refreshToken: erro de rede/timeout: \$e');
      return false;
    }
  }
}
