/// Um hit individual retornado pela busca de placa.
class PlateHit {
  final int? id;
  final String plate;
  final String? cameraId;
  final String? cameraName;
  final String? occurredAt;
  final double? confidence;
  final String? direcao;
  final String? imagePath;
  // Dados do veículo (cam_meta)
  final String? vehicleType;
  final String? vehicleColor;
  final String? plateColor;
  final int? speed;
  final int? speedLimit;
  final String? illegalName;

  const PlateHit({
    this.id,
    required this.plate,
    this.cameraId,
    this.cameraName,
    this.occurredAt,
    this.confidence,
    this.direcao,
    this.imagePath,
    this.vehicleType,
    this.vehicleColor,
    this.plateColor,
    this.speed,
    this.speedLimit,
    this.illegalName,
  });

  factory PlateHit.fromJson(Map<String, dynamic> json) {
    final meta = json['cam_meta'] as Map<String, dynamic>?;
    return PlateHit(
      id: json['id'] as int?,
      plate: (json['plate'] as String?) ?? '',
      cameraId: json['camera_id'] as String?,
      cameraName: (json['camera_name'] ?? json['camera'] ?? json['channel_name'] ?? json['cam_nome']) as String?,
      occurredAt: (json['occurred_at'] ?? json['timestamp']) as String?,
      confidence: (json['confidence'] as num?)?.toDouble(),
      direcao: json['direcao'] as String?,
      imagePath: (json['image_path'] ?? json['image']) as String?,
      vehicleType: meta?['vehicle_type'] as String?,
      vehicleColor: meta?['vehicle_color'] as String?,
      plateColor: meta?['plate_color'] as String?,
      speed: (meta?['speed'] as num?)?.toInt(),
      speedLimit: (meta?['speed_limit'] as num?)?.toInt(),
      illegalName: meta?['illegal_name'] as String?,
    );
  }
}

/// Resultado completo da busca GET /api/events?plate=...
class PlateSearchResult {
  final String status;
  final int total;
  final List<PlateHit> hits;

  const PlateSearchResult({
    required this.status,
    required this.total,
    required this.hits,
  });

  factory PlateSearchResult.fromJson(Map<String, dynamic> json) {
    // Aceita tanto { items: [...] } quanto { hits: [...] }
    final raw = (json['items'] ?? json['hits'] ?? json['events'] ?? []) as List;
    return PlateSearchResult(
      status: (json['status'] as String?) ?? 'ok',
      total: (json['total'] as int?) ?? raw.length,
      hits: raw.map((e) => PlateHit.fromJson(e as Map<String, dynamic>)).toList(),
    );
  }
}
