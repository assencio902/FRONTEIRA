import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import '../models/auth_token.dart';

/// Serviço de autenticação — fachada sobre [ApiClient] + SharedPreferences.
class AuthService {
  AuthService._();
  static final AuthService instance = AuthService._();

  /// Faz login e retorna o token. Lança [ApiException] em falha.
  Future<AuthToken> login(String email, String password) =>
      ApiClient.instance.login(email, password);

  /// Remove o token e encerra a sessão.
  Future<void> logout() => ApiClient.instance.logout();

  /// Retorna `true` se há um token salvo (sessão ativa).
  Future<bool> isLoggedIn() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString('jwt_token');
    return token != null && token.isNotEmpty;
  }
}
