import 'api_client.dart';
import 'auth_storage.dart';
import '../models/auth_token.dart';

/// Serviço de autenticação — fachada sobre [ApiClient] + SharedPreferences.
class AuthService {
  AuthService._();
  static final AuthService instance = AuthService._();

  /// Faz login e retorna o token. Lança [ApiException] em falha.
  Future<AuthToken> login(String username, String password) =>
      ApiClient.instance.login(username, password);

  /// Remove o token e encerra a sessão.
  Future<void> logout() => ApiClient.instance.logout();

  /// Retorna o token JWT salvo, ou `null` se não houver sessão ativa.
  Future<String?> getToken() => AuthStorage.getToken();

  /// Retorna `true` se há um token salvo (sessão ativa).
  Future<bool> isLoggedIn() async {
    final token = await AuthStorage.getToken();
    if (token == null || token.isEmpty) return false;
    return !(await AuthStorage.isTokenExpired());
  }
}
