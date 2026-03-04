import 'package:flutter/material.dart';

/// Paleta oficial BPFRON — tema policial escuro.
abstract final class AppColors {
  static const Color background = Color(0xFF081A0E); // verde escuro profundo
  static const Color primary    = Color(0xFF16A34A); // verde vivo (ações)
  static const Color accent     = Color(0xFF4ADE80); // verde claro (destaque)
  static const Color success    = Color(0xFF22C55E); // verde sucesso
  static const Color warning    = Color(0xFFFACC15); // amarelo/ouro
  static const Color danger     = Color(0xFFEF4444); // vermelho
  static const Color text       = Color(0xFFE5E7EB); // texto claro
  static const Color surface    = Color(0xFF0D2218); // verde superfície
  static const Color border     = Color(0xFF1A3828); // verde borda
  static const Color muted      = Color(0xFF8FA89A); // cinza-verde suave
}

abstract final class AppTheme {
  static ThemeData get dark => ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: AppColors.background,
        colorScheme: const ColorScheme.dark(
          primary:     AppColors.warning,
          secondary:   AppColors.success,
          surface:     AppColors.surface,
          error:       AppColors.danger,
          onPrimary:   Colors.black,
          onSecondary: Colors.black,
          onSurface:   AppColors.text,
          onError:     Colors.white,
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: AppColors.background,
          foregroundColor: AppColors.text,
          elevation: 0,
        ),
        cardTheme: CardThemeData(
          color: AppColors.surface,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
          elevation: 0,
        ),
        dividerTheme: const DividerThemeData(color: AppColors.border),
        iconTheme: const IconThemeData(color: AppColors.text),
        textTheme: const TextTheme(
          bodyLarge:    TextStyle(color: AppColors.text),
          bodyMedium:   TextStyle(color: AppColors.text),
          bodySmall:    TextStyle(color: AppColors.muted),
          titleLarge:   TextStyle(color: AppColors.text, fontWeight: FontWeight.w700),
          titleMedium:  TextStyle(color: AppColors.text, fontWeight: FontWeight.w600),
          titleSmall:   TextStyle(color: AppColors.text, fontWeight: FontWeight.w600),
          labelLarge:   TextStyle(color: AppColors.text),
          labelMedium:  TextStyle(color: AppColors.muted),
          labelSmall:   TextStyle(color: AppColors.muted),
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: AppColors.surface,
          hintStyle: TextStyle(color: AppColors.text.withValues(alpha: 0.45)),
          enabledBorder: OutlineInputBorder(
            borderSide: const BorderSide(color: AppColors.border),
            borderRadius: BorderRadius.circular(14),
          ),
          focusedBorder: OutlineInputBorder(
            borderSide: const BorderSide(color: AppColors.warning, width: 1.6),
            borderRadius: BorderRadius.circular(14),
          ),
          errorBorder: OutlineInputBorder(
            borderSide: const BorderSide(color: AppColors.danger),
            borderRadius: BorderRadius.circular(14),
          ),
          focusedErrorBorder: OutlineInputBorder(
            borderSide: const BorderSide(color: AppColors.danger, width: 1.6),
            borderRadius: BorderRadius.circular(14),
          ),
          labelStyle: const TextStyle(color: AppColors.muted),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            backgroundColor: AppColors.warning,
            foregroundColor: Colors.black,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
            ),
            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 16),
            textStyle: const TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.4,
            ),
          ),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(
            foregroundColor: AppColors.warning,
            side: const BorderSide(color: AppColors.border),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(14),
            ),
          ),
        ),
        checkboxTheme: CheckboxThemeData(
          fillColor: WidgetStateProperty.resolveWith(
            (s) => s.contains(WidgetState.selected)
                ? AppColors.warning
                : Colors.transparent,
          ),
          checkColor: WidgetStateProperty.all(Colors.black),
        ),
        textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(foregroundColor: AppColors.warning),
        ),
      );
}
