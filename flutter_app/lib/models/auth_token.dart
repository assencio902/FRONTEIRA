/// Modelo do token retornado pelo POST /api/auth/login e POST /api/auth/refresh.
class AuthToken {
  final String  accessToken;
  final String  tokenType;
  final String? refreshToken;
  final int?    expiresIn;

  const AuthToken({
    required this.accessToken,
    required this.tokenType,
    this.refreshToken,
    this.expiresIn,
  });

  factory AuthToken.fromJson(Map<String, dynamic> json) => AuthToken(
        accessToken:  json['access_token']  as String,
        tokenType:    (json['token_type']   as String?) ?? 'bearer',
        refreshToken: json['refresh_token'] as String?,
        expiresIn:    json['expires_in']    as int?,
      );
}
