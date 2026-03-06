/// Representa uma câmera retornada pela API /api/v1/cameras
class Camera {
  final int id;
  final String cameraId;
  final String nome;
  final bool ativa;
  final String criticidade;
  final double pesoScore;
  final String? createdAt;
  final String? ip;
  final String? lastSeen;
  final int totalEvents;
  final int eventsToday;
  final String? direcao;
  final double? latitude;
  final double? longitude;
  final String modoIntegracao;
  final String? usuario;

  const Camera({
    required this.id,
    required this.cameraId,
    required this.nome,
    required this.ativa,
    required this.criticidade,
    required this.pesoScore,
    this.createdAt,
    this.ip,
    this.lastSeen,
    required this.totalEvents,
    required this.eventsToday,
    this.direcao,
    this.latitude,
    this.longitude,
    required this.modoIntegracao,
    this.usuario,
  });

  /// Factory para criar Camera a partir do JSON da API
  factory Camera.fromJson(Map<String, dynamic> json) {
    return Camera(
      id: json['id'] as int,
      cameraId: json['camera_id'] as String,
      nome: json['nome'] as String,
      ativa: json['ativa'] as bool? ?? true,
      criticidade: (json['criticidade'] as String?) ?? 'NORMAL',
      pesoScore: (json['peso_score'] as num?)?.toDouble() ?? 1.0,
      createdAt: json['created_at'] as String?,
      ip: json['ip'] as String?,
      lastSeen: json['last_seen'] as String?,
      totalEvents: (json['total_events'] as num?)?.toInt() ?? 0,
      eventsToday: (json['events_today'] as num?)?.toInt() ?? 0,
      direcao: json['direcao'] as String?,
      latitude: json['latitude'] != null ? (json['latitude'] as num).toDouble() : null,
      longitude: json['longitude'] != null ? (json['longitude'] as num).toDouble() : null,
      modoIntegracao: (json['modo_integracao'] as String?) ?? 'push',
      usuario: json['usuario'] as String?,
    );
  }

  /// Converte Camera para JSON
  Map<String, dynamic> toJson() => {
        'id': id,
        'camera_id': cameraId,
        'nome': nome,
        'ativa': ativa,
        'criticidade': criticidade,
        'peso_score': pesoScore,
        'created_at': createdAt,
        'ip': ip,
        'last_seen': lastSeen,
        'total_events': totalEvents,
        'events_today': eventsToday,
        'direcao': direcao,
        'latitude': latitude,
        'longitude': longitude,
        'modo_integracao': modoIntegracao,
        'usuario': usuario,
      };

  /// Verifica se a câmera possui coordenadas GPS
  bool get hasGps => latitude != null && longitude != null;

  /// Status da câmera baseado em last_seen
  String get status {
    if (!ativa) return 'Inativa';
    if (lastSeen == null) return 'Sem comunicação';
    
    final seen = DateTime.tryParse(lastSeen!);
    if (seen == null) return 'Desconhecido';
    
    final diff = DateTime.now().difference(seen);
    if (diff.inMinutes < 5) return 'Online';
    if (diff.inHours < 1) return 'Recente';
    if (diff.inHours < 24) return 'Offline';
    return 'Inativo';
  }

  /// Cor do status para exibição
  String get statusColor {
    final st = status;
    if (st == 'Online') return '#10b981';       // verde
    if (st == 'Recente') return '#f59e0b';      // amarelo
    if (st == 'Offline') return '#ef4444';      // vermelho
    if (st == 'Inativa') return '#6b7280';      // cinza
    return '#9ca3af';                            // cinza claro
  }

  @override
  String toString() => 'Camera($cameraId: $nome @ [$latitude, $longitude])';
}

/// Resultado da API GET /api/v1/cameras
class CameraListResponse {
  final List<Camera> items;
  final int total;

  const CameraListResponse({
    required this.items,
    required this.total,
  });

  factory CameraListResponse.fromJson(Map<String, dynamic> json) {
    final itemsList = json['items'] as List<dynamic>? ?? [];
    return CameraListResponse(
      items: itemsList.map((e) => Camera.fromJson(e as Map<String, dynamic>)).toList(),
      total: json['total'] as int? ?? 0,
    );
  }

  /// Filtra apenas câmeras com GPS
  List<Camera> get withGps => items.where((c) => c.hasGps).toList();

  /// Filtra câmeras sem GPS
  List<Camera> get withoutGps => items.where((c) => !c.hasGps).toList();
}
