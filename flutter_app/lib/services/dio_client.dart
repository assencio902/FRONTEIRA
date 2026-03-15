import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config.dart';
import 'auth_service.dart';
import 'auth_storage.dart';

/// Cliente Dio centralizado com interceptor automático de autenticação.
///
/// Funcionalidades:
///   • Injeta `Authorization: Bearer <token>` em todas as requsições `/api/`
///   • Ao receber HTTP 401 (token expirado em uso), tenta [AuthService.refreshToken]
///     **uma única vez** e repete a requisição original com o novo token
///   • Se o refresh falhar, emite [onForcedLogout] para que a UI redirecione ao login
///
/// Uso básico:
/// ```dart
/// final response = await DioClient.instance.dio.get('/api/cameras');
/// ```
///
/// Escutar logout forçado (ex: em DashboardScreen.initState):
/// ```dart
/// DioClient.instance.onForcedLogout.listen((_) { /* navegar para login */ });
/// ```
class DioClient {
  DioClient._();
  static final DioClient instance = DioClient._();

  final _logoutCtrl = StreamController<String>.broadcast();

  /// Emite um evento quando o refresh falha e o usuário precisa relogar.
  Stream<String> get onForcedLogout => _logoutCtrl.stream;

  late final Dio dio = _build();

  Dio _build() {
    final d = Dio(
      BaseOptions(
        baseUrl: AppConfig.baseUrl,
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 30),
        headers: {
          'Content-Type': 'application/json',
          'Accept':        'application/json',
        },
      ),
    );
    d.interceptors.add(_AuthInterceptor(this));
    return d;
  }

  void dispose() => _logoutCtrl.close();
}

// ─── Interceptor interno ─────────────────────────────────────────────────────

class _AuthInterceptor extends Interceptor {
  final DioClient _client;
  bool _refreshing = false;

  _AuthInterceptor(this._client);

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    final token = await AuthStorage.getToken();
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    final status = err.response?.statusCode;
    final path   = err.requestOptions.path;

    // Só tenta refresh em 401 fora das rotas de auth para evitar loop
    if (status == 401 && !_refreshing && !path.contains('/auth/')) {
      _refreshing = true;
      debugPrint('[DioClient] 401 em $path — tentando refresh de sessão...');

      try {
        final refreshed = await AuthService.instance.refreshToken();

        if (refreshed) {
          debugPrint('[DioClient] Refresh OK — repetindo requisição: $path');
          final opts     = err.requestOptions;
          final newToken = await AuthStorage.getToken();
          opts.headers['Authorization'] = 'Bearer $newToken';
          try {
            final response = await _client.dio.fetch(opts);
            handler.resolve(response);
            return;
          } on DioException catch (retryErr) {
            handler.next(retryErr);
            return;
          }
        } else {
          debugPrint('[DioClient] Refresh falhou — emitindo logout forçado');
          _client._logoutCtrl.add('session_expired');
        }
      } catch (e) {
        debugPrint('[DioClient] Erro durante refresh: $e');
      } finally {
        _refreshing = false;
      }
    }

    handler.next(err);
  }
}
