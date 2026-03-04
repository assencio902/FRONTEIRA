import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';

import '../models/plate_recognition_result.dart';

/// Reconhece placa veicular diretamente na imagem usando ML Kit (on-device).
/// Não depende de nenhum endpoint backend.
class PlateRecognitionRepository {
  // Padrões de placa brasileira:
  //   Antiga  : ABC1234
  //   Mercosul: ABC1D23
  static final RegExp _plateRegex = RegExp(
    r'\b([A-Z]{3}[-\s]?\d{1}[A-Z]{1}\d{2}|[A-Z]{3}[-\s]?\d{4})\b',
    caseSensitive: false,
  );

  static Future<PlateRecognitionResult> recognize(File image) async {
    final inputImage = InputImage.fromFile(image);
    final recognizer = TextRecognizer(script: TextRecognitionScript.latin);

    try {
      final RecognizedText recognized = await recognizer.processImage(inputImage);

      debugPrint('[PlateOCR] texto completo: ${recognized.text}');

      // Normaliza: remove quebras de linha, converte para maiúsculo
      final allText = recognized.text.toUpperCase().replaceAll('\n', ' ');

      // Procura padrão de placa no texto
      final match = _plateRegex.firstMatch(allText);

      if (match != null) {
        final plate = match.group(0)!
            .toUpperCase()
            .replaceAll(RegExp(r'[-\s]'), '');
        debugPrint('[PlateOCR] placa detectada: $plate');
        return PlateRecognitionResult(plate: plate, confidence: 0.9);
      }

      // Fallback: qualquer token de 7 chars alfanuméricos
      final tokens = allText.split(RegExp(r'[\s,;:]+'));
      for (final tok in tokens) {
        final clean = tok.replaceAll(RegExp(r'[^A-Z0-9]'), '');
        if (clean.length == 7) {
          debugPrint('[PlateOCR] fallback token: $clean');
          return PlateRecognitionResult(plate: clean, confidence: 0.5);
        }
      }

      debugPrint('[PlateOCR] nenhuma placa detectada');
      return const PlateRecognitionResult(plate: null, confidence: 0.0);
    } finally {
      recognizer.close();
    }
  }
}
