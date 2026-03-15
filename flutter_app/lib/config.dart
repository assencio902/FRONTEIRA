/// Configuração global do app.
/// Altere [baseUrl] para o endereço da sua API FastAPI.
class AppConfig {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.20.30.62:8000',
  );
}
