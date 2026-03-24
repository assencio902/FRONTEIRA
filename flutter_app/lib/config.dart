import 'package:flutter/foundation.dart';

/// Configuracao global do app.
///
/// Em producao, informe `--dart-define=API_BASE_URL=https://seu-servidor`.
/// Em debug, usamos o servidor homologado por padrao, com override opcional.
class AppConfig {
  static const String _configuredBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: '',
  );
  static const String _debugConfiguredBaseUrl = String.fromEnvironment(
    'API_DEBUG_BASE_URL',
    defaultValue: 'http://131.100.76.4:17223',
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
    final configured = _normalize(_debugConfiguredBaseUrl);
    if (configured.isNotEmpty) return configured;

    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        return 'http://131.100.76.4:17223';
      case TargetPlatform.iOS:
      case TargetPlatform.macOS:
      case TargetPlatform.windows:
      case TargetPlatform.linux:
      case TargetPlatform.fuchsia:
        return 'http://131.100.76.4:17223';
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
