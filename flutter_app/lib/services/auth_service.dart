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

  /// Retorna o token JWT salvo, ou `null` se não houver sessão ativa.
  Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('jwt_token');
  }

  /// Retorna `true` se há um token salvo (sessão ativa).
  Future<bool> isLoggedIn() async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }
}
