import 'package:flutter/foundation.dart';

/// Configuracao global do app.
///
/// Em producao, informe `--dart-define=API_BASE_URL=https://seu-servidor`.
/// Em debug, usamos um fallback local para facilitar o desenvolvimento.
class AppConfig {
  static const String _configuredBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );

  static String get baseUrl {
    final configured = _normalize(_configuredBaseUrl);
    if (configured.isNotEmpty) return configured;

    if (kReleaseMode) {
      throw StateError(
        'API_BASE_URL deve ser informado em builds de release.',
      );
    }

    return _normalize(_debugDefaultBaseUrl());
  }

  static String _debugDefaultBaseUrl() {
    if (kIsWeb) return 'http://127.0.0.1:8000';

    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return 'http://10.0.2.2:8000';
      case TargetPlatform.iOS:
      case TargetPlatform.macOS:
      case TargetPlatform.windows:
      case TargetPlatform.linux:
      case TargetPlatform.fuchsia:
        return 'http://127.0.0.1:8000';
    }
  }

  static String _normalize(String value) {
    final trimmed = value.trim();
    if (trimmed.endsWith('/')) {
      return trimmed.substring(0, trimmed.length - 1);
    }
    return trimmed;
  }
}
