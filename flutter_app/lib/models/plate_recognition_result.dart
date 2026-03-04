/// Resultado do reconhecimento de placa via API (POST /plates/recognize).
class PlateRecognitionResult {
  /// Placa detectada com maior confiança.
  final String? plate;

  /// Confiança entre 0.0 e 1.0.
  final double? confidence;

  /// Lista de candidatos em ordem decrescente de confiança.
  final List<String>? candidates;

  const PlateRecognitionResult({
    this.plate,
    this.confidence,
    this.candidates,
  });

  factory PlateRecognitionResult.fromJson(Map<String, dynamic> json) {
    return PlateRecognitionResult(
      plate: json['plate'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble(),
      candidates: (json['candidates'] as List<dynamic>?)
          ?.map((e) => e.toString())
          .toList(),
    );
  }

  @override
  String toString() =>
      'PlateRecognitionResult(plate=$plate, confidence=$confidence, candidates=$candidates)';
}
