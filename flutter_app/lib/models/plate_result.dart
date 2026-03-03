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

  const PlateHit({
    this.id,
    required this.plate,
    this.cameraId,
    this.cameraName,
    this.occurredAt,
    this.confidence,
    this.direcao,
    this.imagePath,
  });

  factory PlateHit.fromJson(Map<String, dynamic> json) => PlateHit(
        id: json['id'] as int?,
        plate: (json['plate'] as String?) ?? '',
        cameraId: json['camera_id'] as String?,
        cameraName: json['camera_name'] as String?,
        occurredAt: json['occurred_at'] as String?,
        confidence: (json['confidence'] as num?)?.toDouble(),
        direcao: json['direcao'] as String?,
        imagePath: json['image_path'] as String?,
      );
}

/// Resultado completo da busca GET /plates/search?plate=...
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
