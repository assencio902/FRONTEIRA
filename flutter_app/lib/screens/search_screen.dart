import 'package:flutter/material.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../models/plate_result.dart';
import '../widgets/loading_button.dart';
import 'login_screen.dart';
import 'result_screen.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _plateCtrl = TextEditingController();
  bool _loading = false;

  @override
  void dispose() {
    _plateCtrl.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    final plate = _plateCtrl.text.trim().toUpperCase();
    if (plate.isEmpty) {
      _showError('Digite uma placa.');
      return;
    }
    setState(() => _loading = true);
    try {
      final result = await ApiClient.instance.searchPlate(plate);
      if (!mounted) return;
      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => ResultScreen(plate: plate, result: result),
        ),
      );
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.statusCode == 401) {
        _handleUnauthorized();
      } else {
        _showError('Erro ${e.statusCode}: ${e.message}');
      }
    } catch (e) {
      if (!mounted) return;
      _showError('Falha de conexão. Verifique a rede.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _handleUnauthorized() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Sessão expirada. Faça login novamente.'),
        backgroundColor: Color(0xFFEF4444),
        behavior: SnackBarBehavior.floating,
      ),
    );
    AuthService.instance.logout().then((_) {
      if (!mounted) return;
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (_) => false,
      );
    });
  }

  void _showError(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: const Color(0xFFEF4444),
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _logout() async {
    await AuthService.instance.logout();
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pesquisa de Placa'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            tooltip: 'Sair',
            onPressed: _logout,
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 16),
            const Text(
              'Digite a placa do veículo',
              style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: Color(0xFF94A3B8)),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _plateCtrl,
              textCapitalization: TextCapitalization.characters,
              decoration: const InputDecoration(
                labelText: 'Placa (ex: ABC1234)',
                prefixIcon: Icon(Icons.search),
              ),
              onSubmitted: (_) => _search(),
            ),
            const SizedBox(height: 24),
            LoadingButton(
              label: 'Pesquisar',
              loading: _loading,
              onPressed: _search,
              icon: Icons.manage_search_rounded,
            ),
          ],
        ),
      ),
    );
  }
}
