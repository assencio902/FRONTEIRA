import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Botão primário padrão do app (fundo amarelo, texto preto).
///
/// Se [loading] for true, mostra um indicador de progresso no lugar do ícone.
class AppButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool loading;
  final AppButtonVariant variant;

  const AppButton({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.loading = false,
    this.variant = AppButtonVariant.primary,
  });

  /// Atalho para botão secundário (borda, sem preenchimento).
  const AppButton.secondary({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.loading = false,
  }) : variant = AppButtonVariant.secondary;

  /// Atalho para botão de perigo (fundo vermelho).
  const AppButton.danger({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.loading = false,
  }) : variant = AppButtonVariant.danger;

  @override
  Widget build(BuildContext context) {
    final style = _resolveStyle();
    final effectiveOnPressed = loading ? null : onPressed;

    return SizedBox(
      height: 50,
      child: ElevatedButton(
        style: style,
        onPressed: effectiveOnPressed,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          mainAxisSize: MainAxisSize.min,
          children: [
            if (loading)
              SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2.5,
                  color: _foregroundColor,
                ),
              )
            else if (icon != null)
              Icon(icon, size: 20),
            if (icon != null || loading) const SizedBox(width: 8),
            Text(label),
          ],
        ),
      ),
    );
  }

  Color get _foregroundColor {
    switch (variant) {
      case AppButtonVariant.primary:
        return Colors.black;
      case AppButtonVariant.secondary:
        return AppColors.muted;
      case AppButtonVariant.danger:
        return Colors.white;
    }
  }

  ButtonStyle _resolveStyle() {
    switch (variant) {
      case AppButtonVariant.primary:
        return ElevatedButton.styleFrom(
          backgroundColor: AppColors.warning,
          foregroundColor: Colors.black,
          disabledBackgroundColor: AppColors.warning.withValues(alpha: 0.35),
          disabledForegroundColor: Colors.black54,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.4,
          ),
        );
      case AppButtonVariant.secondary:
        return ElevatedButton.styleFrom(
          backgroundColor: AppColors.surface,
          foregroundColor: AppColors.muted,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: const BorderSide(color: AppColors.border),
          ),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.4,
          ),
        );
      case AppButtonVariant.danger:
        return ElevatedButton.styleFrom(
          backgroundColor: AppColors.danger,
          foregroundColor: Colors.white,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: const TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            letterSpacing: 0.4,
          ),
        );
    }
  }
}

enum AppButtonVariant { primary, secondary, danger }
