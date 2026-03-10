/// Configuração global do app.
/// Altere [baseUrl] para o endereço da sua API FastAPI.
class AppConfig {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://104.236.104.79:8000',
  );
}
