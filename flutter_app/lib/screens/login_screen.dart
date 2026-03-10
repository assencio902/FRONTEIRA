import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../services/notification_service.dart';
import '../theme/app_theme.dart';
import 'dashboard_screen.dart';

// ─── Paleta mapeada para AppColors ───────────────────────────────────────────
const _kBg1    = AppColors.background;
const _kBg2    = AppColors.background;
const _kCard   = AppColors.surface;
const _kBorder = AppColors.border;
const _kYellow = AppColors.warning;
const _kGreen  = AppColors.success;
const _kMuted  = AppColors.muted;
const _kRed    = AppColors.danger;

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _userCtrl  = TextEditingController();
  final _passCtrl  = TextEditingController();
  final _userFocus = FocusNode();
  final _passFocus = FocusNode();

  bool    _obscure  = true;
  bool    _remember = false;
  bool    _loading  = false;
  String? _error;

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    _userFocus.dispose();
    _passFocus.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final user = _userCtrl.text.trim();
    final pass = _passCtrl.text;

    if (user.isEmpty) {
      setState(() => _error = 'Informe o usuário.');
      return;
    }
    if (pass.isEmpty) {
      setState(() => _error = 'Informe a senha.');
      return;
    }

    setState(() { _loading = true; _error = null; });

    try {
      await AuthService.instance.login(user, pass);
      await NotificationService().syncTokenWithBackend();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const DashboardScreen()),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 401 || e.statusCode == 403) {
        setState(() => _error = 'Usuário ou senha inválidos.');
      } else {
        setState(() => _error = 'Falha no login (${e.statusCode}). Tente novamente.');
      }
    } on TimeoutException {
      if (!mounted) return;
      setState(() => _error = 'A API demorou para responder. Verifique sua conexão.');
    } on SocketException {
      if (!mounted) return;
      setState(() => _error = 'Não foi possível conectar à API. Verifique internet/servidor.');
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = 'Não foi possível realizar o login agora.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        body: Container(
          decoration: const BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [_kBg1, _kBg2],
            ),
          ),
          child: SafeArea(
            child: Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 32),
                child: Container(
                  decoration: BoxDecoration(
                    color: _kCard,
                    borderRadius: BorderRadius.circular(40),
                    border: Border.all(color: _kBorder, width: 2.5),
                    boxShadow: [
                      BoxShadow(
                        color: _kBorder.withValues(alpha: 0.4),
                        blurRadius: 32,
                        spreadRadius: 4,
                      ),
                    ],
                  ),
                  clipBehavior: Clip.antiAlias,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _buildLoginCard(),
                      Padding(
                        padding: const EdgeInsets.only(bottom: 24),
                        child: _buildFooter(),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  // ── Logo Card ─────────────────────────────────────────────────────────────

  // ── Card unificado (brasão + formulário) ──────────────────────────────────

  Widget _buildLoginCard() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
          // Brasão
          ClipRRect(
            borderRadius: const BorderRadius.vertical(top: Radius.circular(40)),
            child: Image.asset(
              'assets/logo_bpfron.png',
              width: double.infinity,
              fit: BoxFit.contain,
              errorBuilder: (_, __, ___) => const Center(
                child: Icon(Icons.shield_rounded, size: 110, color: _kYellow),
              ),
            ),
          ),
          // Formulário
          Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
          // Header
          const Text(
            'ACESSO RESTRITO',
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: _kYellow,
              letterSpacing: 2.0,
            ),
          ),
          const SizedBox(height: 22),

          // Campo Usuário
          _tacticalField(
            controller: _userCtrl,
            focusNode:  _userFocus,
            label:      'Usuário',
            icon:       Icons.person_outline_rounded,
            action:     TextInputAction.next,
            onSubmitted: (_) => _passFocus.requestFocus(),
          ),
          const SizedBox(height: 14),

          // Campo Senha
          _tacticalField(
            controller: _passCtrl,
            focusNode:  _passFocus,
            label:      'Senha',
            icon:       Icons.lock_outline_rounded,
            obscure:    _obscure,
            action:     TextInputAction.done,
            onSubmitted: (_) => _submit(),
            suffix: IconButton(
              icon: Icon(
                _obscure ? Icons.visibility_off_outlined : Icons.visibility_outlined,
                color: _kMuted,
                size: 20,
              ),
              onPressed: () => setState(() => _obscure = !_obscure),
            ),
          ),
          const SizedBox(height: 12),

          // Lembrar-me + Esqueci senha
          Row(
            children: [
              SizedBox(
                width: 20,
                height: 20,
                child: Checkbox(
                  value: _remember,
                  onChanged: (v) => setState(() => _remember = v ?? false),
                  activeColor: _kYellow,
                  checkColor: Colors.black,
                  side: const BorderSide(color: _kBorder, width: 1.5),
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(4)),
                ),
              ),
              const SizedBox(width: 8),
              const Text('Lembrar-me',
                  style: TextStyle(fontSize: 15, color: _kMuted)),
              const Spacer(),
              GestureDetector(
                onTap: () {},
                child: const Text(
                  'Esqueci minha senha',
                  style: TextStyle(
                    fontSize: 14,
                    color: _kYellow,
                    decoration: TextDecoration.underline,
                    decorationColor: _kYellow,
                  ),
                ),
              ),
            ],
          ),

          // Bloco de erro
          if (_error != null) ...[
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: _kRed.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: _kRed.withValues(alpha: 0.4)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.warning_amber_rounded, color: _kRed, size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(_error!,
                        style: const TextStyle(color: _kRed, fontSize: 15)),
                  ),
                ],
              ),
            ),
          ],

          const SizedBox(height: 22),

          // Botão ENTRAR
          SizedBox(
            height: 54,
            child: ElevatedButton(
              onPressed: _loading ? null : _submit,
              style: ElevatedButton.styleFrom(
                backgroundColor: _kYellow,
                foregroundColor: Colors.black,
                disabledBackgroundColor: _kYellow.withValues(alpha: 0.35),
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12)),
                elevation: 0,
              ),
              child: _loading
                  ? const SizedBox(
                      width: 22,
                      height: 22,
                      child: CircularProgressIndicator(
                          strokeWidth: 2.5, color: Colors.black),
                    )
                  : const Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.login_rounded, size: 20),
                        SizedBox(width: 8),
                        Text(
                          'ENTRAR',
                          style: TextStyle(
                            fontWeight: FontWeight.w900,
                            fontSize: 17,
                            letterSpacing: 2.5,
                          ),
                        ),
                      ],
                    ),
            ),
          ),
              ],
            ),
          ),
        ],
      );
  }

  // ── Campo tático reutilizável ─────────────────────────────────────────────

  Widget _tacticalField({
    required TextEditingController controller,
    required FocusNode focusNode,
    required String label,
    required IconData icon,
    bool obscure = false,
    required TextInputAction action,
    ValueChanged<String>? onSubmitted,
    Widget? suffix,
  }) {
    return TextField(
      controller: controller,
      focusNode: focusNode,
      obscureText: obscure,
      textInputAction: action,
      onSubmitted: onSubmitted,
      autocorrect: false,
      style: const TextStyle(color: Colors.white, fontSize: 17),
      decoration: InputDecoration(
        labelText: label,
        labelStyle: const TextStyle(color: _kMuted, fontSize: 16),
        prefixIcon: Icon(icon, color: _kMuted, size: 20),
        suffixIcon: suffix,
        filled: true,
        fillColor: AppColors.surface,
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: _kBorder, width: 1),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: _kYellow, width: 1.5),
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 16, vertical: 18),
      ),
    );
  }

  // ── Rodapé ────────────────────────────────────────────────────────────────

  Widget _buildFooter() {
    return Column(
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 7,
              height: 7,
              decoration:
                  const BoxDecoration(color: _kGreen, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
            const Text('Operador autorizado',
                style: TextStyle(fontSize: 13, color: _kMuted)),
          ],
        ),
        const SizedBox(height: 6),
        const Text(
          'Versão 1.0  •  BPFRON © 2026',
          style: TextStyle(fontSize: 12, color: AppColors.muted),
        ),
      ],
    );
  }
}
