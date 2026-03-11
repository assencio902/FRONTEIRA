import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';

/// Campo de pesquisa por placa padronizado para uso em todas as telas.
///
/// Aceita e exibe texto em caixa alta, formata no padrão de placa.
/// Inclui ícone de busca/carro, prefixo e bordas consistentes.
class PlateSearchField extends StatelessWidget {
  final TextEditingController controller;
  final FocusNode? focusNode;
  final String hintText;
  final int maxLength;
  final VoidCallback? onSubmitted;
  final ValueChanged<String>? onChanged;
  final Widget? suffixIcon;
  final bool enabled;

  const PlateSearchField({
    super.key,
    required this.controller,
    this.focusNode,
    this.hintText = 'ABC1234',
    this.maxLength = 7,
    this.onSubmitted,
    this.onChanged,
    this.suffixIcon,
    this.enabled = true,
  });

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      focusNode: focusNode,
      enabled: enabled,
      textCapitalization: TextCapitalization.characters,
      maxLength: maxLength,
      inputFormatters: [
        FilteringTextInputFormatter.allow(RegExp(r'[A-Za-z0-9]')),
        LengthLimitingTextInputFormatter(maxLength),
        _UpperCaseFormatter(),
      ],
      style: const TextStyle(
        color: AppColors.text,
        fontWeight: FontWeight.w800,
        fontSize: 14,
        letterSpacing: 2.5,
      ),
      decoration: InputDecoration(
        hintText: hintText,
        counterText: '',
        hintStyle: TextStyle(
          color: AppColors.muted.withValues(alpha: 0.45),
          fontSize: 14,
          letterSpacing: 2.5,
          fontWeight: FontWeight.w500,
        ),
        prefixIcon: const Icon(
          Icons.directions_car_rounded,
          color: AppColors.warning,
          size: 16,
        ),
        suffixIcon: suffixIcon,
        filled: true,
        fillColor: AppColors.background,
        contentPadding: const EdgeInsets.symmetric(vertical: 7, horizontal: 12),
        enabledBorder: OutlineInputBorder(
          borderSide: const BorderSide(color: AppColors.border),
          borderRadius: BorderRadius.circular(8),
        ),
        focusedBorder: OutlineInputBorder(
          borderSide: const BorderSide(color: AppColors.warning, width: 1.5),
          borderRadius: BorderRadius.circular(8),
        ),
        disabledBorder: OutlineInputBorder(
          borderSide: BorderSide(color: AppColors.border.withValues(alpha: 0.5)),
          borderRadius: BorderRadius.circular(8),
        ),
      ),
      onSubmitted: onSubmitted != null ? (_) => onSubmitted!() : null,
      onChanged: onChanged,
    );
  }
}

/// Formata texto para caixa alta automaticamente.
class _UpperCaseFormatter extends TextInputFormatter {
  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    return newValue.copyWith(
      text: newValue.text.toUpperCase(),
      selection: newValue.selection,
    );
  }
}
