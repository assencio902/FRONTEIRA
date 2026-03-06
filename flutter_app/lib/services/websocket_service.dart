import 'dart:async';

// Serviço de WebSocket (stub básico)
class WebSocketService {
  static final _eventController = StreamController<Map<String, dynamic>>.broadcast();
  bool _connected = false;
  
  Stream<Map<String, dynamic>> get eventStream => _eventController.stream;
  
  bool get isConnected => _connected;
  
  Future<void> connect() async {
    // TODO: Implementar conexão WebSocket real
    _connected = true;
    print('🔌 WebSocket conectado (stub)');
  }
  
  void disconnect() {
    _connected = false;
    print('🔌 WebSocket desconectado');
  }
  
  void dispose() {
    disconnect();
    _eventController.close();
  }
}
